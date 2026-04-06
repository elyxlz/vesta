pub use vesta_common::{save_server_config, normalize_url, ServerConfig};

pub fn load_server_config(host_flag: Option<&str>, token_flag: Option<&str>) -> Option<ServerConfig> {
    // 1. Flags
    if let (Some(host), Some(token)) = (host_flag, token_flag) {
        return Some(ServerConfig {
            url: normalize_url(host),
            api_key: token.to_string(),
            cert_fingerprint: None,
            cert_pem: None,
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
            cert_pem: None,
        });
    }

    // 3. config.json
    vesta_common::load_server_config()
}

pub fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}
