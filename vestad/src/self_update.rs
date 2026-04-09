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

    update_agents(&config);

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
/// For pre-migration containers (without read-only mounts), recreate them with mounts.
fn update_agents(config: &std::path::Path) {
    let containers = crate::docker::list_managed_containers();
    if containers.is_empty() {
        tracing::info!("no agents to update");
        return;
    }

    let agents_dir = config.join("agents");

    for cname in &containers {
        let name = crate::docker::get_agent_name(cname);
        let status = crate::docker::container_status(cname);
        let was_running = status == crate::docker::ContainerStatus::Running;

        if crate::docker::has_agent_code_mounts(cname) {
            // Container already has read-only mounts — just restart if running
            if was_running {
                tracing::info!(agent = %name, "restarting agent for code update");
                if !crate::docker::docker_ok(&["restart", cname]) {
                    tracing::error!(agent = %name, "failed to restart agent");
                }
            } else {
                tracing::info!(agent = %name, "agent is stopped, will use new code on next start");
            }
        } else {
            // Pre-migration container: needs recreation with mounts
            tracing::info!(agent = %name, "migrating agent to use read-only mounts");

            let port = crate::docker::read_env_value(&agents_dir, &name, "WS_PORT")
                .and_then(|v| v.parse::<u16>().ok());

            let Some(port) = port else {
                tracing::error!(agent = %name, "cannot migrate: no port in env file");
                continue;
            };

            let vestad_port = crate::docker::read_env_value(&agents_dir, &name, "VESTAD_PORT")
                .and_then(|v| v.parse::<u16>().ok())
                .unwrap_or(0);
            let vestad_tunnel = crate::docker::read_env_value(&agents_dir, &name, "VESTAD_TUNNEL");

            let env_config = crate::docker::AgentEnvConfig {
                config_dir: config.to_path_buf(),
                agents_dir: agents_dir.clone(),
                vestad_port,
                vestad_tunnel,
            };

            // Commit current state as backup
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let backup_tag = format!("vesta-migrate:{}_{}", name, ts);

            if !crate::docker::docker_ok(&["commit", cname, &backup_tag]) {
                tracing::error!(agent = %name, "failed to commit container for migration");
                continue;
            }

            // Remove old container
            crate::docker::docker_ok(&["rm", "-f", cname]);

            // Create new container from backup image (with mounts)
            if let Err(e) = crate::docker::create_container(cname, &backup_tag, port, &name, &env_config) {
                tracing::error!(agent = %name, error = %e, "failed to recreate container with mounts");
                // Backup image still exists for manual recovery
                continue;
            }

            if was_running {
                tracing::info!(agent = %name, "starting migrated agent");
                if !crate::docker::docker_ok(&["start", cname]) {
                    tracing::error!(agent = %name, "failed to start migrated agent");
                }
            } else {
                tracing::info!(agent = %name, "migrated agent (kept stopped)");
            }

            // Clean up backup image
            crate::docker::docker_ok(&["rmi", &backup_tag]);
        }
    }
}
