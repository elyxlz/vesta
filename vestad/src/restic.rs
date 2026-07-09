//! restic-backed backup storage: one deduplicated, compressed, encrypted restic
//! repository per agent, snapshots tagged `agent:<name>` + `type:<backup_type>`.

use std::path::PathBuf;

use crate::docker::{container_name, DockerError};
use crate::types::{BackupInfo, BackupType};

const REPO_DIR: &str = "restic-repo";
const PASSWORD_FILE: &str = "restic-password";
const RESTIC_BIN: &str = "restic";
const RESTIC_TIMEOUT_SECS: u64 = 7200; // 2 hours — multi-GB agents stream the whole fs

fn config_dir() -> PathBuf {
    crate::paths::config_dir_or_relative()
}

/// Per-agent repos so concurrent backups of different agents don't contend on a
/// shared restic lock; same-agent ops are serialized by vestad's agent locks.
fn repo_path(name: &str) -> PathBuf {
    config_dir().join(REPO_DIR).join(name)
}

/// A local restic repo always has a `config` file; used to tell a first, full
/// snapshot from an incremental one.
pub fn repo_initialized(name: &str) -> bool {
    repo_path(name).join("config").exists()
}

/// Move an agent's repo on rename — repos are keyed by name, so otherwise the
/// renamed agent starts empty and the old backups are orphaned.
pub fn rename_repo(old_name: &str, new_name: &str) -> Result<(), DockerError> {
    let old = repo_path(old_name);
    if !old.exists() {
        return Ok(());
    }
    let new = repo_path(new_name);
    if let Some(parent) = new.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| DockerError::Failed(format!("failed to create repo dir: {e}")))?;
    }
    std::fs::rename(&old, &new)
        .map_err(|e| DockerError::Failed(format!("failed to move backup repo: {e}")))?;
    tracing::info!(old = %old_name, new = %new_name, "moved restic backup repository");
    Ok(())
}

/// Delete an agent's repo on destroy to reclaim disk. Best-effort.
pub fn remove_repo(name: &str) {
    let repo = repo_path(name);
    if repo.exists() {
        match std::fs::remove_dir_all(&repo) {
            Ok(()) => tracing::info!(agent = %name, "removed restic backup repository"),
            Err(e) => tracing::warn!(agent = %name, error = %e, "failed to remove backup repository"),
        }
    }
}

fn password_path() -> PathBuf {
    config_dir().join(PASSWORD_FILE)
}

/// PATH restic if present, else the copy embedded at build time.
pub fn ensure_restic() -> Result<PathBuf, DockerError> {
    if let Some(path) = crate::vendored_bin::which(RESTIC_BIN) {
        return Ok(path);
    }

    if let Some((bytes, fingerprint)) = crate::vendored_bin::vendored_restic() {
        return crate::vendored_bin::extract_embedded(&config_dir(), RESTIC_BIN, bytes, fingerprint)
            .map_err(|e| DockerError::Failed(e.to_string()));
    }

    Err(DockerError::Failed(
        "restic not found: not on PATH and not embedded in this build (VESTAD_SKIP_RESTIC=1?). Install restic.".into(),
    ))
}

/// Generate the repo encryption passphrase once (32 random bytes, hex) at 0600.
fn ensure_password() -> Result<PathBuf, DockerError> {
    let path = password_path();
    if path.exists() {
        return Ok(path);
    }
    std::fs::create_dir_all(config_dir())
        .map_err(|e| DockerError::Failed(format!("failed to create config dir: {e}")))?;

    // Read EXACTLY 32 bytes: /dev/urandom never returns EOF, so std::fs::read
    // (read_to_end) would loop forever growing a buffer until OOM.
    use std::io::Read;
    let mut bytes = [0u8; 32];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|e| DockerError::Failed(format!("failed to read /dev/urandom: {e}")))?;
    let hex = hex::encode(bytes);

    std::fs::write(&path, &hex)
        .map_err(|e| DockerError::Failed(format!("failed to write restic password: {e}")))?;
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
        .map_err(|e| DockerError::Failed(format!("failed to chmod restic password: {e}")))?;
    Ok(path)
}

/// Build a restic Command preset with this agent's repository and password env.
fn restic_command(name: &str) -> Result<std::process::Command, DockerError> {
    let bin = ensure_restic()?;
    let password = ensure_password()?;
    let mut cmd = std::process::Command::new(bin);
    cmd.env("RESTIC_REPOSITORY", repo_path(name))
        .env("RESTIC_PASSWORD_FILE", password);
    Ok(cmd)
}

/// Run a restic subcommand to completion, returning its captured stdout. A nonzero
/// exit maps to `Failed`, with the subcommand `label` naming it in both the spawn-
/// and exit-failure messages.
fn run_restic_capture(name: &str, label: &str, args: &[&str]) -> Result<Vec<u8>, DockerError> {
    let output = restic_command(name)?
        .args(args)
        .output()
        .map_err(|e| DockerError::Failed(format!("failed to run restic {label}: {e}")))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(DockerError::Failed(format!("restic {label} failed: {stderr}")));
    }
    Ok(output.stdout)
}

/// Pipe `producer`'s stdout into `consumer`'s stdin, run both to completion, and
/// return the consumer's captured stdout. A nonzero exit on either side maps to
/// `Failed`, named by its label.
fn pipe_through(
    mut producer: std::process::Command,
    producer_label: &str,
    mut consumer: std::process::Command,
    consumer_label: &str,
) -> Result<Vec<u8>, DockerError> {
    let mut producer_child = producer
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| DockerError::Failed(format!("failed to start {producer_label}: {e}")))?;
    let producer_stdout = producer_child.stdout.take()
        .ok_or_else(|| DockerError::Failed(format!("{producer_label} stdout not available")))?;

    let consumer_output = consumer
        .stdin(producer_stdout)
        .output()
        .map_err(|e| DockerError::Failed(format!("failed to run {consumer_label}: {e}")))?;

    let producer_output = producer_child.wait_with_output()
        .map_err(|e| DockerError::Failed(format!("{producer_label} wait failed: {e}")))?;
    if !producer_output.status.success() {
        let stderr = String::from_utf8_lossy(&producer_output.stderr);
        return Err(DockerError::Failed(format!("{producer_label} failed: {stderr}")));
    }
    if !consumer_output.status.success() {
        let stderr = String::from_utf8_lossy(&consumer_output.stderr);
        return Err(DockerError::Failed(format!("{consumer_label} failed: {stderr}")));
    }
    Ok(consumer_output.stdout)
}

/// Initialize the agent's repository if it does not already exist. Idempotent.
fn ensure_repo(name: &str) -> Result<(), DockerError> {
    // `cat config` succeeds only on an initialized repo.
    let exists = restic_command(name)?
        .args(["cat", "config"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if exists {
        return Ok(());
    }

    std::fs::create_dir_all(repo_path(name))
        .map_err(|e| DockerError::Failed(format!("failed to create repo dir: {e}")))?;

    run_restic_capture(name, "init", &["init"])?;
    tracing::info!(repo = %repo_path(name).display(), "initialized restic backup repository");
    Ok(())
}

fn agent_tar_name(name: &str) -> String {
    format!("{name}.tar")
}

/// Convert a restic RFC3339 timestamp to the `YYYYMMDD-HHMMSS` (UTC) format the
/// rest of the backup system uses for `created_at`.
fn format_restic_time(ts: &str) -> Option<String> {
    let dt = time::OffsetDateTime::parse(ts.trim(), &time::format_description::well_known::Rfc3339).ok()?;
    let utc = dt.to_offset(time::UtcOffset::UTC);
    let fmt = time::macros::format_description!("[year][month][day]-[hour][minute][second]");
    utc.format(&fmt).ok()
}

#[derive(serde::Deserialize)]
struct ResticSummaryMsg {
    message_type: Option<String>,
    snapshot_id: Option<String>,
    #[serde(default)]
    total_bytes_processed: u64,
}

/// Stream `docker export <cname>` into `restic backup --stdin`. Caller owns stop/start.
pub async fn snapshot(name: &str, backup_type: &BackupType) -> Result<BackupInfo, DockerError> {
    ensure_repo(name)?;
    let cname = container_name(name);
    let tar_name = agent_tar_name(name);
    let agent_tag = format!("agent:{name}");
    let type_tag = format!("type:{backup_type}");
    let backup_type = backup_type.clone();
    let name = name.to_string();
    let repo_name = name.clone();

    let summary = tokio::time::timeout(
        std::time::Duration::from_secs(RESTIC_TIMEOUT_SECS),
        tokio::task::spawn_blocking(move || -> Result<ResticSummaryMsg, DockerError> {
            let mut export = std::process::Command::new("docker");
            export.args(["export", &cname]);
            let mut backup = restic_command(&repo_name)?;
            backup.args([
                "backup", "--stdin",
                "--stdin-filename", &tar_name,
                "--tag", &agent_tag,
                "--tag", &type_tag,
                "--json",
            ]);
            let backup_stdout = pipe_through(export, "docker export", backup, "restic backup")?;

            // The final JSON line is the summary, carrying the new snapshot_id.
            let stdout = String::from_utf8_lossy(&backup_stdout);
            let summary = stdout
                .lines()
                .filter_map(|line| serde_json::from_str::<ResticSummaryMsg>(line).ok())
                .find(|msg| msg.message_type.as_deref() == Some("summary"))
                .ok_or_else(|| DockerError::Failed("restic backup produced no summary".into()))?;
            Ok(summary)
        }),
    )
    .await
    .map_err(|_| DockerError::Failed(format!("backup timed out after {RESTIC_TIMEOUT_SECS}s")))?
    .map_err(|e| DockerError::Failed(format!("backup task failed: {e}")))??;

    let full_id = summary.snapshot_id
        .ok_or_else(|| DockerError::Failed("restic summary missing snapshot_id".into()))?;
    let id = short_id(&full_id);

    Ok(BackupInfo {
        id,
        agent_name: name,
        backup_type,
        created_at: crate::time_utils::now_timestamp(),
        size: summary.total_bytes_processed,
    })
}

fn short_id(full: &str) -> String {
    full.chars().take(8).collect()
}

/// A file-node line from `restic ls --json` (struct_type == "node").
#[derive(serde::Deserialize)]
struct ResticLsNode {
    #[serde(default)]
    struct_type: String,
    #[serde(default)]
    path: String,
    #[serde(default)]
    name: String,
}

/// Return the absolute path of the `.tar` file stored inside the snapshot.
/// Runs `restic ls <id> --json` and picks the first file whose name ends with
/// `.tar`. This is rename-proof: it reads what was actually baked in at backup
/// time rather than recomputing from the agent's current name.
fn snapshot_tar_path_for_id(repo_name: &str, backup_id: &str) -> Result<String, DockerError> {
    let stdout = run_restic_capture(repo_name, "ls", &["ls", backup_id, "--json"])?;
    let stdout = String::from_utf8_lossy(&stdout);
    for line in stdout.lines() {
        let Ok(node) = serde_json::from_str::<ResticLsNode>(line) else {
            continue;
        };
        if node.struct_type == "node" && node.name.ends_with(".tar") {
            return Ok(node.path);
        }
    }
    Err(DockerError::Failed(format!(
        "snapshot {backup_id} contains no .tar file; cannot restore"
    )))
}

#[derive(serde::Deserialize)]
struct ResticSnapshot {
    short_id: String,
    time: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    summary: Option<ResticSnapshotSummary>,
}

#[derive(serde::Deserialize)]
struct ResticSnapshotSummary {
    #[serde(default)]
    total_bytes_processed: u64,
}

fn tag_value<'a>(tags: &'a [String], prefix: &str) -> Option<&'a str> {
    tags.iter().find_map(|t| t.strip_prefix(prefix))
}

fn snapshot_to_info(snap: ResticSnapshot) -> Option<BackupInfo> {
    let agent_name = tag_value(&snap.tags, "agent:")?.to_string();
    let backup_type = tag_value(&snap.tags, "type:")?.parse::<BackupType>().ok()?;
    let created_at = format_restic_time(&snap.time)?;
    Some(BackupInfo {
        id: snap.short_id,
        agent_name,
        backup_type,
        created_at,
        size: snap.summary.map(|s| s.total_bytes_processed).unwrap_or(0),
    })
}

/// List an agent's snapshots, newest first.
pub async fn list(name: &str) -> Result<Vec<BackupInfo>, DockerError> {
    ensure_repo(name)?;
    let name = name.to_string();

    let snapshots = tokio::task::spawn_blocking(move || -> Result<Vec<ResticSnapshot>, DockerError> {
        let stdout = run_restic_capture(&name, "snapshots", &["snapshots", "--json"])?;
        serde_json::from_slice::<Vec<ResticSnapshot>>(&stdout)
            .map_err(|e| DockerError::Failed(format!("failed to parse restic snapshots: {e}")))
    })
    .await
    .map_err(|e| DockerError::Failed(format!("list task failed: {e}")))??;

    let mut backups: Vec<BackupInfo> = snapshots.into_iter().filter_map(snapshot_to_info).collect();
    backups.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    Ok(backups)
}

/// Stream `restic dump <id>` into `docker import`, returning the image ref. The
/// stable per-agent tag (prior one removed first) keeps restores from piling up
/// image layers.
pub async fn restore_to_image(name: &str, backup_id: &str) -> Result<String, DockerError> {
    ensure_repo(name)?;
    // Read the tar path actually stored in the snapshot rather than recomputing
    // from the current agent name: after a rename the baked-in path still uses the
    // old name, so recomputing would give the wrong path and make every pre-rename
    // snapshot permanently unrestorable.
    let tar_path = snapshot_tar_path_for_id(name, backup_id)?;
    let image_ref = format!("vesta-restore:{name}");
    let backup_id = backup_id.to_string();
    let image_for_task = image_ref.clone();
    let repo_name = name.to_string();

    tokio::time::timeout(
        std::time::Duration::from_secs(RESTIC_TIMEOUT_SECS),
        tokio::task::spawn_blocking(move || -> Result<(), DockerError> {
            crate::docker::retry_import_pipeline("restic restore", || {
                // Best-effort removal of a previous restore image for this agent.
                std::process::Command::new("docker")
                    .args(["rmi", "-f", &image_for_task])
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .ok();

                let mut dump = restic_command(&repo_name)?;
                dump.args(["dump", &backup_id, &tar_path]);
                let mut import = std::process::Command::new("docker");
                import.args(["import", "-", &image_for_task]);
                pipe_through(dump, "restic dump", import, "docker import")?;
                Ok(())
            })
        }),
    )
    .await
    .map_err(|_| DockerError::Failed(format!("restore timed out after {RESTIC_TIMEOUT_SECS}s")))?
    .map_err(|e| DockerError::Failed(format!("restore task failed: {e}")))??;

    Ok(image_ref)
}

/// Forget the given snapshots from an agent's repository and prune to reclaim space.
pub async fn forget(name: &str, ids: &[String]) -> Result<(), DockerError> {
    if ids.is_empty() {
        return Ok(());
    }
    ensure_repo(name)?;
    let ids: Vec<String> = ids.to_vec();
    let name = name.to_string();

    tokio::time::timeout(
        std::time::Duration::from_secs(RESTIC_TIMEOUT_SECS),
        tokio::task::spawn_blocking(move || -> Result<(), DockerError> {
            let mut args = vec!["forget", "--prune"];
            args.extend(ids.iter().map(String::as_str));
            run_restic_capture(&name, "forget", &args)?;
            Ok(())
        }),
    )
    .await
    .map_err(|_| DockerError::Failed(format!("forget timed out after {RESTIC_TIMEOUT_SECS}s")))?
    .map_err(|e| DockerError::Failed(format!("forget task failed: {e}")))?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_id_truncates() {
        assert_eq!(short_id("0123456789abcdef"), "01234567");
        assert_eq!(short_id("abc"), "abc");
    }

    #[test]
    fn tag_value_extracts() {
        let tags = vec!["agent:okami".to_string(), "type:manual".to_string()];
        assert_eq!(tag_value(&tags, "agent:"), Some("okami"));
        assert_eq!(tag_value(&tags, "type:"), Some("manual"));
        assert_eq!(tag_value(&tags, "missing:"), None);
    }

    #[test]
    fn format_restic_time_to_compact_utc() {
        assert_eq!(
            format_restic_time("2026-05-29T04:00:01.123456789Z").as_deref(),
            Some("20260529-040001")
        );
        // Offset is normalized to UTC.
        assert_eq!(
            format_restic_time("2026-05-29T06:00:01+02:00").as_deref(),
            Some("20260529-040001")
        );
    }

    // Guard: snapshot() and restore_to_image() must agree on the tar path even after
    // the agent is renamed.  The bug was that restore_to_image recomputed the path
    // from the current (post-rename) name while the snapshot stored the pre-rename
    // name.  The fix reads the path back from the snapshot via `restic ls` instead.
    //
    // This test exercises the parsing half of that fix: given fake `restic ls --json`
    // output that mimics a pre-rename snapshot (path = "/okami.tar"), the helper
    // must return exactly "/okami.tar" regardless of what name the agent has now.
    #[test]
    fn restore_tar_path_matches_backup_tar_path_after_rename() {
        // Simulate the JSON lines emitted by `restic ls <id> --json` for a snapshot
        // that was taken when the agent was called "okami".
        let ls_output = concat!(
            "{\"struct_type\":\"snapshot\",\"id\":\"abc12345\",\"short_id\":\"abc12345\"}\n",
            "{\"struct_type\":\"node\",\"name\":\"okami.tar\",\"type\":\"file\",\"path\":\"/okami.tar\"}\n",
        );

        // Parse the output the same way snapshot_tar_path_for_id does.
        let found_path = ls_output
            .lines()
            .filter_map(|line| serde_json::from_str::<ResticLsNode>(line).ok())
            .find(|node| node.struct_type == "node" && node.name.ends_with(".tar"))
            .map(|node| node.path)
            .expect("should find the .tar node");

        // The path must come from the snapshot, not from the current agent name.
        // If the agent was renamed to "kitsune", agent_tar_name("kitsune") = "kitsune.tar",
        // which differs from what is stored: any code recomputing from the current name
        // would produce "/kitsune.tar" and cause `restic dump` to fail.
        assert_eq!(found_path, "/okami.tar");
        assert_ne!(
            found_path,
            format!("/{}", agent_tar_name("kitsune")),
            "proves that recomputing from the post-rename name would have been wrong"
        );
    }

    #[test]
    fn snapshot_to_info_requires_tags() {
        let snap = ResticSnapshot {
            short_id: "abc12345".into(),
            time: "2026-05-29T04:00:01Z".into(),
            tags: vec!["agent:okami".into(), "type:daily".into()],
            summary: Some(ResticSnapshotSummary { total_bytes_processed: 4242 }),
        };
        let info = snapshot_to_info(snap).unwrap();
        assert_eq!(info.id, "abc12345");
        assert_eq!(info.agent_name, "okami");
        assert_eq!(info.backup_type, BackupType::Daily);
        assert_eq!(info.created_at, "20260529-040001");
        assert_eq!(info.size, 4242);

        let untagged = ResticSnapshot {
            short_id: "abc12345".into(),
            time: "2026-05-29T04:00:01Z".into(),
            tags: vec![],
            summary: None,
        };
        assert!(snapshot_to_info(untagged).is_none());
    }
}
