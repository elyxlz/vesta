use vesta_common::client::ws_base_url;
use vesta_common::{normalize_url, version_less_than};

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
fn url_hash_key_parsing() {
    let (url, key) = "https://host:7860#my-api-key".split_once('#').unwrap();
    assert_eq!(url, "https://host:7860");
    assert_eq!(key, "my-api-key");
    assert!("https://host:7860".split_once('#').is_none());
}
