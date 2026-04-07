use std::fmt;

#[derive(Debug)]
pub enum UpdateError {
    UnsupportedArch(String),
    Download(String),
    Extract(String),
    Replace(String),
}

impl fmt::Display for UpdateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedArch(arch) => write!(f, "unsupported architecture: {}", arch),
            Self::Download(msg) => write!(f, "failed to download update: {}", msg),
            Self::Extract(msg) => write!(f, "failed to extract update: {}", msg),
            Self::Replace(msg) => write!(f, "failed to replace binary: {}", msg),
        }
    }
}

/// Downloads the latest vestad binary from GitHub, replaces the current binary,
/// and reinstalls the systemd service. Returns Ok(true) if a restart was triggered.
pub fn perform_update() -> Result<bool, UpdateError> {
    let target = match std::env::consts::ARCH {
        "x86_64" => "x86_64-unknown-linux-gnu",
        "aarch64" => "aarch64-unknown-linux-gnu",
        other => return Err(UpdateError::UnsupportedArch(other.to_string())),
    };

    let archive = format!("vestad-{}.tar.gz", target);
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/latest/download/{}",
        archive
    );
    let tmp = format!("/tmp/vestad-update-{}", std::process::id());
    std::fs::create_dir_all(&tmp).ok();

    tracing::info!("downloading update...");
    let status = std::process::Command::new("curl")
        .args(["-fsSL", "-o", &format!("{}/{}", tmp, archive), &url])
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        std::fs::remove_dir_all(&tmp).ok();
        return Err(UpdateError::Download("curl failed".into()));
    }

    let status = std::process::Command::new("tar")
        .args(["-xzf", &format!("{}/{}", tmp, archive), "-C", &tmp])
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        std::fs::remove_dir_all(&tmp).ok();
        return Err(UpdateError::Extract("tar failed".into()));
    }

    let new_binary = format!("{}/vestad", tmp);
    self_replace::self_replace(&new_binary)
        .map_err(|e| UpdateError::Replace(e.to_string()))?;

    std::fs::remove_dir_all(&tmp).ok();

    if let Err(e) = crate::systemd::reinstall_service() {
        tracing::warn!("failed to update systemd service: {e}");
    }

    if crate::systemd::is_active() {
        tracing::info!("restarting vestad...");
        if let Err(e) = crate::systemd::restart() {
            tracing::error!("failed to restart: {e}");
        }
        Ok(true)
    } else {
        tracing::info!("updated. run 'vestad' to start.");
        Ok(false)
    }
}
