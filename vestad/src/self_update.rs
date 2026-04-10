use std::fmt;

#[derive(Debug)]
pub enum UpdateError {
    UnsupportedArch(String),
    Download(String),
    Extract(String),
    Replace(String),
    AgentCode(String),
}

impl fmt::Display for UpdateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedArch(arch) => write!(f, "unsupported architecture: {}", arch),
            Self::Download(msg) => write!(f, "failed to download update: {}", msg),
            Self::Extract(msg) => write!(f, "failed to extract update: {}", msg),
            Self::Replace(msg) => write!(f, "failed to replace binary: {}", msg),
            Self::AgentCode(msg) => write!(f, "failed to update agent code: {}", msg),
        }
    }
}

/// Downloads the latest vestad binary from GitHub, replaces the current binary,
/// updates agent code, restarts running agents, and reinstalls the systemd service.
/// Returns Ok(true) if a restart was triggered.
pub fn perform_update() -> Result<bool, UpdateError> {
    let tag = crate::update_check::fetch_latest_tag()
        .ok_or_else(|| UpdateError::Download("cannot determine latest version".into()))?;

    tracing::info!(tag = %tag, "starting update");

    update_binary(&tag)?;

    let config = crate::config_dir();
    tracing::info!(tag = %tag, "updating agent code from github");
    crate::agent_code::fetch_agent_code_from_github(&config, &tag)
        .map_err(|e| UpdateError::AgentCode(e.to_string()))?;

    restart_agents();

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

fn update_binary(tag: &str) -> Result<(), UpdateError> {
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

    tracing::info!(tag = %tag, "downloading vestad binary");
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
    tracing::info!("vestad binary replaced successfully");
    Ok(())
}

/// Restart running agents so they pick up new agent code.
/// Migration of pre-migration containers is handled at startup by docker::migrate_containers.
fn restart_agents() {
    let containers = crate::docker::list_managed_containers();
    if containers.is_empty() {
        tracing::info!("no agents to restart");
        return;
    }

    for cname in &containers {
        let name = crate::docker::get_agent_name(cname);
        let status = crate::docker::container_status(cname);
        if status == crate::docker::ContainerStatus::Running {
            tracing::info!(agent = %name, "restarting agent for code update");
            if !crate::docker::docker_ok(&["restart", cname]) {
                tracing::error!(agent = %name, "failed to restart agent");
            }
        } else {
            tracing::info!(agent = %name, "agent is stopped, will use new code on next start");
        }
    }
}
