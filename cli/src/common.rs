use std::path::PathBuf;

use serde::{Deserialize, Serialize};

// ── Constants ───────────────────────────────────────────────────

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
    pub ws_port: u16,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct ListEntry {
    pub name: String,
    pub status: String,
    pub ws_port: u16,
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

// ── Backup Types ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum BackupType {
    Manual,
    Daily,
    Weekly,
    Monthly,
    PreRestore,
}

impl std::fmt::Display for BackupType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Manual => write!(f, "manual"),
            Self::Daily => write!(f, "daily"),
            Self::Weekly => write!(f, "weekly"),
            Self::Monthly => write!(f, "monthly"),
            Self::PreRestore => write!(f, "pre-restore"),
        }
    }
}

impl std::str::FromStr for BackupType {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "manual" => Ok(Self::Manual),
            "daily" => Ok(Self::Daily),
            "weekly" => Ok(Self::Weekly),
            "monthly" => Ok(Self::Monthly),
            "pre-restore" => Ok(Self::PreRestore),
            other => Err(format!("unknown backup type: {}", other)),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackupInfo {
    pub id: String,
    pub agent_name: String,
    pub backup_type: BackupType,
    pub created_at: String,
    pub size: u64,
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
        .join("cli")
}

pub fn config_path() -> PathBuf {
    config_dir().join("config.json")
}

pub fn load_config() -> VestaConfig {
    if let Ok(content) = std::fs::read_to_string(config_path()) {
        if let Ok(config) = serde_json::from_str(&content) {
            return config;
        }
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

// ── Helpers ────────────────────────────────────────────────────

pub fn normalize_url(host: &str) -> String {
    if host.starts_with("https://") || host.starts_with("http://") {
        host.to_string()
    } else {
        format!("https://{}", host)
    }
}

pub fn version_less_than(a: &str, b: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> {
        v.split('.').filter_map(|s| s.parse().ok()).collect()
    };
    parse(a) < parse(b)
}

// ── Update checks ───────────────────────────────────────────────

const GITHUB_RELEASES_LATEST_URL: &str =
    "https://api.github.com/repos/elyxlz/vesta/releases/latest";

pub fn fetch_latest_release_tag(timeout_secs: Option<u64>) -> Option<String> {
    let mut args: Vec<String> = vec![
        "-fsSL".into(),
        "-H".into(),
        "Accept: application/vnd.github+json".into(),
        "-H".into(),
        "User-Agent: vesta-release-check".into(),
    ];
    if let Some(t) = timeout_secs {
        args.push("--connect-timeout".into());
        args.push(t.to_string());
        args.push("--max-time".into());
        args.push(t.to_string());
    }
    args.push(GITHUB_RELEASES_LATEST_URL.into());

    let output = std::process::Command::new("curl")
        .args(&args)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }

    let body = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value = serde_json::from_str(&body).ok()?;
    let tag = data.get("tag_name")?.as_str()?.trim().trim_start_matches('v');
    if tag.is_empty() {
        None
    } else {
        Some(tag.to_string())
    }
}
