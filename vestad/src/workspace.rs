//! Thin edge around vestad/scripts/build-workspace.sh: the script owns all git logic
//! (and has its own real-git test suite in agent/tests/test_build_workspace.py); this
//! module only probes git, materializes the embedded script, and runs it.

use std::fmt;
use std::path::{Path, PathBuf};
use std::process::Command;

const BUILD_SCRIPT: &str = include_str!("../scripts/build-workspace.sh");
const SCRIPT_FILENAME: &str = "build-workspace.sh";

#[derive(Debug)]
pub enum WorkspaceError {
    GitMissing,
    Io(String),
    BuildFailed(String),
}

impl fmt::Display for WorkspaceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::GitMissing => write!(f, "git is required on the host to build the agent workspace (install git and restart vestad)"),
            Self::Io(msg) => write!(f, "workspace io error: {msg}"),
            Self::BuildFailed(msg) => write!(f, "build-workspace.sh failed: {msg}"),
        }
    }
}

impl std::error::Error for WorkspaceError {}

pub fn workspace_dir(config_dir: &Path) -> PathBuf {
    config_dir.join("workspace")
}

pub fn bundle_path(config_dir: &Path) -> PathBuf {
    workspace_dir(config_dir).join("workspace.bundle")
}

/// Build/refresh this host's workspace repo + bundle from the extracted agent content.
/// No-op (fast) when the content hasn't changed; the script owns that decision.
pub fn ensure_workspace(config_dir: &Path, content_dir: &Path) -> Result<(), WorkspaceError> {
    let git_ok = Command::new("git")
        .arg("--version")
        .output()
        .map(|out| out.status.success());
    if !matches!(git_ok, Ok(true)) {
        return Err(WorkspaceError::GitMissing);
    }

    let dir = workspace_dir(config_dir);
    std::fs::create_dir_all(&dir).map_err(|e| WorkspaceError::Io(e.to_string()))?;
    let script = dir.join(SCRIPT_FILENAME);
    std::fs::write(&script, BUILD_SCRIPT).map_err(|e| WorkspaceError::Io(e.to_string()))?;

    let output = Command::new("bash")
        .arg(&script)
        .arg(content_dir)
        .arg(&dir)
        .arg(env!("CARGO_PKG_VERSION"))
        .output()
        .map_err(|e| WorkspaceError::Io(e.to_string()))?;
    if !output.status.success() {
        return Err(WorkspaceError::BuildFailed(
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    tracing::info!("{}", String::from_utf8_lossy(&output.stdout).trim());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ensure_workspace_builds_bundle_from_content_dir() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let content = tmp.path().join("agent-code");
        std::fs::create_dir_all(content.join("core")).expect("mkdir");
        std::fs::write(
            content.join("core/pyproject.toml"),
            "[project]\nname = \"vesta\"\nversion = \"0.0.0\"\n",
        )
        .expect("write");
        std::fs::write(content.join("MEMORY.md"), "# m\n").expect("write");

        ensure_workspace(tmp.path(), &content).expect("first build");
        assert!(bundle_path(tmp.path()).is_file());
        // Second run with unchanged content is a no-op, not an error.
        ensure_workspace(tmp.path(), &content).expect("no-op rerun");
    }
}
