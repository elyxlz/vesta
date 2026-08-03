use std::fs::File;

use bollard::Docker;

use crate::docker::{
    container_created, container_name, container_size_root_fs, container_size_rw, container_status,
    create_container, ensure_container_removed, env_file_names, guard_alive, handoff_boot_reason,
    handoff_shutdown_reason, read_env_value, start_container, stop_container_with_timeout,
    validate_name, AgentEnvConfig, ContainerStatus, DockerError,
};
use crate::types::{BackupInfo, BackupType, RetentionPolicy};

pub const DEFAULT_RETENTION_PERIODIC: usize = 2;
pub const DEFAULT_RETENTION_PRE_UPDATE_VERSIONS: usize = 2;
const MIN_DISK_SPACE_BYTES: u64 = 1_000_000_000; // 1 GB
const DISK_SPACE_MARGIN_BYTES: u64 = 500_000_000; // 500 MB margin above container size
pub const BACKUP_STOP_TIMEOUT_SECS: i32 = 30;
pub const MIN_AGE_FOR_BACKUP_SECS: u64 = 6 * 3600;

/// Acquire an exclusive file lock for the given agent. The lock is held for the
/// lifetime of the returned Flock. Used to coordinate between the vestad API and
/// the `vestad backup export/import` CLI which bypasses the server.
pub fn agent_file_lock(name: &str) -> Result<nix::fcntl::Flock<File>, DockerError> {
    let lock_dir = crate::paths::config_dir_or_relative().join("locks");
    std::fs::create_dir_all(&lock_dir)
        .map_err(|e| DockerError::Failed(format!("failed to create lock dir: {e}")))?;
    let lock_path = lock_dir.join(format!("{name}.lock"));
    let file = File::create(&lock_path)
        .map_err(|e| DockerError::Failed(format!("failed to create lock file: {e}")))?;
    nix::fcntl::Flock::lock(file, nix::fcntl::FlockArg::LockExclusive)
        .map_err(|(_, errno)| DockerError::Failed(format!("failed to acquire agent lock: {errno}")))
}

/// Ensure the repo filesystem has room. The first snapshot writes the whole root
/// fs (`docker export`), so size off that; later snapshots only write the diff,
/// so the writable-layer size is an adequate floor.
async fn check_disk_space(docker: &Docker, name: &str, cname: &str) -> Result<(), DockerError> {
    let repo_fs = crate::paths::config_dir_or_relative();
    std::fs::create_dir_all(&repo_fs)
        .map_err(|e| DockerError::Failed(format!("failed to create backup dir: {e}")))?;

    let stat = nix::sys::statvfs::statvfs(repo_fs.as_path())
        .map_err(|e| DockerError::Failed(format!("failed to check disk space: {e}")))?;

    let available = stat.blocks_available() * stat.fragment_size();

    let container_size = if crate::restic::repo_initialized(name) {
        container_size_rw(docker, cname).await.unwrap_or(0)
    } else {
        container_size_root_fs(docker, cname).await.unwrap_or(0)
    };
    let required = std::cmp::max(
        container_size + DISK_SPACE_MARGIN_BYTES,
        MIN_DISK_SPACE_BYTES,
    );

    if available < required {
        let avail_mb = available / 1_000_000;
        let required_mb = required / 1_000_000;
        return Err(DockerError::Failed(format!(
            "insufficient disk space for backup ({avail_mb}MB available, need at least {required_mb}MB)"
        )));
    }
    Ok(())
}

/// Returns the container's age in seconds, or None if unknown.
pub async fn container_age_secs(docker: &Docker, name: &str) -> Option<u64> {
    let cname = container_name(name);
    let created = container_created(docker, &cname).await?;
    let created_epoch = parse_rfc3339_epoch(created.trim())?;
    Some(crate::time_utils::now_epoch_secs().saturating_sub(created_epoch))
}

/// Parse an RFC3339 timestamp (e.g. "2026-04-07T13:11:12.123Z") to unix epoch seconds.
fn parse_rfc3339_epoch(ts: &str) -> Option<u64> {
    let dt = time::OffsetDateTime::parse(ts.trim(), &time::format_description::well_known::Rfc3339)
        .ok()?;
    u64::try_from(dt.unix_timestamp()).ok()
}

const TEMP_IMAGE_REPO_PREFIX: &str = "vesta-backup-tmp";

/// Create a backup of the given agent without ever stopping it. A running container is captured
/// via `docker commit` (Docker pauses it for the seconds the commit takes), then the committed
/// image is exported through a temp container into restic; a stopped container exports directly.
pub async fn create_backup(
    docker: &Docker,
    name: &str,
    backup_type: BackupType,
    from_version: Option<&str>,
) -> Result<BackupInfo, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = guard_alive(container_status(docker, &cname).await, name)?;
    check_disk_space(docker, name, &cname).await?;

    let result = if cs == ContainerStatus::Running {
        // One shared name for the throwaway image repo and export container.
        let temp_cname = format!("{TEMP_IMAGE_REPO_PREFIX}-{name}");
        let image = format!("{temp_cname}:latest");
        // A leftover temp container/image from a crashed run must not fail this one.
        crate::docker::remove_container_force(docker, &temp_cname).await.ok();
        crate::docker::remove_image(docker, &image).await.ok();
        tracing::info!(agent = %name, backup_type = %backup_type, "committing running container for backup");
        crate::docker::commit_container_to_image(docker, &cname, &temp_cname, "latest").await?;
        let snap = match crate::docker::create_plain_container(docker, &image, &temp_cname).await {
            Ok(()) => crate::restic::snapshot(name, &backup_type, from_version, &temp_cname).await,
            Err(e) => Err(e),
        };
        crate::docker::remove_container_force(docker, &temp_cname).await.ok();
        crate::docker::remove_image(docker, &image).await.ok();
        snap
    } else {
        crate::restic::snapshot(name, &backup_type, from_version, &cname).await
    };

    match &result {
        Ok(info) => {
            tracing::info!(agent = %name, backup_type = %info.backup_type, backup_id = %info.id, size = info.size, "backup created");
        }
        Err(e) => tracing::error!(agent = %name, error = %e, "backup failed"),
    }

    result
}

/// List all backups for the given agent, sorted by date descending. Agent identity
/// is the env file vestad writes at creation (the durable record), not the
/// container: an agent whose container is currently absent, e.g. mid recovery from
/// a failed restore, still lists.
pub async fn list_backups(
    agents_dir: &std::path::Path,
    name: &str,
) -> Result<Vec<BackupInfo>, DockerError> {
    validate_name(name)?;
    if !env_file_names(agents_dir).iter().any(|owned| owned == name) {
        return Err(DockerError::NotFound(format!("agent '{name}' not found")));
    }
    crate::restic::list(name).await
}

/// Aggregate backups across every owned agent (one repo each).
pub async fn list_all_backups(docker: &Docker) -> Vec<BackupInfo> {
    let owned_agents = list_agent_names(docker).await;
    let mut all = Vec::new();
    for name in &owned_agents {
        match crate::restic::list(name).await {
            Ok(mut backups) => all.append(&mut backups),
            Err(e) => tracing::warn!(agent = %name, error = %e, "failed to list backups"),
        }
    }
    all.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    all
}

/// Restore an agent from a backup snapshot.
/// Creates a pre-restore safety backup first, then replaces the container.
pub async fn restore_backup(
    docker: &Docker,
    name: &str,
    backup_id: &str,
    env_config: &AgentEnvConfig,
    user_mounts: &[crate::mounts::HostMount],
) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);

    // Verify the backup exists and belongs to this agent before doing anything destructive.
    // This is the durable env-file check (not container status), so an agent whose
    // container is already gone, e.g. a prior restore that died after removal, can
    // still restore instead of being locked out by the failure it's recovering from.
    let backups = list_backups(&env_config.agents_dir, name).await?;
    if !backups.iter().any(|b| b.id == backup_id) {
        return Err(DockerError::NotFound(format!(
            "backup '{backup_id}' not found"
        )));
    }

    let status = container_status(docker, &cname).await;
    let container_present = status != ContainerStatus::NotFound;

    if container_present {
        // Stop once, take safety backup, then remove — avoids a redundant stop/start cycle.
        if status == ContainerStatus::Running {
            handoff_shutdown_reason(docker, name, &cname, &crate::lifecycle::RESTORE_SHUTDOWN)
                .await;
            stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS)
                .await
                .ok();
        }
        tracing::info!(agent = %name, "creating pre-restore safety backup");
        if let Err(e) = crate::restic::snapshot(name, &BackupType::PreRestore, None, &cname).await {
            if status == ContainerStatus::Running {
                handoff_boot_reason(docker, name, &cname, &crate::lifecycle::RESTORE_ABORTED).await;
                start_container(docker, &cname).await;
            }
            return Err(DockerError::Failed(format!(
                "pre-restore safety backup failed: {e}"
            )));
        }
        // Confirm it's actually gone (don't swallow): docker rm can return before the name frees,
        // and a create colliding on the name would delete the env file while the old container
        // still exists. The pre-restore safety backup is already taken, so restart and bail.
        if let Err(e) = ensure_container_removed(docker, &cname).await {
            if status == ContainerStatus::Running {
                handoff_boot_reason(docker, name, &cname, &crate::lifecycle::RESTORE_ABORTED).await;
                start_container(docker, &cname).await;
            }
            return Err(e);
        }
    } else {
        tracing::warn!(agent = %name, "container already absent before restore; skipping safety backup");
    }

    let port = read_env_value(&env_config.agents_dir, name, "WS_PORT")
        .and_then(|v| v.parse().ok())
        .ok_or_else(|| DockerError::Failed("agent has no port in env file".into()))?;
    tracing::debug!(agent = %name, backup_id = %backup_id, "restoring snapshot into image");
    let image = crate::restic::restore_to_image(name, backup_id).await?;
    create_container(
        docker,
        env_config,
        crate::docker::ContainerSpec {
            cname: &cname,
            image: &image,
            port,
            agent_name: name,
            user_mounts,
        },
    )
    .await?;

    handoff_boot_reason(docker, name, &cname, &crate::lifecycle::RESTORE_BOOT).await;
    if !start_container(docker, &cname).await {
        return Err(DockerError::Failed("failed to start restored agent".into()));
    }

    Ok(())
}

/// Delete a backup snapshot. Verifies the backup belongs to the named agent and
/// that the named agent is managed by this vestad instance.
pub async fn delete_backup(
    docker: &Docker,
    name: &str,
    backup_id: &str,
) -> Result<(), DockerError> {
    let owned_agents = list_agent_names(docker).await;
    if !owned_agents.iter().any(|owned| owned == name) {
        return Err(DockerError::NotFound(format!("agent '{name}' not found")));
    }
    let backups = crate::restic::list(name).await?;
    if !backups.iter().any(|b| b.id == backup_id) {
        return Err(DockerError::Failed(format!(
            "backup '{backup_id}' not found for agent '{name}'"
        )));
    }
    crate::restic::forget(name, &[backup_id.to_string()]).await
}

/// Determine which auto-backups should be deleted based on the retention policy.
/// Returns the IDs of backups to delete.
pub fn compute_backups_to_delete(
    backups: &[BackupInfo],
    retention: &RetentionPolicy,
) -> Vec<String> {
    let mut to_delete = Vec::new();

    let mut periodic: Vec<&BackupInfo> = backups
        .iter()
        .filter(|b| b.backup_type == BackupType::Periodic)
        .collect();
    periodic.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    to_delete.extend(periodic.into_iter().skip(retention.periodic).map(|b| b.id.clone()));

    // Pre-update snapshots are retained as whole version sets: the newest
    // `pre_update_versions` distinct from-versions survive, older versions go.
    let mut pre_update: Vec<&BackupInfo> = backups
        .iter()
        .filter(|b| b.backup_type == BackupType::PreUpdate)
        .collect();
    pre_update.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    let mut kept_versions: Vec<String> = Vec::new();
    for info in pre_update {
        let version = info.from_version.clone().unwrap_or_default();
        if kept_versions.contains(&version) {
            continue;
        }
        if kept_versions.len() < retention.pre_update_versions {
            kept_versions.push(version);
        } else {
            to_delete.push(info.id.clone());
        }
    }

    to_delete
}

/// Run retention cleanup for an agent's auto-backups.
/// Pass existing backups list to avoid a redundant snapshot listing.
pub async fn cleanup_backups(name: &str, backups: &[BackupInfo], retention: &RetentionPolicy) {
    let to_delete = compute_backups_to_delete(backups, retention);
    if to_delete.is_empty() {
        return;
    }
    tracing::info!(agent = %name, count = to_delete.len(), "cleaning up old backups");
    if let Err(e) = crate::restic::forget(name, &to_delete).await {
        tracing::warn!(agent = %name, error = %e, "failed to prune expired backups");
    }
}

/// List all agent names that have containers.
pub async fn list_agent_names(docker: &Docker) -> Vec<String> {
    crate::docker::list_managed_agents(docker)
        .await
        .into_iter()
        .map(|a| a.agent_name)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restore_backup_confirms_removal_before_create() {
        // restore_backup recreates under the SAME name, so the old container must be confirmed
        // gone before create. A best-effort `remove_container_force(...).await.ok()` could let
        // the create collide on the name after the env file was already rewritten (docker rm can
        // return before the name frees, or fail transiently), same failure mode as rebuild_agent.
        let src = include_str!("backup.rs");
        let restore_start = src
            .find("pub async fn restore_backup")
            .expect("restore_backup present");
        let delete_start = src
            .find("pub async fn delete_backup")
            .expect("delete_backup present");
        assert!(
            restore_start < delete_start,
            "restore_backup must appear before delete_backup for this test to slice correctly"
        );
        let restore_body = &src[restore_start..delete_start];

        let remove_pos = restore_body
            .find("ensure_container_removed")
            .expect("restore_backup must confirm the old container is gone via ensure_container_removed before recreating");
        let create_pos = restore_body
            .find("create_container")
            .expect("create_container must be called in restore_backup");
        assert!(
            remove_pos < create_pos,
            "restore_backup must remove the old container before creating the new one"
        );
        assert!(
            !restore_body.contains("remove_container_force"),
            "restore_backup must use ensure_container_removed (confirms gone), not the best-effort remove_container_force"
        );
    }

    #[test]
    fn create_backup_never_stops_or_starts_containers() {
        // Backups are restart-free by design: a running container is captured via
        // docker commit (pause), never stopped. Only restore may stop a container.
        let src = include_str!("backup.rs");
        let create_start = src
            .find("pub async fn create_backup")
            .expect("create_backup present");
        let restore_start = src
            .find("pub async fn restore_backup")
            .expect("restore_backup present");
        assert!(create_start < restore_start, "create_backup precedes restore_backup");
        let backup_paths = &src[create_start..restore_start];
        assert!(
            !backup_paths.contains("stop_container_with_timeout")
                && !backup_paths.contains("start_container("),
            "no backup path may stop or start a container"
        );
        // Built at runtime so this test's own source can't satisfy the search.
        let banned_cycle_fn = ["with_container", "_paused"].concat();
        assert!(
            !src[..create_start].contains(&banned_cycle_fn) && !backup_paths.contains(&banned_cycle_fn),
            "the stop/restart backup cycle must stay deleted"
        );
    }

    // ── Retention policy tests ────────────────────────────────────

    const DEFAULT_RETENTION: RetentionPolicy = RetentionPolicy { periodic: 2, pre_update_versions: 2 };

    fn make_backup(agent: &str, bt: BackupType, ts: &str) -> BackupInfo {
        BackupInfo {
            id: format!("{agent}-{bt}-{ts}"),
            agent_name: agent.to_string(),
            backup_type: bt,
            created_at: ts.to_string(),
            size: 1000,
            from_version: None,
        }
    }

    fn make_pre_update(agent: &str, version: &str, ts: &str) -> BackupInfo {
        BackupInfo { from_version: Some(version.to_string()), ..make_backup(agent, BackupType::PreUpdate, ts) }
    }

    #[test]
    fn retention_keeps_newest_periodic() {
        let backups = vec![
            make_backup("a", BackupType::Periodic, "20260401-120000"),
            make_backup("a", BackupType::Periodic, "20260404-120000"),
            make_backup("a", BackupType::Periodic, "20260407-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert_eq!(to_delete, vec![backups[0].id.clone()]);
    }

    #[test]
    fn retention_keeps_newest_distinct_pre_update_versions() {
        let backups = vec![
            make_pre_update("a", "v0.1.180", "20260401-120000"),
            make_pre_update("a", "v0.1.181", "20260404-120000"),
            make_pre_update("a", "v0.1.182", "20260407-120000"),
            // A second snapshot of a kept version stays (same set).
            make_pre_update("a", "v0.1.182", "20260407-130000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert_eq!(to_delete, vec![backups[0].id.clone()]);
    }

    #[test]
    fn retention_ignores_manual_and_pre_restore() {
        let backups = vec![
            make_backup("a", BackupType::Manual, "20260401-120000"),
            make_backup("a", BackupType::Manual, "20260402-120000"),
            make_backup("a", BackupType::Manual, "20260403-120000"),
            make_backup("a", BackupType::PreRestore, "20260401-120000"),
            make_backup("a", BackupType::PreRestore, "20260402-120000"),
            make_backup("a", BackupType::PreRestore, "20260403-120000"),
        ];
        assert!(compute_backups_to_delete(&backups, &DEFAULT_RETENTION).is_empty());
    }

    #[test]
    fn retention_empty_list() {
        assert!(compute_backups_to_delete(&[], &DEFAULT_RETENTION).is_empty());
    }
}
