#[cfg(target_os = "linux")]
pub use vesta_common::platform::*;
pub use vesta_common::{save_server_config, normalize_url, ServerConfig};

/// Try to read the TLS cert PEM from the local vestad config directory.
fn try_read_local_cert() -> Option<String> {
    #[cfg(target_os = "linux")]
    {
        let home = std::env::var("HOME").ok()?;
        std::fs::read_to_string(format!("{}/.config/vesta/tls/cert.pem", home)).ok()
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

pub fn load_server_config(host_flag: Option<&str>, token_flag: Option<&str>) -> Option<ServerConfig> {
    // 1. Flags
    if let (Some(host), Some(token)) = (host_flag, token_flag) {
        return Some(ServerConfig {
            url: normalize_url(host),
            api_key: token.to_string(),
            cert_fingerprint: None,
            cert_pem: try_read_local_cert(),
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
            cert_pem: try_read_local_cert(),
        });
    }

    // 3. server.json (via vesta-common)
    if let Some(config) = vesta_common::load_server_config() {
        return Some(config);
    }

    // 4. Linux-only: read directly from server filesystem
    #[cfg(target_os = "linux")]
    if let Some(config) = vesta_common::platform::linux::extract_credentials() {
        return Some(config);
    }

    None
}

pub fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}
