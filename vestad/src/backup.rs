use std::fs::File;

use bollard::Docker;

use crate::docker::{
    container_created, container_name, container_size_rw, container_status, create_container,
    docker_cp_content, docker_root_dir, image_exists, inspect_container,
    list_images_by_reference, remove_container_force, remove_image,
    snapshot_container, start_container, stop_container_with_timeout, tag_image, validate_name,
    AgentEnvConfig, ContainerStatus, DockerError,
};
use crate::types::{BackupInfo, BackupType, RetentionPolicy};

const BACKUP_IMAGE_PREFIX: &str = "vesta-backup";
pub const DEFAULT_RETENTION_DAILY: usize = 3;
pub const DEFAULT_RETENTION_WEEKLY: usize = 2;
pub const DEFAULT_RETENTION_MONTHLY: usize = 1;
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

/// Check that Docker's data root has enough free disk space for a backup.
/// Requires at least the container's writable layer size + margin, with a 1GB floor.
async fn check_disk_space(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    let root = docker_root_dir(docker).await;

    let stat = nix::sys::statvfs::statvfs(root.as_str())
        .map_err(|e| DockerError::Failed(format!("failed to check disk space: {}", e)))?;

    let available = stat.blocks_available() * stat.fragment_size();

    let container_size = container_size_rw(docker, cname).await.unwrap_or(0);
    let required = std::cmp::max(container_size + DISK_SPACE_MARGIN_BYTES, MIN_DISK_SPACE_BYTES);

    if available < required {
        let avail_mb = available / 1_000_000;
        let required_mb = required / 1_000_000;
        return Err(DockerError::Failed(format!(
            "insufficient disk space for backup ({}MB available, need at least {}MB)",
            avail_mb, required_mb
        )));
    }
    Ok(())
}

/// Build a backup image tag from components.
pub fn backup_tag(agent_name: &str, backup_type: &BackupType, timestamp: &str) -> String {
    format!(
        "{}:{}_{}_{}", BACKUP_IMAGE_PREFIX, agent_name, backup_type, timestamp
    )
}

/// Parse a backup image tag into (agent_name, backup_type, timestamp).
/// Supports both new format (`_` delimiter) and legacy format (`-` delimiter).
pub fn parse_backup_tag(tag: &str) -> Option<(String, BackupType, String)> {
    let repo_tag = tag.strip_prefix(&format!("{}:", BACKUP_IMAGE_PREFIX))?;

    // New format: {name}_{type}_{YYYYMMDD-HHMMSS} — unambiguous since `_` is not allowed in agent names
    let mut parts = repo_tag.rsplitn(3, '_');
    let timestamp = parts.next()?;
    if let (Some(type_str), Some(name)) = (parts.next(), parts.next()) {
        if !name.is_empty() && timestamp.len() == 15 && timestamp.as_bytes()[8] == b'-' {
            if let Ok(bt) = type_str.parse::<BackupType>() {
                return Some((name.to_string(), bt, timestamp.to_string()));
            }
        }
    }

    // Legacy format: {name}-{type}-{YYYYMMDD-HHMMSS} — ambiguous, uses suffix guessing
    crate::migrations::parse_backup_tag_legacy(repo_tag)
}

pub fn now_timestamp() -> String {
    now_timestamp_from_epoch(crate::time_utils::now_epoch_secs())
}

pub fn now_timestamp_from_epoch(epoch_secs: u64) -> String {
    let dt = time::OffsetDateTime::from_unix_timestamp(epoch_secs as i64)
        .expect("epoch seconds within valid range");
    let fmt = time::macros::format_description!("[year][month][day]-[hour][minute][second]");
    dt.format(&fmt).expect("timestamp format never fails")
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
    let dt = time::OffsetDateTime::parse(
        ts.trim(),
        &time::format_description::well_known::Rfc3339,
    )
    .ok()?;
    Some(dt.unix_timestamp() as u64)
}

/// Snapshot the container to a backup image without managing container lifecycle.
/// Caller is responsible for stopping/starting the container.
async fn commit_backup(
    docker: &Docker,
    cname: &str,
    name: &str,
    backup_type: &BackupType,
) -> Result<BackupInfo, DockerError> {
    let ts = now_timestamp();
    let tag = backup_tag(name, backup_type, &ts);
    let name_label = format!("LABEL vesta.agent_name={}", name);
    let type_label = format!("LABEL vesta.backup_type={}", backup_type);
    let date_label = format!("LABEL vesta.backup_date={}", ts);

    snapshot_container(docker, cname, &tag, &[&name_label, &type_label, &date_label]).await?;

    let images = list_images_by_reference(docker, &tag).await;
    let size = images.first().map(|(_, sz)| *sz).unwrap_or(0);

    Ok(BackupInfo {
        id: tag,
        agent_name: name.to_string(),
        backup_type: backup_type.clone(),
        created_at: ts,
        size,
    })
}

/// Create a backup of the given agent. Stops the container during commit, then restarts.
pub async fn create_backup(
    docker: &Docker,
    name: &str,
    backup_type: BackupType,
) -> Result<BackupInfo, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(docker, &cname).await;
    match cs {
        ContainerStatus::NotFound => {
            return Err(DockerError::NotFound(format!(
                "agent '{}' not found",
                name
            )))
        }
        ContainerStatus::Dead => {
            return Err(DockerError::BrokenState(format!(
                "agent '{}' is in a broken state",
                name
            )))
        }
        _ => {}
    }

    check_disk_space(docker, &cname).await?;

    let was_running = cs == ContainerStatus::Running;
    if was_running {
        tracing::info!(agent = %name, backup_type = %backup_type, "stopping agent for backup");
        if let Err(err) = docker_cp_content(
            docker,
            &cname,
            "backup — paused for backup",
            "/root/agent/data/restart_reason",
        )
        .await
        {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
        stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS).await.ok();
    }

    tracing::info!(agent = %name, "committing backup image");
    let result = commit_backup(docker, &cname, name, &backup_type).await;

    if was_running {
        tracing::info!(agent = %name, "restarting agent");
        start_container(docker, &cname).await;
    }

    match &result {
        Ok(info) => {
            tracing::info!(agent = %name, backup_id = %info.id, size = info.size, "backup committed")
        }
        Err(e) => tracing::error!(agent = %name, error = %e, "backup commit failed"),
    }

    result
}

/// Create multiple backup types in a single stop/start cycle.
/// Commits once for the first type, then `docker tag` for the rest (zero-cost shared layers).
/// Returns a result per type — failures don't block other types.
/// NOTE: Tagged images share the first type's Docker labels (vesta.backup_type). This is fine
/// because the system identifies backup type from the image tag string, not from labels.
pub async fn create_backups_batch(
    docker: &Docker,
    name: &str,
    types: Vec<BackupType>,
) -> Vec<(BackupType, Result<BackupInfo, DockerError>)> {
    let fail_all =
        |types: Vec<BackupType>,
         e: DockerError|
         -> Vec<(BackupType, Result<BackupInfo, DockerError>)> {
            types.into_iter().map(|bt| (bt, Err(e.clone()))).collect()
        };

    if types.is_empty() {
        return Vec::new();
    }

    let cname = match validate_name(name).map(|_| container_name(name)) {
        Ok(c) => c,
        Err(e) => return fail_all(types, e),
    };

    let cs = container_status(docker, &cname).await;
    match cs {
        ContainerStatus::NotFound => {
            return fail_all(
                types,
                DockerError::NotFound(format!("agent '{}' not found", name)),
            );
        }
        ContainerStatus::Dead => {
            return fail_all(
                types,
                DockerError::BrokenState(format!("agent '{}' is in a broken state", name)),
            );
        }
        _ => {}
    }

    if let Err(e) = check_disk_space(docker, &cname).await {
        return fail_all(types, e);
    }

    let was_running = cs == ContainerStatus::Running;
    if was_running {
        if let Err(err) = docker_cp_content(
            docker,
            &cname,
            "backup — paused for backup",
            "/root/agent/data/restart_reason",
        )
        .await
        {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
        stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS).await.ok();
    }

    let mut results = Vec::new();
    let first_type = &types[0];
    let first_result = commit_backup(docker, &cname, name, first_type).await;

    match first_result {
        Ok(first_info) => {
            let size = first_info.size;
            let ts = first_info.created_at.clone();
            let source_tag = first_info.id.clone();
            results.push((first_type.clone(), Ok(first_info)));

            for bt in &types[1..] {
                let new_tag = backup_tag(name, bt, &ts);
                let (repo, img_tag) = new_tag.rsplit_once(':').unwrap_or((&new_tag, "latest"));
                match tag_image(docker, &source_tag, repo, img_tag).await {
                    Ok(()) => {
                        results.push((
                            bt.clone(),
                            Ok(BackupInfo {
                                id: new_tag,
                                agent_name: name.to_string(),
                                backup_type: bt.clone(),
                                created_at: ts.clone(),
                                size,
                            }),
                        ));
                    }
                    Err(_) => {
                        results.push((
                            bt.clone(),
                            Err(DockerError::Failed(format!(
                                "failed to tag backup as {}",
                                bt
                            ))),
                        ));
                    }
                }
            }
        }
        Err(e) => {
            results.push((first_type.clone(), Err(e)));
            for bt in &types[1..] {
                results.push((
                    bt.clone(),
                    Err(DockerError::Failed("backup commit failed".into())),
                ));
            }
        }
    }

    if was_running {
        start_container(docker, &cname).await;
    }

    results
}

/// Query Docker for backup images matching a reference and optional agent name, sorted by date descending.
async fn query_backup_images(
    docker: &Docker,
    reference: &str,
    agent_name: Option<&str>,
) -> Vec<BackupInfo> {
    let images = list_images_by_reference(docker, reference).await;

    let mut backups: Vec<BackupInfo> = images
        .into_iter()
        .filter_map(|(tag, size)| {
            let (parsed_name, backup_type, timestamp) = parse_backup_tag(&tag)?;
            if let Some(name) = agent_name {
                if parsed_name != name {
                    return None;
                }
            }
            Some(BackupInfo {
                id: tag,
                agent_name: parsed_name,
                backup_type,
                created_at: timestamp,
                size,
            })
        })
        .collect();

    backups.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    backups
}

/// List all backups for the given agent, sorted by date descending.
pub async fn list_backups(docker: &Docker, name: &str) -> Result<Vec<BackupInfo>, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    if container_status(docker, &cname).await == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!(
            "agent '{}' not found",
            name
        )));
    }
    let owned_agents = list_agent_names(docker).await;
    if !owned_agents.iter().any(|owned| owned == name) {
        return Err(DockerError::NotFound(format!(
            "agent '{}' not found",
            name
        )));
    }
    let reference = format!("{}:{}*", BACKUP_IMAGE_PREFIX, name);
    let backups = query_backup_images(docker, &reference, Some(name)).await;
    Ok(filter_backups_by_owned_agents(backups, &owned_agents))
}

/// List all backup images belonging to agents managed by this vestad instance.
/// Docker images are a machine-wide resource, so we filter out images whose
/// `{agent_name}` prefix is not in the current user's agent set. This prevents
/// leaking other OS users' backups on shared hosts.
pub async fn list_all_backups(docker: &Docker) -> Vec<BackupInfo> {
    let reference = format!("{}:*", BACKUP_IMAGE_PREFIX);
    let backups = query_backup_images(docker, &reference, None).await;
    let owned_agents = list_agent_names(docker).await;
    filter_backups_by_owned_agents(backups, &owned_agents)
}

/// Pure filter: keep only backups whose `agent_name` is in `owned_agents`.
/// Extracted for unit testing and shared between list and list-all paths.
pub fn filter_backups_by_owned_agents(
    backups: Vec<BackupInfo>,
    owned_agents: &[String],
) -> Vec<BackupInfo> {
    backups
        .into_iter()
        .filter(|backup| owned_agents.iter().any(|owned| owned == &backup.agent_name))
        .collect()
}

/// Restore an agent from a backup image.
/// Creates a pre-restore safety backup first, then replaces the container.
pub async fn restore_backup(
    docker: &Docker,
    name: &str,
    backup_id: &str,
    env_config: &AgentEnvConfig,
    manage_core_code: bool,
) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);

    if !image_exists(docker, backup_id).await {
        return Err(DockerError::NotFound(format!(
            "backup '{}' not found",
            backup_id
        )));
    }

    let info = inspect_container(docker, &cname, Some(&env_config.agents_dir)).await;
    if info.status == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!(
            "agent '{}' not found",
            name
        )));
    }

    // Stop once, commit safety backup, then remove — avoids a redundant stop/start cycle
    if info.status == ContainerStatus::Running {
        stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS).await.ok();
    }
    tracing::info!(agent = %name, "creating pre-restore safety backup");
    if let Err(e) = commit_backup(docker, &cname, name, &BackupType::PreRestore).await {
        // Restart the container before returning the error
        if info.status == ContainerStatus::Running {
            start_container(docker, &cname).await;
        }
        return Err(DockerError::Failed(format!(
            "pre-restore safety backup failed: {e}"
        )));
    }
    remove_container_force(docker, &cname).await.ok();

    let port = info
        .port
        .ok_or_else(|| DockerError::Failed("agent has no port in env file".into()))?;
    tracing::debug!(agent = %name, backup_id = %backup_id, "creating container from backup image");
    create_container(docker, &cname, backup_id, port, name, env_config, manage_core_code, None).await?;

    if !start_container(docker, &cname).await {
        return Err(DockerError::Failed(
            "failed to start restored agent".into(),
        ));
    }

    Ok(())
}

/// Delete a backup image. Verifies the backup belongs to the named agent and
/// that the named agent is managed by this vestad instance. The latter check
/// prevents a user from deleting another OS user's backup on a shared host
/// where docker images are a machine-wide resource.
pub async fn delete_backup(
    docker: &Docker,
    name: &str,
    backup_id: &str,
) -> Result<(), DockerError> {
    let (parsed_name, _, _) = parse_backup_tag(backup_id)
        .ok_or_else(|| DockerError::Failed(format!("'{}' is not a valid backup tag", backup_id)))?;
    if parsed_name != name {
        return Err(DockerError::Failed(format!(
            "backup '{}' belongs to agent '{}', not '{}'",
            backup_id, parsed_name, name
        )));
    }
    let owned_agents = list_agent_names(docker).await;
    if !owned_agents.iter().any(|owned| owned == name) {
        return Err(DockerError::NotFound(format!(
            "agent '{}' not found",
            name
        )));
    }
    if remove_image(docker, backup_id).await.is_err() {
        return Err(DockerError::Failed(format!(
            "failed to delete backup '{}'",
            backup_id
        )));
    }
    Ok(())
}

/// Determine which auto-backups should be deleted based on the retention policy.
/// Returns the IDs of backups to delete.
pub fn compute_backups_to_delete(
    backups: &[BackupInfo],
    retention: &RetentionPolicy,
) -> Vec<String> {
    let mut to_delete = Vec::new();

    for (backup_type, keep) in [
        (BackupType::Daily, retention.daily),
        (BackupType::Weekly, retention.weekly),
        (BackupType::Monthly, retention.monthly),
    ] {
        let mut typed: Vec<&BackupInfo> = backups
            .iter()
            .filter(|b| b.backup_type == backup_type)
            .collect();
        typed.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        for excess in typed.into_iter().skip(keep) {
            to_delete.push(excess.id.clone());
        }
    }

    to_delete
}

/// Run retention cleanup for an agent's auto-backups.
/// Pass existing backups list to avoid a redundant `docker images` call.
pub async fn cleanup_backups(
    docker: &Docker,
    backups: &[BackupInfo],
    retention: &RetentionPolicy,
) {
    let to_delete = compute_backups_to_delete(backups, retention);
    if to_delete.is_empty() {
        return;
    }
    tracing::info!(count = to_delete.len(), "cleaning up old backups");
    for id in &to_delete {
        if remove_image(docker, id).await.is_ok() {
            tracing::debug!(backup_id = %id, "deleted expired backup");
        } else {
            tracing::warn!(backup_id = %id, "failed to delete expired backup");
        }
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

    // ── Backup tag tests ──────────────────────────────────────────

    #[test]
    fn backup_tag_generation() {
        let tag = backup_tag("myagent", &BackupType::Manual, "20260404-120000");
        assert_eq!(tag, "vesta-backup:myagent_manual_20260404-120000");
    }

    #[test]
    fn backup_tag_generation_pre_restore() {
        let tag = backup_tag("myagent", &BackupType::PreRestore, "20260404-120000");
        assert_eq!(tag, "vesta-backup:myagent_pre-restore_20260404-120000");
    }

    #[test]
    fn parse_backup_tag_new_format() {
        let (name, bt, ts) =
            parse_backup_tag("vesta-backup:myagent_manual_20260404-120000").unwrap();
        assert_eq!(name, "myagent");
        assert_eq!(bt, BackupType::Manual);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_new_format_pre_restore() {
        let (name, bt, ts) =
            parse_backup_tag("vesta-backup:myagent_pre-restore_20260404-120000").unwrap();
        assert_eq!(name, "myagent");
        assert_eq!(bt, BackupType::PreRestore);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_new_format_hyphenated_name() {
        let (name, bt, ts) =
            parse_backup_tag("vesta-backup:my-cool-agent_daily_20260404-120000").unwrap();
        assert_eq!(name, "my-cool-agent");
        assert_eq!(bt, BackupType::Daily);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_legacy_manual() {
        let (name, bt, ts) =
            parse_backup_tag("vesta-backup:myagent-manual-20260404-120000").unwrap();
        assert_eq!(name, "myagent");
        assert_eq!(bt, BackupType::Manual);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_legacy_hyphenated_name() {
        let (name, bt, ts) =
            parse_backup_tag("vesta-backup:my-cool-agent-daily-20260404-120000").unwrap();
        assert_eq!(name, "my-cool-agent");
        assert_eq!(bt, BackupType::Daily);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_roundtrip() {
        let original_tag = backup_tag("test-agent", &BackupType::Weekly, "20260101-235959");
        let (name, bt, ts) = parse_backup_tag(&original_tag).unwrap();
        assert_eq!(name, "test-agent");
        assert_eq!(bt, BackupType::Weekly);
        assert_eq!(ts, "20260101-235959");
    }

    #[test]
    fn parse_backup_tag_invalid() {
        assert!(parse_backup_tag("not-a-backup:tag").is_none());
        assert!(parse_backup_tag("vesta-backup:").is_none());
        assert!(parse_backup_tag("vesta-backup:short").is_none());
    }

    #[test]
    fn parse_backup_tag_all_types() {
        for type_str in ["manual", "daily", "weekly", "monthly", "pre-restore"] {
            let bt: BackupType = type_str.parse().unwrap();
            let tag = backup_tag("agent", &bt, "20260404-120000");
            let (name, parsed_bt, _) = parse_backup_tag(&tag).unwrap();
            assert_eq!(name, "agent");
            assert_eq!(parsed_bt, bt);
        }
    }

    // ── Retention policy tests ────────────────────────────────────

    const DEFAULT_RETENTION: RetentionPolicy = RetentionPolicy {
        daily: DEFAULT_RETENTION_DAILY,
        weekly: DEFAULT_RETENTION_WEEKLY,
        monthly: DEFAULT_RETENTION_MONTHLY,
    };

    fn make_backup(agent: &str, bt: BackupType, ts: &str) -> BackupInfo {
        BackupInfo {
            id: backup_tag(agent, &bt, ts),
            agent_name: agent.to_string(),
            backup_type: bt,
            created_at: ts.to_string(),
            size: 1000,
        }
    }

    #[test]
    fn retention_empty_list() {
        let to_delete = compute_backups_to_delete(&[], &DEFAULT_RETENTION);
        assert!(to_delete.is_empty());
    }

    #[test]
    fn retention_under_limit() {
        let backups = vec![
            make_backup("a", BackupType::Daily, "20260401-120000"),
            make_backup("a", BackupType::Daily, "20260402-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert!(to_delete.is_empty());
    }

    #[test]
    fn retention_daily_over_limit() {
        let backups = vec![
            make_backup("a", BackupType::Daily, "20260401-120000"),
            make_backup("a", BackupType::Daily, "20260402-120000"),
            make_backup("a", BackupType::Daily, "20260403-120000"),
            make_backup("a", BackupType::Daily, "20260404-120000"),
            make_backup("a", BackupType::Daily, "20260405-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert_eq!(to_delete.len(), 2);
        // Oldest two should be deleted
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Daily, "20260401-120000")));
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Daily, "20260402-120000")));
    }

    #[test]
    fn retention_weekly_over_limit() {
        let backups = vec![
            make_backup("a", BackupType::Weekly, "20260301-120000"),
            make_backup("a", BackupType::Weekly, "20260308-120000"),
            make_backup("a", BackupType::Weekly, "20260315-120000"),
            make_backup("a", BackupType::Weekly, "20260322-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert_eq!(to_delete.len(), 2);
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Weekly, "20260301-120000")));
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Weekly, "20260308-120000")));
    }

    #[test]
    fn retention_monthly_over_limit() {
        let backups = vec![
            make_backup("a", BackupType::Monthly, "20260101-120000"),
            make_backup("a", BackupType::Monthly, "20260201-120000"),
            make_backup("a", BackupType::Monthly, "20260301-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert_eq!(to_delete.len(), 2);
    }

    #[test]
    fn retention_mixed_types() {
        let backups = vec![
            make_backup("a", BackupType::Daily, "20260401-120000"),
            make_backup("a", BackupType::Daily, "20260402-120000"),
            make_backup("a", BackupType::Daily, "20260403-120000"),
            make_backup("a", BackupType::Weekly, "20260322-120000"),
            make_backup("a", BackupType::Weekly, "20260329-120000"),
            make_backup("a", BackupType::Monthly, "20260301-120000"),
            make_backup("a", BackupType::Manual, "20260404-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        // 3 daily (keep all), 2 weekly (keep all), 1 monthly (keep all), manual not touched
        assert!(to_delete.is_empty());
    }

    // ── Owner filter tests ────────────────────────────────────────

    #[test]
    fn filter_keeps_only_owned_agents() {
        let backups = vec![
            make_backup("mine", BackupType::Daily, "20260401-120000"),
            make_backup("theirs", BackupType::Daily, "20260401-120000"),
            make_backup("mine", BackupType::Weekly, "20260329-120000"),
            make_backup("another-user-agent", BackupType::Manual, "20260320-120000"),
        ];
        let owned = vec!["mine".to_string()];
        let filtered = filter_backups_by_owned_agents(backups, &owned);
        assert_eq!(filtered.len(), 2);
        assert!(filtered.iter().all(|b| b.agent_name == "mine"));
    }

    #[test]
    fn filter_empty_owned_returns_nothing() {
        let backups = vec![
            make_backup("alice", BackupType::Daily, "20260401-120000"),
            make_backup("bob", BackupType::Weekly, "20260329-120000"),
        ];
        let filtered = filter_backups_by_owned_agents(backups, &[]);
        assert!(filtered.is_empty());
    }

    #[test]
    fn filter_empty_backups_returns_empty() {
        let owned = vec!["alice".to_string(), "bob".to_string()];
        let filtered = filter_backups_by_owned_agents(Vec::new(), &owned);
        assert!(filtered.is_empty());
    }

    #[test]
    fn filter_multi_owned_keeps_each_match() {
        let backups = vec![
            make_backup("alice", BackupType::Daily, "20260401-120000"),
            make_backup("bob", BackupType::Daily, "20260401-120000"),
            make_backup("carol", BackupType::Daily, "20260401-120000"),
        ];
        let owned = vec!["alice".to_string(), "carol".to_string()];
        let filtered = filter_backups_by_owned_agents(backups, &owned);
        assert_eq!(filtered.len(), 2);
        let names: Vec<&str> = filtered.iter().map(|b| b.agent_name.as_str()).collect();
        assert!(names.contains(&"alice"));
        assert!(names.contains(&"carol"));
        assert!(!names.contains(&"bob"));
    }

    #[test]
    fn filter_exact_name_match_not_prefix() {
        // Ensures we match exact agent names, not prefixes. "my-agent" must not
        // match a backup whose agent_name is "my-agent-evil".
        let backups = vec![
            make_backup("my-agent", BackupType::Daily, "20260401-120000"),
            make_backup("my-agent-evil", BackupType::Daily, "20260401-120000"),
        ];
        let owned = vec!["my-agent".to_string()];
        let filtered = filter_backups_by_owned_agents(backups, &owned);
        assert_eq!(filtered.len(), 1);
        assert_eq!(filtered[0].agent_name, "my-agent");
    }

    #[test]
    fn retention_ignores_manual_and_pre_restore() {
        let backups = vec![
            make_backup("a", BackupType::Manual, "20260401-120000"),
            make_backup("a", BackupType::Manual, "20260402-120000"),
            make_backup("a", BackupType::Manual, "20260403-120000"),
            make_backup("a", BackupType::Manual, "20260404-120000"),
            make_backup("a", BackupType::PreRestore, "20260401-120000"),
            make_backup("a", BackupType::PreRestore, "20260402-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups, &DEFAULT_RETENTION);
        assert!(to_delete.is_empty());
    }
}
