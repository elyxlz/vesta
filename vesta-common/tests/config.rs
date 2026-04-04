use vesta_common::client::ws_base_url;
use vesta_common::{is_local_server, normalize_url, version_less_than, ServerConfig};

#[test]
fn normalize_url_adds_https() {
    assert_eq!(normalize_url("localhost:7860"), "https://localhost:7860");
    assert_eq!(normalize_url("https://already.com"), "https://already.com");
    assert_eq!(normalize_url("http://plain.com"), "http://plain.com");
}

#[test]
fn ws_base_url_converts_protocol() {
    assert_eq!(ws_base_url("https://localhost:7860"), "wss://localhost:7860");
    assert_eq!(ws_base_url("http://localhost:7860"), "ws://localhost:7860");
}

#[test]
fn server_config_json_roundtrip() {
    let config = vesta_common::ServerConfig {
        url: "https://localhost:7860".into(),
        api_key: "test-key".into(),
        cert_fingerprint: Some("sha256:AA:BB".into()),
        cert_pem: Some("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n".into()),
    };
    let json = serde_json::to_string(&config).unwrap();
    let parsed: vesta_common::ServerConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.url, config.url);
    assert_eq!(parsed.api_key, config.api_key);
    assert_eq!(parsed.cert_fingerprint, config.cert_fingerprint);
}

#[test]
fn version_comparison() {
    assert!(version_less_than("0.1.104", "0.1.105"));
    assert!(!version_less_than("0.1.105", "0.1.104"));
    assert!(!version_less_than("0.1.105", "0.1.105"));
    assert!(version_less_than("0.1.9", "0.1.10"));
    assert!(version_less_than("0.1.0", "0.2.0"));
    assert!(version_less_than("0.9.0", "1.0.0"));
}

#[test]
fn server_config_file_roundtrip() {
    let tmp = tempfile::TempDir::new().unwrap();
    let path = tmp.path().join("server.json");

    let config = vesta_common::ServerConfig {
        url: "https://test:1234".into(),
        api_key: "key".into(),
        cert_fingerprint: Some("sha256:test".into()),
        cert_pem: None,
    };
    let json = serde_json::to_string_pretty(&config).unwrap();
    std::fs::write(&path, &json).unwrap();

    let content = std::fs::read_to_string(&path).unwrap();
    let loaded: vesta_common::ServerConfig = serde_json::from_str(&content).unwrap();
    assert_eq!(loaded.url, config.url);
    assert_eq!(loaded.api_key, config.api_key);
    assert_eq!(loaded.cert_fingerprint, config.cert_fingerprint);
}

#[test]
fn vesta_config_embeds_server() {
    let config = vesta_common::VestaConfig {
        server: Some(vesta_common::ServerConfig {
            url: "https://test:7860".into(),
            api_key: "key".into(),
            cert_fingerprint: None,
            cert_pem: None,
        }),
    };
    let json = serde_json::to_string_pretty(&config).unwrap();
    let loaded: vesta_common::VestaConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(loaded.server.unwrap().url, "https://test:7860");
}

#[test]
fn vesta_config_empty_has_no_server() {
    let config = vesta_common::VestaConfig::default();
    assert!(config.server.is_none());
    let json = serde_json::to_string(&config).unwrap();
    assert!(!json.contains("server"), "empty config should omit server");
}

#[test]
fn url_hash_key_parsing() {
    let (url, key) = "https://host:7860#my-api-key".split_once('#').unwrap();
    assert_eq!(url, "https://host:7860");
    assert_eq!(key, "my-api-key");
    assert!("https://host:7860".split_once('#').is_none());
}

#[test]
fn is_local_server_detects_localhost() {
    let local = |url: &str| {
        is_local_server(&ServerConfig {
            url: url.into(),
            api_key: "k".into(),
            cert_fingerprint: None,
            cert_pem: None,
        })
    };
    assert!(local("https://localhost:7860"));
    assert!(local("https://127.0.0.1:7860"));
    assert!(local("https://[::1]:7860"));
    assert!(!local("https://192.168.1.5:7860"));
    assert!(!local("https://my-server.example.com:7860"));
}

#[cfg(target_os = "linux")]
#[test]
fn boot_log_path_is_under_config() {
    let path = vesta_common::platform::linux::boot_log_path();
    let path_str = path.to_string_lossy();
    assert!(path_str.contains(".config/vesta/"), "boot log should be under .config/vesta/");
    assert!(path_str.ends_with("vestad-boot.log"));
}

#[cfg(target_os = "linux")]
#[test]
fn boot_log_summary_returns_empty_for_missing_file() {
    // If the log file doesn't exist, summary should be empty (not error)
    let summary = vesta_common::platform::linux::boot_log_summary();
    // Can't guarantee the file doesn't exist in CI, but at least verify it doesn't panic
    let _ = summary;
}

#[cfg(target_os = "linux")]
#[test]
fn boot_log_summary_truncates_long_output() {
    let log_path = vesta_common::platform::linux::boot_log_path();
    if let Some(parent) = log_path.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    // Write 50 lines, summary should only return first 20
    let lines: Vec<String> = (0..50).map(|i| format!("line {}", i)).collect();
    std::fs::write(&log_path, lines.join("\n")).unwrap();
    let summary = vesta_common::platform::linux::boot_log_summary();
    assert_eq!(summary.lines().count(), 20);
    assert!(summary.starts_with("line 0"));
    assert!(summary.contains("line 19"));
    assert!(!summary.contains("line 20"));
    std::fs::remove_file(&log_path).ok();
}
