#[cfg(target_os = "linux")]
pub mod linux;

#[cfg(target_os = "macos")]
#[allow(dead_code)]
pub mod macos;

#[cfg(target_os = "windows")]
#[allow(dead_code)]
pub mod windows;

use std::path::PathBuf;

pub struct ServerConfig {
    pub url: String,
    pub api_key: String,
    pub cert_fingerprint: Option<String>,
}

fn config_dir() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join("vesta")
}

fn server_json_path() -> PathBuf {
    config_dir().join("server.json")
}

pub fn load_server_config(host_flag: Option<&str>, token_flag: Option<&str>) -> Option<ServerConfig> {
    // 1. Flags
    if let (Some(host), Some(token)) = (host_flag, token_flag) {
        return Some(ServerConfig {
            url: normalize_url(host),
            api_key: token.to_string(),
            cert_fingerprint: None,
        });
    }

    // 2. Env vars
    let env_host = std::env::var("VESTA_HOST").ok();
    let env_token = std::env::var("VESTA_TOKEN").ok();
    if let (Some(host), Some(token)) = (env_host.as_deref(), env_token.as_deref()) {
        return Some(ServerConfig {
            url: normalize_url(host),
            api_key: token.to_string(),
            cert_fingerprint: None,
        });
    }

    // 3. server.json
    if let Ok(content) = std::fs::read_to_string(server_json_path()) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&content) {
            if let (Some(url), Some(key)) = (v["url"].as_str(), v["api_key"].as_str()) {
                return Some(ServerConfig {
                    url: url.to_string(),
                    api_key: key.to_string(),
                    cert_fingerprint: v["cert_fingerprint"].as_str().map(|s| s.to_string()),
                });
            }
        }
    }

    // 4. Linux-only: read directly from server filesystem
    #[cfg(target_os = "linux")]
    {
        let home = std::env::var("HOME").unwrap_or_else(|_| "/root".to_string());
        let key_path = format!("{}/.config/vesta/api-key", home);
        if let Ok(key) = std::fs::read_to_string(&key_path) {
            let key = key.trim().to_string();
            if !key.is_empty() {
                let fingerprint = std::fs::read_to_string(format!("{}/.config/vesta/tls/fingerprint", home))
                    .ok()
                    .map(|s| s.trim().to_string());
                return Some(ServerConfig {
                    url: "https://localhost:7860".to_string(),
                    api_key: key,
                    cert_fingerprint: fingerprint,
                });
            }
        }
    }

    None
}

pub fn save_server_config(config: &ServerConfig) {
    let dir = config_dir();
    std::fs::create_dir_all(&dir).ok();

    let mut json = serde_json::json!({
        "url": config.url,
        "api_key": config.api_key,
    });
    if let Some(ref fp) = config.cert_fingerprint {
        json["cert_fingerprint"] = serde_json::json!(fp);
    }

    let path = server_json_path();
    std::fs::write(&path, serde_json::to_string_pretty(&json).unwrap()).ok();

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).ok();
    }
}

fn normalize_url(host: &str) -> String {
    if host.starts_with("https://") || host.starts_with("http://") {
        host.to_string()
    } else {
        format!("https://{}", host)
    }
}

pub fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}
