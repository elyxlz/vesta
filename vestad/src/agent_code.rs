use std::path::{Path, PathBuf};
use std::{fmt, fs, process};

const GITHUB_ARCHIVE_URL: &str = "https://github.com/elyxlz/vesta/archive/refs/tags";
const TEMP_PREFIX: &str = "vesta-agent-code";

#[derive(Debug)]
pub enum AgentCodeError {
    Download(String),
    Extract(String),
    Io(String),
}

impl fmt::Display for AgentCodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Download(msg) => write!(f, "download failed: {msg}"),
            Self::Extract(msg) => write!(f, "extraction failed: {msg}"),
            Self::Io(msg) => write!(f, "io error: {msg}"),
        }
    }
}

pub fn agent_code_dir(config: &Path) -> PathBuf {
    config.join("agent-code")
}

fn is_populated(config: &Path) -> bool {
    let dir = agent_code_dir(config);
    dir.join("core/main.py").exists()
        && dir.join("pyproject.toml").is_file()
        && dir.join("uv.lock").is_file()
}

/// Read the version from the on-disk agent pyproject.toml.
fn on_disk_version(config: &Path) -> Option<String> {
    let pyproject = fs::read_to_string(agent_code_dir(config).join("pyproject.toml")).ok()?;
    for line in pyproject.lines() {
        // Match exactly "version = ..." at the top level, not dependency version fields
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("version") {
            let rest = rest.trim_start();
            if let Some(rest) = rest.strip_prefix('=') {
                return Some(rest.trim().trim_matches('"').to_string());
            }
        }
    }
    None
}

/// Ensure agent code exists on the host and matches the vestad version.
/// - Dev (debug builds): copies from the local repo if source is newer
/// - Prod (release builds): downloads from GitHub if missing or version mismatch
pub fn ensure_agent_code(config: &Path) -> Result<PathBuf, AgentCodeError> {
    let dir = agent_code_dir(config);
    let vestad_version = env!("CARGO_PKG_VERSION");

    if cfg!(debug_assertions) {
        copy_from_local_repo(config)?;
    } else if is_populated(config) && on_disk_version(config).as_deref() == Some(vestad_version) {
        return Ok(dir);
    } else {
        tracing::info!(
            vestad = vestad_version,
            agent = on_disk_version(config).as_deref().unwrap_or("missing"),
            "updating agent code from github"
        );
        fetch_agent_code_from_github(config, vestad_version)?;
    }

    if !is_populated(config) {
        return Err(AgentCodeError::Extract(
            "agent code population succeeded but validation failed".into(),
        ));
    }

    tracing::info!("agent code ready at {}", dir.display());
    Ok(dir)
}

/// Find the repo root by walking up from cwd looking for agent/core/main.py.
fn find_repo_agent_dir() -> Option<PathBuf> {
    let mut dir = std::env::current_dir().ok()?;
    for _ in 0..10 {
        let candidate = dir.join("agent");
        if candidate.join("core/main.py").exists() {
            return Some(candidate);
        }
        dir = dir.parent()?.to_path_buf();
    }
    None
}

/// Most recent mtime of any file under `dir` (recursive).
fn newest_mtime(dir: &Path) -> Option<std::time::SystemTime> {
    fn walk(dir: &Path, newest: &mut Option<std::time::SystemTime>) {
        let entries = fs::read_dir(dir).ok();
        for entry in entries.into_iter().flatten().filter_map(|e| e.ok()) {
            if let Ok(meta) = entry.metadata() {
                if let Ok(mtime) = meta.modified() {
                    if newest.is_none_or(|n| mtime > n) {
                        *newest = Some(mtime);
                    }
                }
                if meta.is_dir() {
                    walk(&entry.path(), newest);
                }
            }
        }
    }
    let mut newest = None;
    walk(dir, &mut newest);
    newest
}

/// Copy agent code from the local repo into agent-code/, skipping if unchanged.
fn copy_from_local_repo(config: &Path) -> Result<(), AgentCodeError> {
    let agent_dir = find_repo_agent_dir()
        .ok_or_else(|| AgentCodeError::Extract("cannot find agent/ directory in repo".into()))?;

    let dest = agent_code_dir(config);

    // Skip if dest is already up-to-date
    if dest.exists() {
        let src_mtime = newest_mtime(&agent_dir.join("core"));
        let dest_mtime = newest_mtime(&dest.join("core"));
        if let (Some(src), Some(dst)) = (src_mtime, dest_mtime) {
            if dst >= src {
                return Ok(());
            }
        }
    }

    tracing::info!("dev mode: copying agent code from local repo");

    let _ = fs::remove_dir_all(&dest);
    fs::create_dir_all(&dest).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    let status = process::Command::new("cp")
        .args([
            "-r",
            &agent_dir.join("core").display().to_string(),
            &dest.join("core").display().to_string(),
        ])
        .status()
        .map_err(|e| AgentCodeError::Io(e.to_string()))?;
    if !status.success() {
        return Err(AgentCodeError::Extract("failed to copy core".into()));
    }

    for file in ["pyproject.toml", "uv.lock"] {
        fs::copy(agent_dir.join(file), dest.join(file))
            .map_err(|e| AgentCodeError::Io(format!("failed to copy {file}: {e}")))?;
    }

    Ok(())
}

/// Best-effort recursive removal: try `fs::remove_dir_all` first, then fall back
/// to `rm -rf` (handles directories with mixed ownership from previous runs).
fn force_remove_dir(path: &Path) {
    if !path.exists() {
        return;
    }
    if fs::remove_dir_all(path).is_ok() {
        return;
    }
    tracing::warn!(path = %path.display(), "fs::remove_dir_all failed, trying rm -rf");
    let ok = process::Command::new("rm")
        .args(["-rf", &path.display().to_string()])
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !ok {
        tracing::warn!(path = %path.display(), "rm -rf also failed, will use unique temp name");
    }
}

/// Download agent code for a specific release tag from GitHub and atomically swap it in.
fn fetch_agent_code_from_github(config: &Path, tag: &str) -> Result<(), AgentCodeError> {
    let dir = agent_code_dir(config);
    let pid = std::process::id();
    let tmp_dir = config.join(format!("agent-code.new.{pid}"));
    let old_dir = config.join(format!("agent-code.old.{pid}"));

    // Clean up any stale temp directories (best-effort, non-blocking)
    force_remove_dir(&tmp_dir);
    force_remove_dir(&old_dir);
    // Also try to clean generic names from older versions
    force_remove_dir(&config.join("agent-code.new"));
    force_remove_dir(&config.join("agent-code.old"));

    fs::create_dir_all(&tmp_dir).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    let archive_url = format!("{GITHUB_ARCHIVE_URL}/v{tag}.tar.gz");
    let archive_path = format!("/tmp/{TEMP_PREFIX}-{}.tar.gz", std::process::id());

    // Download
    let ok = process::Command::new("curl")
        .args(["-fsSL", "-o", &archive_path, &archive_url])
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !ok {
        force_remove_dir(&tmp_dir);
        let _ = fs::remove_file(&archive_path);
        return Err(AgentCodeError::Download(format!("failed to download {archive_url}")));
    }

    // GitHub archives have prefix vesta-{tag}/ (v is stripped from directory name).
    // --strip-components=2 turns vesta-{tag}/agent/core/... into core/...
    let prefix = format!("vesta-{tag}/agent");
    let ok = process::Command::new("tar")
        .args([
            "-xzf", &archive_path,
            "-C", &tmp_dir.display().to_string(),
            "--strip-components=2",
            &prefix,
        ])
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    let _ = fs::remove_file(&archive_path);

    if !ok {
        force_remove_dir(&tmp_dir);
        return Err(AgentCodeError::Extract("failed to extract agent/ from tarball".into()));
    }

    // Validate
    if !tmp_dir.join("core/main.py").exists() || !tmp_dir.join("pyproject.toml").exists() {
        force_remove_dir(&tmp_dir);
        return Err(AgentCodeError::Extract("extracted archive missing required files".into()));
    }

    // Atomic swap
    if dir.exists() {
        fs::rename(&dir, &old_dir).map_err(|e| {
            force_remove_dir(&tmp_dir);
            AgentCodeError::Io(format!("failed to move old agent-code: {e}"))
        })?;
    }

    fs::rename(&tmp_dir, &dir).map_err(|e| {
        if old_dir.exists() {
            let _ = fs::rename(&old_dir, &dir);
        }
        AgentCodeError::Io(format!("failed to move new agent-code into place: {e}"))
    })?;

    force_remove_dir(&old_dir);
    tracing::info!(tag = %tag, "agent code updated successfully");
    Ok(())
}

// TODO: re-add fetch_agent_code_known_tag test after first release with agent/core/ layout
