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

#[derive(Debug, Deserialize)]
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

// ── Config ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VestaConfig {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server: Option<ServerConfig>,
}

pub fn config_dir() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("vesta")
}

pub fn config_path() -> PathBuf {
    config_dir().join("config.json")
}

/// Legacy server.json path — used for migration only.
pub fn server_json_path() -> PathBuf {
    config_dir().join("server.json")
}

pub fn default_server_url() -> String {
    format!("https://localhost:{}", DEFAULT_API_PORT)
}

pub fn load_config() -> VestaConfig {
    if let Ok(content) = std::fs::read_to_string(config_path()) {
        if let Ok(config) = serde_json::from_str(&content) {
            return config;
        }
    }
    // Migrate from legacy server.json
    if let Some(server) = load_legacy_server_config() {
        let config = VestaConfig { server: Some(server) };
        let _ = save_config(&config);
        let _ = std::fs::remove_file(server_json_path());
        return config;
    }
    VestaConfig::default()
}

pub fn save_config(config: &VestaConfig) -> Result<(), String> {
    let dir = config_dir();
    std::fs::create_dir_all(&dir).map_err(|e| format!("failed to create config dir: {}", e))?;
    let path = config_path();
    let json = serde_json::to_string_pretty(config).unwrap();
    std::fs::write(&path, json).map_err(|e| format!("failed to write config.json: {}", e))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).ok();
    }
    Ok(())
}

pub fn load_server_config() -> Option<ServerConfig> {
    load_config().server
}

pub fn save_server_config(config: &ServerConfig) -> Result<(), String> {
    let mut full = load_config();
    full.server = Some(config.clone());
    save_config(&full)
}

fn load_legacy_server_config() -> Option<ServerConfig> {
    let content = std::fs::read_to_string(server_json_path()).ok()?;
    let config: ServerConfig = serde_json::from_str(&content).ok()?;
    if config.url.is_empty() || config.api_key.is_empty() {
        return None;
    }
    Some(config)
}

/// Wait for vestad to become reachable on the given port.
pub fn wait_for_server_port(port: u16, timeout_secs: u64) -> bool {
    let addr: std::net::SocketAddr = ([127, 0, 0, 1], port).into();
    for _ in 0..timeout_secs {
        if std::net::TcpStream::connect_timeout(&addr, std::time::Duration::from_secs(1)).is_ok() {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
    false
}

/// Wait for vestad on the default API port.
pub fn wait_for_server(timeout_secs: u64) -> bool {
    wait_for_server_port(DEFAULT_API_PORT, timeout_secs)
}

/// Ensure vestad is installed, running, and configured.
/// `vestad_path` is an optional hint to a bundled vestad binary (e.g. from Tauri resources).
/// Returns Ok(true) if setup was performed, Ok(false) if already configured.
#[allow(unused_variables)]
pub fn ensure_server_with(vestad_path: Option<&std::path::Path>) -> Result<bool, String> {
    #[cfg(target_os = "linux")]
    let server_reachable = wait_for_server(1);

    #[cfg(target_os = "linux")]
    {
        #[cfg(debug_assertions)]
        {
            if server_reachable {
                if load_server_config().is_some() {
                    return Ok(false);
                }
            } else {
                install_and_boot(false, vestad_path)?;
            }
        }

        #[cfg(not(debug_assertions))]
        {
            if server_reachable {
                if let Some(config) = load_server_config() {
                    if is_local_server(&config) {
                        let c = client::Client::new(&config);
                        let server_ver = c.server_version().unwrap_or_default();
                        let app_ver = env!("CARGO_PKG_VERSION");
                        if version_less_than(&server_ver, app_ver) {
                            eprintln!("updating vestad {} → {}...", server_ver, app_ver);
                            install_and_boot(true, vestad_path)?;
                        }
                    }
                    return Ok(false);
                }
            } else {
                install_and_boot(false, vestad_path)?;
            }
        }

        if let Some(creds) = platform::linux::extract_credentials() {
            save_server_config(&creds)?;
        }
    }

    #[cfg(not(target_os = "linux"))]
    {
        // On non-Linux platforms, local bootstrap is not supported.
        // Users must connect to a remote server via `vesta connect`.
        if load_server_config().is_some() {
            return Ok(false);
        }
        return Ok(false);
    }

    #[cfg(target_os = "linux")]
    Ok(true)
}

pub fn normalize_url(host: &str) -> String {
    if host.starts_with("https://") || host.starts_with("http://") {
        host.to_string()
    } else {
        format!("https://{}", host)
    }
}

/// Convenience wrapper that calls `ensure_server_with(None)`.
pub fn ensure_server() -> Result<bool, String> {
    ensure_server_with(None)
}

#[cfg(target_os = "linux")]
fn install_and_boot(shutdown_first: bool, vestad_hint: Option<&std::path::Path>) -> Result<(), String> {
    let vestad_path = platform::linux::install_vestad_from(vestad_hint)?;
    platform::linux::install_autostart(&vestad_path)?;
    if shutdown_first {
        platform::linux::shutdown();
    }
    platform::linux::boot()?;
    if !wait_for_server(30) {
        return Err("server did not start within 30s".into());
    }
    Ok(())
}

pub fn is_local_server(config: &ServerConfig) -> bool {
    let url = &config.url;
    url.contains("localhost") || url.contains("127.0.0.1") || url.contains("[::1]")
}

pub fn version_less_than(a: &str, b: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> {
        v.split('.').filter_map(|s| s.parse().ok()).collect()
    };
    parse(a) < parse(b)
}
