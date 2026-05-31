//! restic-backed backup storage: one deduplicated, compressed, encrypted restic
//! repository per agent, snapshots tagged `agent:<name>` + `type:<backup_type>`.

use std::path::{Path, PathBuf};

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
    if let Some(path) = which(RESTIC_BIN) {
        return Ok(path);
    }

    if let Some((bytes, fingerprint)) = crate::restic_embed::vendored_restic() {
        return extract_embedded_restic(&config_dir(), bytes, fingerprint);
    }

    Err(DockerError::Failed(
        "restic not found: not on PATH and not embedded in this build (VESTAD_SKIP_RESTIC=1?). Install restic.".into(),
    ))
}

const RESTIC_FINGERPRINT_MARKER: &str = ".restic-fingerprint";

/// Serializes extraction so concurrent first-use callers don't write the binary
/// while another thread is exec'ing it (ETXTBSY).
static EXTRACT_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Write the embedded binary to disk, re-extracting only if the fingerprint changed.
fn extract_embedded_restic(
    config_dir: &Path,
    bytes: &[u8],
    fingerprint: &str,
) -> Result<PathBuf, DockerError> {
    let local_bin = config_dir.join(RESTIC_BIN);
    let marker = config_dir.join(RESTIC_FINGERPRINT_MARKER);
    let _guard = EXTRACT_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    if local_bin.exists()
        && std::fs::read_to_string(&marker).ok().as_deref() == Some(fingerprint)
    {
        return Ok(local_bin);
    }

    std::fs::create_dir_all(config_dir)
        .map_err(|e| DockerError::Failed(format!("failed to create config dir: {e}")))?;
    // Write to a temp file and atomically rename, so we never truncate a binary
    // another thread is currently executing (which would fail with ETXTBSY).
    let tmp = config_dir.join(format!("{RESTIC_BIN}.tmp"));
    std::fs::write(&tmp, bytes)
        .map_err(|e| DockerError::Failed(format!("failed to write embedded restic: {e}")))?;
    set_executable(&tmp)?;
    std::fs::rename(&tmp, &local_bin)
        .map_err(|e| DockerError::Failed(format!("failed to install restic binary: {e}")))?;
    std::fs::write(&marker, fingerprint)
        .map_err(|e| DockerError::Failed(format!("failed to write restic fingerprint: {e}")))?;

    tracing::info!(path = %local_bin.display(), "restic extracted from embed");
    Ok(local_bin)
}

fn set_executable(path: &Path) -> Result<(), DockerError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
        .map_err(|e| DockerError::Failed(format!("chmod failed: {e}")))
}

fn which(name: &str) -> Option<PathBuf> {
    let output = std::process::Command::new("which").arg(name).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if path.is_empty() { None } else { Some(PathBuf::from(path)) }
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
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();

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

    let output = restic_command(name)?
        .args(["init"])
        .output()
        .map_err(|e| DockerError::Failed(format!("failed to run restic init: {e}")))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(DockerError::Failed(format!("restic init failed: {stderr}")));
    }
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
            let mut export_child = std::process::Command::new("docker")
                .args(["export", &cname])
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::piped())
                .spawn()
                .map_err(|e| DockerError::Failed(format!("failed to start docker export: {e}")))?;

            let export_stdout = export_child.stdout.take()
                .ok_or_else(|| DockerError::Failed("docker export stdout not available".into()))?;

            let backup_output = restic_command(&repo_name)?
                .args([
                    "backup", "--stdin",
                    "--stdin-filename", &tar_name,
                    "--tag", &agent_tag,
                    "--tag", &type_tag,
                    "--json",
                ])
                .stdin(export_stdout)
                .stderr(std::process::Stdio::piped())
                .output()
                .map_err(|e| DockerError::Failed(format!("failed to run restic backup: {e}")))?;

            let export_output = export_child.wait_with_output()
                .map_err(|e| DockerError::Failed(format!("docker export wait failed: {e}")))?;
            if !export_output.status.success() {
                let stderr = String::from_utf8_lossy(&export_output.stderr);
                return Err(DockerError::Failed(format!("docker export failed: {stderr}")));
            }
            if !backup_output.status.success() {
                let stderr = String::from_utf8_lossy(&backup_output.stderr);
                return Err(DockerError::Failed(format!("restic backup failed: {stderr}")));
            }

            // The final JSON line is the summary, carrying the new snapshot_id.
            let stdout = String::from_utf8_lossy(&backup_output.stdout);
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
        created_at: crate::backup::now_timestamp(),
        size: summary.total_bytes_processed,
    })
}

fn short_id(full: &str) -> String {
    full.chars().take(8).collect()
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
        let output = restic_command(&name)?
            .args(["snapshots", "--json"])
            .output()
            .map_err(|e| DockerError::Failed(format!("failed to run restic snapshots: {e}")))?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(DockerError::Failed(format!("restic snapshots failed: {stderr}")));
        }
        serde_json::from_slice::<Vec<ResticSnapshot>>(&output.stdout)
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
    let tar_path = format!("/{}", agent_tar_name(name));
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

                let mut dump_child = restic_command(&repo_name)?
                    .args(["dump", &backup_id, &tar_path])
                    .stdout(std::process::Stdio::piped())
                    .stderr(std::process::Stdio::piped())
                    .spawn()
                    .map_err(|e| DockerError::Failed(format!("failed to start restic dump: {e}")))?;

                let dump_stdout = dump_child.stdout.take()
                    .ok_or_else(|| DockerError::Failed("restic dump stdout not available".into()))?;

                let import_output = std::process::Command::new("docker")
                    .args(["import", "-", &image_for_task])
                    .stdin(dump_stdout)
                    .output()
                    .map_err(|e| DockerError::Failed(format!("failed to run docker import: {e}")))?;

                let dump_output = dump_child.wait_with_output()
                    .map_err(|e| DockerError::Failed(format!("restic dump wait failed: {e}")))?;
                if !dump_output.status.success() {
                    let stderr = String::from_utf8_lossy(&dump_output.stderr);
                    return Err(DockerError::Failed(format!("restic dump failed: {stderr}")));
                }
                if !import_output.status.success() {
                    let stderr = String::from_utf8_lossy(&import_output.stderr);
                    return Err(DockerError::Failed(format!("docker import failed: {stderr}")));
                }
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
            let mut args = vec!["forget".to_string(), "--prune".to_string()];
            args.extend(ids);
            let output = restic_command(&name)?
                .args(&args)
                .output()
                .map_err(|e| DockerError::Failed(format!("failed to run restic forget: {e}")))?;
            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                return Err(DockerError::Failed(format!("restic forget failed: {stderr}")));
            }
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
