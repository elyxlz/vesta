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
    dir.join("src/vesta/main.py").exists()
        && dir.join("pyproject.toml").is_file()
        && dir.join("uv.lock").is_file()
}

/// Ensure agent code exists on the host.
/// - Dev (debug builds): copies from the local repo
/// - Prod (release builds): downloads from GitHub for the current version
pub fn ensure_agent_code(config: &Path) -> Result<PathBuf, AgentCodeError> {
    let dir = agent_code_dir(config);
    if is_populated(config) {
        return Ok(dir);
    }

    if cfg!(debug_assertions) {
        tracing::info!("dev mode: copying agent code from local repo");
        copy_from_local_repo(config)?;
    } else {
        let version = env!("CARGO_PKG_VERSION");
        tracing::info!(version, "downloading agent code from github");
        fetch_agent_code_from_github(config, version)?;
    }

    if !is_populated(config) {
        return Err(AgentCodeError::Extract(
            "agent code population succeeded but validation failed".into(),
        ));
    }

    tracing::info!("agent code ready at {}", dir.display());
    Ok(dir)
}

/// Find the repo root by walking up from cwd looking for agent/src/vesta/main.py.
fn find_repo_agent_dir() -> Option<PathBuf> {
    let mut dir = std::env::current_dir().ok()?;
    for _ in 0..10 {
        let candidate = dir.join("agent");
        if candidate.join("src/vesta/main.py").exists() {
            return Some(candidate);
        }
        dir = dir.parent()?.to_path_buf();
    }
    None
}

/// Copy agent code from the local repo into agent-code/.
fn copy_from_local_repo(config: &Path) -> Result<(), AgentCodeError> {
    let agent_dir = find_repo_agent_dir()
        .ok_or_else(|| AgentCodeError::Extract("cannot find agent/ directory in repo".into()))?;

    let dest = agent_code_dir(config);
    // Clean and recreate
    let _ = fs::remove_dir_all(&dest);
    fs::create_dir_all(&dest).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    // Copy src/vesta/ using cp -r
    let src_dest = dest.join("src");
    fs::create_dir_all(&src_dest).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    let status = process::Command::new("cp")
        .args(["-r",
            &agent_dir.join("src/vesta").display().to_string(),
            &src_dest.join("vesta").display().to_string(),
        ])
        .status()
        .map_err(|e| AgentCodeError::Io(e.to_string()))?;
    if !status.success() {
        return Err(AgentCodeError::Extract("failed to copy src/vesta".into()));
    }

    // Copy individual files
    for file in ["pyproject.toml", "uv.lock"] {
        fs::copy(agent_dir.join(file), dest.join(file))
            .map_err(|e| AgentCodeError::Io(format!("failed to copy {file}: {e}")))?;
    }

    Ok(())
}

/// Download agent code for a specific release tag from GitHub and atomically swap it in.
pub fn fetch_agent_code_from_github(config: &Path, tag: &str) -> Result<(), AgentCodeError> {
    let dir = agent_code_dir(config);
    let tmp_dir = config.join("agent-code.new");
    let old_dir = config.join("agent-code.old");

    // Clean up any leftover temp dirs from previous failed attempts
    let _ = fs::remove_dir_all(&tmp_dir);
    let _ = fs::remove_dir_all(&old_dir);

    fs::create_dir_all(&tmp_dir).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    let archive_url = format!("{GITHUB_ARCHIVE_URL}/{tag}.tar.gz");
    tracing::info!(tag = %tag, url = %archive_url, "downloading agent code from github");

    // Download tarball
    let archive_path = format!("/tmp/{TEMP_PREFIX}-{}.tar.gz", std::process::id());
    let status = process::Command::new("curl")
        .args(["-fsSL", "-o", &archive_path, &archive_url])
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        let _ = fs::remove_dir_all(&tmp_dir);
        let _ = fs::remove_file(&archive_path);
        return Err(AgentCodeError::Download(format!("failed to download {archive_url}")));
    }

    tracing::info!("extracting tarball");

    // Extract only the files we need from the tarball
    // GitHub archives have a prefix directory like vesta-{tag}/
    let prefix = format!("vesta-{tag}");

    // Extract agent/src/vesta/
    let src_dest = tmp_dir.join("src");
    fs::create_dir_all(&src_dest).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    let extract_ok = process::Command::new("tar")
        .args([
            "-xzf", &archive_path,
            "-C", &src_dest.display().to_string(),
            "--strip-components=3",
            &format!("{prefix}/agent/src/vesta"),
        ])
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !extract_ok {
        let _ = fs::remove_dir_all(&tmp_dir);
        let _ = fs::remove_file(&archive_path);
        return Err(AgentCodeError::Extract("failed to extract src/vesta from tarball".into()));
    }

    // The above extracts contents of vesta/ into src/, but we need src/vesta/
    // tar --strip-components=3 on vesta-tag/agent/src/vesta/* puts files directly in src/
    // We need to move them into src/vesta/
    let extracted_src = tmp_dir.join("src");
    let final_src = tmp_dir.join("src_final/vesta");
    fs::create_dir_all(&final_src).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    // Move all files from extracted_src into final_src
    for entry in fs::read_dir(&extracted_src).map_err(|e| AgentCodeError::Io(e.to_string()))? {
        let entry = entry.map_err(|e| AgentCodeError::Io(e.to_string()))?;
        let dest = final_src.join(entry.file_name());
        fs::rename(entry.path(), &dest).map_err(|e| AgentCodeError::Io(e.to_string()))?;
    }
    fs::remove_dir_all(&extracted_src).ok();
    fs::rename(tmp_dir.join("src_final"), tmp_dir.join("src"))
        .map_err(|e| AgentCodeError::Io(e.to_string()))?;

    // Extract pyproject.toml
    let extract_ok = process::Command::new("tar")
        .args([
            "-xzf", &archive_path,
            "-C", &tmp_dir.display().to_string(),
            "--strip-components=2",
            &format!("{prefix}/agent/pyproject.toml"),
        ])
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !extract_ok {
        let _ = fs::remove_dir_all(&tmp_dir);
        let _ = fs::remove_file(&archive_path);
        return Err(AgentCodeError::Extract("failed to extract pyproject.toml from tarball".into()));
    }

    // Extract uv.lock
    let extract_ok = process::Command::new("tar")
        .args([
            "-xzf", &archive_path,
            "-C", &tmp_dir.display().to_string(),
            "--strip-components=2",
            &format!("{prefix}/agent/uv.lock"),
        ])
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !extract_ok {
        let _ = fs::remove_dir_all(&tmp_dir);
        let _ = fs::remove_file(&archive_path);
        return Err(AgentCodeError::Extract("failed to extract uv.lock from tarball".into()));
    }

    let _ = fs::remove_file(&archive_path);

    // Validate before swap
    if !tmp_dir.join("src/vesta/main.py").exists() {
        let _ = fs::remove_dir_all(&tmp_dir);
        return Err(AgentCodeError::Extract("src/vesta/main.py not found in extracted archive".into()));
    }
    if !tmp_dir.join("pyproject.toml").exists() {
        let _ = fs::remove_dir_all(&tmp_dir);
        return Err(AgentCodeError::Extract("pyproject.toml not found in extracted archive".into()));
    }

    // Atomic swap: agent-code -> agent-code.old, agent-code.new -> agent-code
    if dir.exists() {
        fs::rename(&dir, &old_dir).map_err(|e| {
            let _ = fs::remove_dir_all(&tmp_dir);
            AgentCodeError::Io(format!("failed to move old agent-code: {e}"))
        })?;
    }

    fs::rename(&tmp_dir, &dir).map_err(|e| {
        // Try to restore old dir
        if old_dir.exists() {
            let _ = fs::rename(&old_dir, &dir);
        }
        AgentCodeError::Io(format!("failed to move new agent-code into place: {e}"))
    })?;

    let _ = fs::remove_dir_all(&old_dir);

    tracing::info!(tag = %tag, "agent code updated successfully");
    Ok(())
}
