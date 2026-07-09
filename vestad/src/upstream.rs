//! Thin edge around vestad/scripts/build-upstream.sh: the script owns all git logic
//! (and has its own real-git test suite in agent/tests/test_build_upstream.py); this
//! module only probes git, materializes the embedded script, and runs it.

use std::fmt;
use std::path::{Path, PathBuf};
use std::process::Command;

const BUILD_SCRIPT: &str = include_str!("../scripts/build-upstream.sh");
const SCRIPT_FILENAME: &str = "build-upstream.sh";

#[derive(Debug)]
pub enum UpstreamError {
    GitMissing,
    Io(String),
    BuildFailed(String),
}

impl fmt::Display for UpstreamError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::GitMissing => write!(f, "git is required on the host to build the agent upstream repo (install git and restart vestad)"),
            Self::Io(msg) => write!(f, "upstream io error: {msg}"),
            Self::BuildFailed(msg) => write!(f, "build-upstream.sh failed: {msg}"),
        }
    }
}

impl std::error::Error for UpstreamError {}

pub fn upstream_dir(config_dir: &Path) -> PathBuf {
    config_dir.join("upstream")
}

// LEGACY(remove-when: no agent predating the release that ships this rename remains and
// the 2026-07 workspace migrations are fleet-applied): old boxes' checked-out
// fetch-workspace.sh curls the bundle endpoint, which serves this file.
pub fn bundle_path(config_dir: &Path) -> PathBuf {
    upstream_dir(config_dir).join("workspace.bundle")
}

// LEGACY(remove-when: no agent predating the release that ships this rename remains and
// the 2026-07 workspace migrations are fleet-applied): hosts upgraded from the workspace
// era keep their append-only snapshot history under the old names; rename it in place.
fn migrate_legacy_layout(config_dir: &Path) -> Result<(), UpstreamError> {
    let old_dir = config_dir.join("workspace");
    let new_dir = upstream_dir(config_dir);
    if old_dir.is_dir() && !new_dir.exists() {
        std::fs::rename(&old_dir, &new_dir).map_err(|e| UpstreamError::Io(e.to_string()))?;
    }
    let old_repo = new_dir.join("workspace.git");
    let new_repo = new_dir.join("upstream.git");
    if old_repo.is_dir() && !new_repo.exists() {
        std::fs::rename(&old_repo, &new_repo).map_err(|e| UpstreamError::Io(e.to_string()))?;
    }
    Ok(())
}

/// Build/refresh this host's upstream repo (+ legacy bundle) from the extracted agent
/// content. No-op (fast) when the content hasn't changed; the script owns that decision.
pub fn ensure_upstream(config_dir: &Path, content_dir: &Path) -> Result<(), UpstreamError> {
    let git_ok = Command::new("git").arg("--version").output().map(|out| out.status.success());
    if !matches!(git_ok, Ok(true)) {
        return Err(UpstreamError::GitMissing);
    }

    migrate_legacy_layout(config_dir)?;
    let dir = upstream_dir(config_dir);
    std::fs::create_dir_all(&dir).map_err(|e| UpstreamError::Io(e.to_string()))?;
    let script = dir.join(SCRIPT_FILENAME);
    std::fs::write(&script, BUILD_SCRIPT).map_err(|e| UpstreamError::Io(e.to_string()))?;

    let output = Command::new("bash")
        .arg(&script)
        .arg(content_dir)
        .arg(&dir)
        .arg(env!("CARGO_PKG_VERSION"))
        .output()
        .map_err(|e| UpstreamError::Io(e.to_string()))?;
    if !output.status.success() {
        return Err(UpstreamError::BuildFailed(String::from_utf8_lossy(&output.stderr).trim().to_string()));
    }
    tracing::info!("{}", String::from_utf8_lossy(&output.stdout).trim());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn content_dir(tmp: &Path) -> PathBuf {
        let content = tmp.join("agent-code");
        std::fs::create_dir_all(content.join("core")).expect("mkdir");
        std::fs::write(content.join("core/pyproject.toml"), "[project]\nname = \"vesta\"\nversion = \"0.0.0\"\n").expect("write");
        std::fs::write(content.join("MEMORY.md"), "# m\n").expect("write");
        content
    }

    #[test]
    fn ensure_upstream_builds_repo_and_legacy_bundle_from_content_dir() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let content = content_dir(tmp.path());

        ensure_upstream(tmp.path(), &content).expect("first build");
        assert!(upstream_dir(tmp.path()).join("upstream.git").is_dir());
        assert!(bundle_path(tmp.path()).is_file());
        // Second run with unchanged content is a no-op, not an error.
        ensure_upstream(tmp.path(), &content).expect("no-op rerun");
    }

    #[test]
    fn legacy_workspace_layout_is_renamed_preserving_history() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let content = content_dir(tmp.path());
        ensure_upstream(tmp.path(), &content).expect("first build");

        // Recreate the pre-rename layout from the built state.
        let dir = upstream_dir(tmp.path());
        std::fs::rename(dir.join("upstream.git"), dir.join("workspace.git")).expect("rename repo back");
        std::fs::rename(&dir, tmp.path().join("workspace")).expect("rename dir back");

        ensure_upstream(tmp.path(), &content).expect("rebuild after migration");
        assert!(upstream_dir(tmp.path()).join("upstream.git").is_dir());
        assert!(!tmp.path().join("workspace").exists());
    }
}
