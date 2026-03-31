pub mod client;
pub mod platform;

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

// ── Constants ───────────────────────────────────────────────────

pub const DEFAULT_WS_PORT: u16 = 7865;
pub const DEFAULT_API_PORT: u16 = 7860;

// ── Types ───────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    pub url: String,
    pub api_key: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cert_fingerprint: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cert_pem: Option<String>,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct StatusJson {
    pub name: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub authenticated: bool,
    #[serde(default)]
    pub agent_ready: bool,
    pub ws_port: u16,
    pub alive: bool,
    pub friendly_status: String,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct ListEntry {
    pub name: String,
    pub status: String,
    pub authenticated: bool,
    pub agent_ready: bool,
    pub ws_port: u16,
    #[serde(default)]
    pub alive: bool,
    #[serde(default)]
    pub friendly_status: String,
}

#[derive(Deserialize)]
pub struct AuthFlowResponse {
    pub auth_url: String,
    pub session_id: String,
}

#[derive(Deserialize)]
pub struct StartAllResult {
    pub name: String,
    pub ok: bool,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum AgentStatus {
    Running,
    Stopped,
    Dead,
    NotFound,
    Unknown,
}

// ── Config helpers ──────────────────────────────────────────────

pub fn config_dir() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join("vesta")
}

pub fn server_json_path() -> PathBuf {
    config_dir().join("server.json")
}

pub fn default_server_url() -> String {
    format!("https://localhost:{}", DEFAULT_API_PORT)
}

pub fn load_server_config() -> Option<ServerConfig> {
    let content = std::fs::read_to_string(server_json_path()).ok()?;
    let config: ServerConfig = serde_json::from_str(&content).ok()?;
    if config.url.is_empty() || config.api_key.is_empty() {
        return None;
    }
    Some(config)
}

pub fn save_server_config(config: &ServerConfig) -> Result<(), String> {
    let dir = config_dir();
    std::fs::create_dir_all(&dir).map_err(|e| format!("failed to create config dir: {}", e))?;

    let path = server_json_path();
    let json = serde_json::to_string_pretty(config).unwrap();
    std::fs::write(&path, json).map_err(|e| format!("failed to write server.json: {}", e))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).ok();
    }
    Ok(())
}

/// Wait for vestad to become reachable (TCP connect to API port).
pub fn wait_for_server(timeout_secs: u64) -> bool {
    let addr = format!("localhost:{}", DEFAULT_API_PORT);
    let addr: std::net::SocketAddr = addr.parse().unwrap();
    for _ in 0..timeout_secs {
        if std::net::TcpStream::connect_timeout(&addr, std::time::Duration::from_secs(1)).is_ok() {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
    false
}

/// Ensure vestad is installed, running, and configured.
/// If server.json already exists and the server is reachable, this is a no-op.
/// Otherwise, runs platform-specific setup (download vestad, install, boot, extract creds).
/// Returns Ok(true) if setup was performed, Ok(false) if already configured.
pub fn ensure_server() -> Result<bool, String> {
    let server_reachable = wait_for_server(1);

    // Already configured and reachable?
    if load_server_config().is_some() && server_reachable {
        return Ok(false);
    }

    // Platform-specific setup
    #[cfg(target_os = "linux")]
    {
        if !server_reachable {
            let vestad_path = platform::linux::install_vestad()?;
            platform::linux::install_autostart(&vestad_path)?;
            platform::linux::boot()?;

            if !wait_for_server(30) {
                return Err("server did not start within 30s".into());
            }
        }

        if let Some(creds) = platform::linux::extract_credentials() {
            save_server_config(&creds)?;
        }
    }

    #[cfg(target_os = "macos")]
    {
        platform::macos::setup(None, false, true)?;
        if let Some(creds) = platform::macos::extract_credentials() {
            save_server_config(&creds)?;
        }
    }

    #[cfg(target_os = "windows")]
    {
        platform::windows::boot()?;
        if let Some(creds) = platform::windows::extract_credentials() {
            save_server_config(&creds)?;
        }
    }

    Ok(true)
}

pub fn normalize_url(host: &str) -> String {
    if host.starts_with("https://") || host.starts_with("http://") {
        host.to_string()
    } else {
        format!("https://{}", host)
    }
}
