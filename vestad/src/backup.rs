use std::fs::File;

use crate::docker::{
    container_name, container_status, create_container, docker_cp_content, docker_ok,
    docker_output, get_agent_name, inspect_container, list_managed_containers, snapshot_container,
    validate_name, AgentEnvConfig, ContainerStatus, DockerError,
};
use crate::types::{BackupInfo, BackupType, RetentionPolicy};

const BACKUP_IMAGE_PREFIX: &str = "vesta-backup";
pub const DEFAULT_RETENTION_DAILY: usize = 3;
pub const DEFAULT_RETENTION_WEEKLY: usize = 2;
pub const DEFAULT_RETENTION_MONTHLY: usize = 1;
const MIN_DISK_SPACE_BYTES: u64 = 1_000_000_000; // 1 GB
const DISK_SPACE_MARGIN_BYTES: u64 = 500_000_000; // 500 MB margin above container size
pub const BACKUP_STOP_TIMEOUT_SECS: &str = "30";
pub const MIN_AGE_FOR_BACKUP_SECS: u64 = 6 * 3600;

/// Acquire an exclusive file lock for the given agent. The lock is held for the
/// lifetime of the returned Flock. Used to coordinate between the vestad API and
/// the `vestad backup export/import` CLI which bypasses the server.
pub fn agent_file_lock(name: &str) -> Result<nix::fcntl::Flock<File>, DockerError> {
    let home = std::env::var("HOME").unwrap_or_default();
    let lock_dir = std::path::PathBuf::from(home).join(".config/vesta/vestad/locks");
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
fn check_disk_space(cname: &str) -> Result<(), DockerError> {
    let root = docker_output(&["info", "--format", "{{.DockerRootDir}}"])
        .unwrap_or_else(|| "/var/lib/docker".to_string());

    let stat = nix::sys::statvfs::statvfs(root.as_str())
        .map_err(|e| DockerError::Failed(format!("failed to check disk space: {}", e)))?;

    let available = stat.blocks_available() * stat.fragment_size();

    let container_size = docker_output(&["inspect", "--format", "{{.SizeRw}}", cname])
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);
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
    parse_backup_tag_legacy(repo_tag)
}

fn parse_backup_tag_legacy(repo_tag: &str) -> Option<(String, BackupType, String)> {
    if repo_tag.len() < 17 {
        return None;
    }
    let timestamp = &repo_tag[repo_tag.len() - 15..];
    if timestamp.len() != 15 || timestamp.as_bytes()[8] != b'-' {
        return None;
    }
    let name_and_type = &repo_tag[..repo_tag.len() - 16];

    for (suffix, bt) in [
        ("-pre-restore", BackupType::PreRestore),
        ("-manual", BackupType::Manual),
        ("-daily", BackupType::Daily),
        ("-weekly", BackupType::Weekly),
        ("-monthly", BackupType::Monthly),
    ] {
        if let Some(name) = name_and_type.strip_suffix(suffix) {
            if !name.is_empty() {
                return Some((name.to_string(), bt, timestamp.to_string()));
            }
        }
    }
    None
}

pub fn now_timestamp() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    now_timestamp_from_epoch(now)
}

pub fn now_timestamp_from_epoch(epoch_secs: u64) -> String {
    let dt = time::OffsetDateTime::from_unix_timestamp(epoch_secs as i64)
        .expect("epoch seconds within valid range");
    let fmt = time::macros::format_description!("[year][month][day]-[hour][minute][second]");
    dt.format(&fmt).expect("timestamp format never fails")
}

/// Returns the container's age in seconds, or None if unknown.
pub fn container_age_secs(name: &str) -> Option<u64> {
    let cname = container_name(name);
    let created = docker_output(&["inspect", "--format", "{{.Created}}", &cname])?;
    let created_epoch = parse_rfc3339_epoch(created.trim())?;
    let now_epoch = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs();
    Some(now_epoch.saturating_sub(created_epoch))
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
fn commit_backup(
    cname: &str,
    name: &str,
    backup_type: &BackupType,
) -> Result<BackupInfo, DockerError> {
    let ts = now_timestamp();
    let tag = backup_tag(name, backup_type, &ts);
    let name_label = format!("LABEL vesta.agent_name={}", name);
    let type_label = format!("LABEL vesta.backup_type={}", backup_type);
    let date_label = format!("LABEL vesta.backup_date={}", ts);

    snapshot_container(cname, &tag, &[&name_label, &type_label, &date_label])?;

    let size = docker_output(&[
        "images",
        "--format",
        "{{.Size}}",
        "--filter",
        &format!("reference={}", tag),
    ])
    .map(|s| parse_docker_size(&s))
    .unwrap_or(0);

    Ok(BackupInfo {
        id: tag,
        agent_name: name.to_string(),
        backup_type: backup_type.clone(),
        created_at: ts,
        size,
    })
}

/// Create a backup of the given agent. Stops the container during commit, then restarts.
pub fn create_backup(name: &str, backup_type: BackupType) -> Result<BackupInfo, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(&cname);
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

    check_disk_space(&cname)?;

    let was_running = cs == ContainerStatus::Running;
    if was_running {
        tracing::info!(agent = %name, backup_type = %backup_type, "stopping agent for backup");
        if let Err(err) = docker_cp_content(
            &cname,
            "backup — paused for backup",
            "/root/vesta/data/restart_reason",
        ) {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
        docker_ok(&["stop", "--time", BACKUP_STOP_TIMEOUT_SECS, &cname]);
    }

    tracing::info!(agent = %name, "committing backup image");
    let result = commit_backup(&cname, name, &backup_type);

    if was_running {
        tracing::info!(agent = %name, "restarting agent");
        docker_ok(&["start", &cname]);
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
pub fn create_backups_batch(
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

    let cs = container_status(&cname);
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

    if let Err(e) = check_disk_space(&cname) {
        return fail_all(types, e);
    }

    let was_running = cs == ContainerStatus::Running;
    if was_running {
        if let Err(err) = docker_cp_content(
            &cname,
            "backup — paused for backup",
            "/root/vesta/data/restart_reason",
        ) {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
        docker_ok(&["stop", "--time", BACKUP_STOP_TIMEOUT_SECS, &cname]);
    }

    let mut results = Vec::new();
    let first_type = &types[0];
    let first_result = commit_backup(&cname, name, first_type);

    match first_result {
        Ok(first_info) => {
            let size = first_info.size;
            let ts = first_info.created_at.clone();
            let source_tag = first_info.id.clone();
            results.push((first_type.clone(), Ok(first_info)));

            for bt in &types[1..] {
                let new_tag = backup_tag(name, bt, &ts);
                if docker_ok(&["tag", &source_tag, &new_tag]) {
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
                } else {
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
        docker_ok(&["start", &cname]);
    }

    results
}

/// Query Docker for backup images matching a filter and optional agent name, sorted by date descending.
fn query_backup_images(filter: &str, agent_name: Option<&str>) -> Vec<BackupInfo> {
    let output = docker_output(&[
        "images",
        "--format",
        "{{.Repository}}:{{.Tag}}\t{{.Size}}",
        "--filter",
        filter,
    ])
    .unwrap_or_default();

    let mut backups: Vec<BackupInfo> = output
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|line| {
            let mut parts = line.splitn(2, '\t');
            let tag = parts.next()?.trim();
            let size_str = parts.next().unwrap_or("0").trim();
            let (parsed_name, backup_type, timestamp) = parse_backup_tag(tag)?;
            if let Some(name) = agent_name {
                if parsed_name != name {
                    return None;
                }
            }
            Some(BackupInfo {
                id: tag.to_string(),
                agent_name: parsed_name,
                backup_type,
                created_at: timestamp,
                size: parse_docker_size(size_str),
            })
        })
        .collect();

    backups.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    backups
}

/// List all backups for the given agent, sorted by date descending.
pub fn list_backups(name: &str) -> Result<Vec<BackupInfo>, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    if container_status(&cname) == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!(
            "agent '{}' not found",
            name
        )));
    }
    let filter = format!("reference={}:{}*", BACKUP_IMAGE_PREFIX, name);
    Ok(query_backup_images(&filter, Some(name)))
}

/// Parse Docker's human-readable size strings like "1.5GB", "300MB", "15kB".
fn parse_docker_size(s: &str) -> u64 {
    let s = s.trim();
    let (num_str, multiplier) = if let Some(n) = s.strip_suffix("GB") {
        (n, 1_000_000_000u64)
    } else if let Some(n) = s.strip_suffix("MB") {
        (n, 1_000_000u64)
    } else if let Some(n) = s.strip_suffix("kB") {
        (n, 1_000u64)
    } else if let Some(n) = s.strip_suffix('B') {
        (n, 1u64)
    } else {
        (s, 1u64)
    };
    num_str
        .trim()
        .parse::<f64>()
        .map(|n| (n * multiplier as f64) as u64)
        .unwrap_or(0)
}

/// List all backup images regardless of whether the agent container exists.
pub fn list_all_backups() -> Vec<BackupInfo> {
    let filter = format!("reference={}:*", BACKUP_IMAGE_PREFIX);
    query_backup_images(&filter, None)
}

/// Restore an agent from a backup image.
/// Creates a pre-restore safety backup first, then replaces the container.
pub fn restore_backup(
    name: &str,
    backup_id: &str,
    env_config: &AgentEnvConfig,
) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);

    if docker_output(&["inspect", "--format", "{{.Id}}", backup_id]).is_none() {
        return Err(DockerError::NotFound(format!(
            "backup '{}' not found",
            backup_id
        )));
    }

    let info = inspect_container(&cname, Some(&env_config.agents_dir));
    if info.status == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!(
            "agent '{}' not found",
            name
        )));
    }

    // Stop once, commit safety backup, then remove — avoids a redundant stop/start cycle
    if info.status == ContainerStatus::Running {
        docker_ok(&["stop", "--time", BACKUP_STOP_TIMEOUT_SECS, &cname]);
    }
    tracing::info!(agent = %name, "creating pre-restore safety backup");
    commit_backup(&cname, name, &BackupType::PreRestore).map_err(|e| {
        // Restart the container before returning the error
        if info.status == ContainerStatus::Running {
            docker_ok(&["start", &cname]);
        }
        DockerError::Failed(format!("pre-restore safety backup failed: {e}"))
    })?;
    docker_ok(&["rm", "-f", &cname]);

    let port = info
        .port
        .ok_or_else(|| DockerError::Failed("agent has no port in env file".into()))?;
    tracing::debug!(agent = %name, backup_id = %backup_id, "creating container from backup image");
    create_container(&cname, backup_id, port, name, env_config)?;

    if !docker_ok(&["start", &cname]) {
        return Err(DockerError::Failed(
            "failed to start restored agent".into(),
        ));
    }

    Ok(())
}

/// Delete a backup image. Verifies the backup belongs to the named agent.
pub fn delete_backup(name: &str, backup_id: &str) -> Result<(), DockerError> {
    let (parsed_name, _, _) = parse_backup_tag(backup_id)
        .ok_or_else(|| DockerError::Failed(format!("'{}' is not a valid backup tag", backup_id)))?;
    if parsed_name != name {
        return Err(DockerError::Failed(format!(
            "backup '{}' belongs to agent '{}', not '{}'",
            backup_id, parsed_name, name
        )));
    }
    if !docker_ok(&["rmi", backup_id]) {
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
pub fn cleanup_backups(backups: &[BackupInfo], retention: &RetentionPolicy) {
    let to_delete = compute_backups_to_delete(backups, retention);
    if to_delete.is_empty() {
        return;
    }
    tracing::info!(count = to_delete.len(), "cleaning up old backups");
    for id in &to_delete {
        if docker_ok(&["rmi", id]) {
            tracing::debug!(backup_id = %id, "deleted expired backup");
        } else {
            tracing::warn!(backup_id = %id, "failed to delete expired backup");
        }
    }
}

/// List all agent names that have containers.
pub fn list_agent_names() -> Vec<String> {
    list_managed_containers()
        .iter()
        .map(|cname| get_agent_name(cname))
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

    // ── Docker size parsing ───────────────────────────────────────

    #[test]
    fn parse_docker_size_values() {
        assert_eq!(parse_docker_size("1.5GB"), 1_500_000_000);
        assert_eq!(parse_docker_size("300MB"), 300_000_000);
        assert_eq!(parse_docker_size("15kB"), 15_000);
        assert_eq!(parse_docker_size("1024B"), 1024);
        assert_eq!(parse_docker_size("0B"), 0);
    }
}
