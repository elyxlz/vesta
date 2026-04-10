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
    agent_code_dir(config).join("src/vesta/main.py").exists()
}

/// Ensure agent code exists on the host. Extracts from the Docker image on first call.
/// Subsequent calls are a no-op.
pub fn ensure_agent_code(config: &Path, image: &str) -> Result<PathBuf, AgentCodeError> {
    let dir = agent_code_dir(config);
    if is_populated(config) {
        tracing::info!("agent code already exists at {}", dir.display());
        return Ok(dir);
    }

    tracing::info!(image = %image, "extracting agent code from docker image");
    extract_from_image(config, image)?;

    if !is_populated(config) {
        return Err(AgentCodeError::Extract(
            "extraction succeeded but src/vesta/main.py not found".into(),
        ));
    }

    tracing::info!("agent code extracted to {}", dir.display());
    Ok(dir)
}

/// Extract src/vesta/, pyproject.toml, uv.lock from a Docker image into agent-code/.
fn extract_from_image(config: &Path, image: &str) -> Result<(), AgentCodeError> {
    let dir = agent_code_dir(config);
    fs::create_dir_all(&dir).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    let temp_name = format!("{TEMP_PREFIX}-{}", std::process::id());

    // Create a temporary container (not started) to copy files from
    if !crate::docker::docker_ok(&["create", "--name", &temp_name, image, "true"]) {
        return Err(AgentCodeError::Extract("failed to create temp container".into()));
    }

    let cleanup = || {
        crate::docker::docker_ok(&["rm", "-f", &temp_name]);
    };

    // Copy src/vesta/ directory
    let src_dest = dir.join("src");
    fs::create_dir_all(&src_dest).map_err(|e| {
        cleanup();
        AgentCodeError::Io(e.to_string())
    })?;

    let copy_results = [
        ("src/vesta", "/root/vesta/src/vesta", src_dest.join("vesta")),
    ];

    for (label, container_path, host_dest) in &copy_results {
        tracing::debug!(path = %label, "copying from container");
        let src = format!("{temp_name}:{container_path}");
        if !crate::docker::docker_ok(&["cp", &src, &host_dest.display().to_string()]) {
            cleanup();
            return Err(AgentCodeError::Extract(format!("failed to copy {label} from container")));
        }
    }

    // Copy individual files (destination must include filename, not just directory)
    for (label, container_path) in [
        ("pyproject.toml", "/root/vesta/pyproject.toml"),
        ("uv.lock", "/root/vesta/uv.lock"),
    ] {
        tracing::debug!(path = %label, "copying from container");
        let src = format!("{temp_name}:{container_path}");
        let dest = dir.join(label);
        if !crate::docker::docker_ok(&["cp", &src, &dest.display().to_string()]) {
            cleanup();
            return Err(AgentCodeError::Extract(format!("failed to copy {label} from container")));
        }
    }

    cleanup();
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
