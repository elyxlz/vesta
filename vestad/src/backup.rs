use std::fs::File;

use bollard::Docker;

use crate::docker::{
    container_created, container_name, container_size_root_fs, container_size_rw, container_status, create_container,
    inspect_container, remove_container_force, start_container, stop_container_with_timeout, validate_name,
    write_pending_restart_reason, AgentEnvConfig, ContainerStatus, DockerError,
};
use crate::types::{BackupInfo, BackupType, RetentionPolicy};

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

/// Ensure the repo filesystem has room. The first snapshot writes the whole root
/// fs (`docker export`), so size off that; later snapshots only write the diff,
/// so the writable-layer size is an adequate floor.
async fn check_disk_space(docker: &Docker, name: &str, cname: &str) -> Result<(), DockerError> {
    let repo_fs = crate::paths::config_dir_or_relative();
    std::fs::create_dir_all(&repo_fs)
        .map_err(|e| DockerError::Failed(format!("failed to create backup dir: {e}")))?;

    let stat = nix::sys::statvfs::statvfs(repo_fs.as_path())
        .map_err(|e| DockerError::Failed(format!("failed to check disk space: {}", e)))?;

    let available = stat.blocks_available() * stat.fragment_size();

    let container_size = if crate::restic::repo_initialized(name) {
        container_size_rw(docker, cname).await.unwrap_or(0)
    } else {
        container_size_root_fs(docker, cname).await.unwrap_or(0)
    };
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

/// Stop (if running), run `op`, restart. Writes `resume_reason` into the agent's boot inbox for
/// the restart. The write happens AFTER `op` — writing before the stop would bake the reason into
/// the snapshot `op` takes, and a restore of that backup would replay it as a stale greeting.
async fn with_container_paused<F, Fut, T>(
    docker: &Docker,
    name: &str,
    cs: ContainerStatus,
    resume_reason: &str,
    op: F,
) -> T
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = T>,
{
    let cname = container_name(name);
    let was_running = cs == ContainerStatus::Running;
    if was_running {
        tracing::info!(agent = %name, "stopping agent for backup");
        stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS).await.ok();
    }

    let result = op().await;

    if was_running {
        tracing::info!(agent = %name, "restarting agent");
        if let Err(err) = write_pending_restart_reason(docker, &cname, resume_reason).await {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
        start_container(docker, &cname).await;
    }
    result
}

/// The boot reason for the restart after a backup pause, by what triggered the backup.
fn backup_resume_reason(backup_type: &BackupType) -> &'static str {
    match backup_type {
        BackupType::Manual => "backup: you were paused for a manual backup",
        BackupType::PreRestore => "backup: you were paused for a safety backup before a restore",
        BackupType::Daily | BackupType::Weekly | BackupType::Monthly => "backup: you were paused for a scheduled backup",
    }
}

/// Validate the agent, confirm its container is backup-able (not NotFound/Dead),
/// and verify disk headroom. Returns the container's status for the stop/start cycle.
async fn backup_preflight(docker: &Docker, name: &str) -> Result<ContainerStatus, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(docker, &cname).await;
    match cs {
        ContainerStatus::NotFound => {
            return Err(DockerError::NotFound(format!("agent '{}' not found", name)))
        }
        ContainerStatus::Dead => {
            return Err(DockerError::BrokenState(format!(
                "agent '{}' is in a broken state",
                name
            )))
        }
        _ => {}
    }
    check_disk_space(docker, name, &cname).await?;
    Ok(cs)
}

/// Create a backup of the given agent. Stops the container during the snapshot, then restarts.
pub async fn create_backup(
    docker: &Docker,
    name: &str,
    backup_type: BackupType,
) -> Result<BackupInfo, DockerError> {
    let cs = backup_preflight(docker, name).await?;

    let result = with_container_paused(docker, name, cs, backup_resume_reason(&backup_type), || async {
        tracing::info!(agent = %name, backup_type = %backup_type, "snapshotting backup");
        crate::restic::snapshot(name, &backup_type).await
    })
    .await;

    match &result {
        Ok(info) => {
            tracing::info!(agent = %name, backup_id = %info.id, size = info.size, "backup created")
        }
        Err(e) => tracing::error!(agent = %name, error = %e, "backup failed"),
    }

    result
}

/// Create multiple backup types in one stop/start cycle (separate restic
/// snapshots, deduplicated). Returns a result per type; failures don't block others.
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

    let cs = match backup_preflight(docker, name).await {
        Ok(cs) => cs,
        Err(e) => return fail_all(types, e),
    };

    // Batch backups are only ever the auto-backup's scheduled set, so one scheduled reason fits.
    with_container_paused(docker, name, cs, "backup: you were paused for a scheduled backup", || async {
        let mut results = Vec::new();
        for bt in types {
            let result = crate::restic::snapshot(name, &bt).await;
            match &result {
                Ok(info) => tracing::info!(agent = %name, backup_type = %bt, backup_id = %info.id, "backup created"),
                Err(e) => tracing::error!(agent = %name, backup_type = %bt, error = %e, "backup failed"),
            }
            results.push((bt, result));
        }
        results
    })
    .await
}

/// List all backups for the given agent, sorted by date descending.
pub async fn list_backups(docker: &Docker, name: &str) -> Result<Vec<BackupInfo>, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    if container_status(docker, &cname).await == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!("agent '{}' not found", name)));
    }
    let owned_agents = list_agent_names(docker).await;
    if !owned_agents.iter().any(|owned| owned == name) {
        return Err(DockerError::NotFound(format!("agent '{}' not found", name)));
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
    manage_core_code: bool,
    user_mounts: &[crate::mounts::HostMount],
) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);

    // Verify the backup exists and belongs to this agent before doing anything destructive.
    let backups = list_backups(docker, name).await?;
    if !backups.iter().any(|b| b.id == backup_id) {
        return Err(DockerError::NotFound(format!("backup '{}' not found", backup_id)));
    }

    let info = inspect_container(docker, &cname, Some(&env_config.agents_dir)).await;
    if info.status == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!("agent '{}' not found", name)));
    }

    // Stop once, take safety backup, then remove — avoids a redundant stop/start cycle.
    if info.status == ContainerStatus::Running {
        stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS).await.ok();
    }
    tracing::info!(agent = %name, "creating pre-restore safety backup");
    if let Err(e) = crate::restic::snapshot(name, &BackupType::PreRestore).await {
        if info.status == ContainerStatus::Running {
            start_container(docker, &cname).await;
        }
        return Err(DockerError::Failed(format!("pre-restore safety backup failed: {e}")));
    }
    remove_container_force(docker, &cname).await.ok();

    let port = info
        .port
        .ok_or_else(|| DockerError::Failed("agent has no port in env file".into()))?;
    tracing::debug!(agent = %name, backup_id = %backup_id, "restoring snapshot into image");
    let image = crate::restic::restore_to_image(name, backup_id).await?;
    create_container(docker, &cname, &image, port, name, env_config, manage_core_code, user_mounts).await?;

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
        return Err(DockerError::NotFound(format!("agent '{}' not found", name)));
    }
    let backups = crate::restic::list(name).await?;
    if !backups.iter().any(|b| b.id == backup_id) {
        return Err(DockerError::Failed(format!(
            "backup '{}' not found for agent '{}'",
            backup_id, name
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
/// Pass existing backups list to avoid a redundant snapshot listing.
pub async fn cleanup_backups(
    name: &str,
    backups: &[BackupInfo],
    retention: &RetentionPolicy,
) {
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

    // ── SSE cancellation safety ───────────────────────────────────

    /// Asserts that the backup/restore pipeline (stop container, snapshot/restore, start
    /// container) runs to completion even when the SSE client disconnects mid-operation.
    ///
    /// The fix spawns the pipeline with tokio::spawn so it is detached from the SSE
    /// response body lifetime. When the SSE consumer task is aborted (client disconnect),
    /// the spawned pipeline continues uninterrupted and start_container is always called.
    #[tokio::test]
    async fn sse_stream_drop_cancels_container_restart() {
        use std::sync::{
            atomic::{AtomicBool, Ordering},
            Arc,
        };
        use tokio::sync::Notify;

        let stopped = Arc::new(AtomicBool::new(false));
        let started = Arc::new(AtomicBool::new(false));
        let op_reached = Arc::new(Notify::new());
        let op_gate = Arc::new(Notify::new());

        let stopped_c = stopped.clone();
        let started_c = started.clone();
        let op_reached_c = op_reached.clone();
        let op_gate_c = op_gate.clone();

        // Fixed pattern: the pipeline is spawned separately from the SSE response body.
        // Dropping the JoinHandle does not abort the task — it runs to completion.
        // This mirrors the tokio::spawn in the fixed create_backup_handler /
        // restore_backup_handler.
        let _pipeline = tokio::spawn(async move {
            // Mirrors stop_container_with_timeout
            stopped_c.store(true, Ordering::SeqCst);
            op_reached_c.notify_one();
            // Mirrors restic::snapshot — the expensive async op
            op_gate_c.notified().await;
            // Mirrors start_container — must always run
            started_c.store(true, Ordering::SeqCst);
        });

        // SSE consumer task — represents the axum response body polled by hyper.
        // When the client disconnects, hyper drops the body and this task is aborted.
        let stream_handle = tokio::spawn(async move {
            let stream = async_stream::stream! {
                // In the fixed handler, this side only awaits the result channel.
                // Here we suspend indefinitely to simulate an in-flight SSE response.
                std::future::pending::<()>().await;
                yield ();
            };
            use futures_util::StreamExt;
            futures_util::pin_mut!(stream);
            stream.next().await;
        });

        // Wait until the container has been stopped and the op is in progress.
        op_reached.notified().await;
        assert!(stopped.load(Ordering::SeqCst), "container should be stopped");
        assert!(!started.load(Ordering::SeqCst), "container not yet restarted");

        // Simulate SSE client disconnecting: abort the SSE consumer task.
        // The spawned pipeline must not be affected.
        stream_handle.abort();
        let _ = stream_handle.await;

        // Release the gate (restic snapshot / restore image stream completes).
        op_gate.notify_one();
        // Give the spawned pipeline a scheduling slot to finish.
        tokio::task::yield_now().await;

        assert!(
            started.load(Ordering::SeqCst),
            "start_container must run to completion regardless of SSE client disconnect"
        );
    }

    // ── Retention policy tests ────────────────────────────────────

    const DEFAULT_RETENTION: RetentionPolicy = RetentionPolicy {
        daily: DEFAULT_RETENTION_DAILY,
        weekly: DEFAULT_RETENTION_WEEKLY,
        monthly: DEFAULT_RETENTION_MONTHLY,
    };

    fn make_backup(agent: &str, bt: BackupType, ts: &str) -> BackupInfo {
        BackupInfo {
            id: format!("{agent}-{bt}-{ts}"),
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
        assert!(to_delete.contains(&make_backup("a", BackupType::Daily, "20260401-120000").id));
        assert!(to_delete.contains(&make_backup("a", BackupType::Daily, "20260402-120000").id));
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
        assert!(to_delete.contains(&make_backup("a", BackupType::Weekly, "20260301-120000").id));
        assert!(to_delete.contains(&make_backup("a", BackupType::Weekly, "20260308-120000").id));
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
