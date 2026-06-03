use vesta_tests::{find_vestad, SERVER};
use vesta_tests::client::Client;
use vesta_tests::types::ServerConfig;

#[test]
fn health() {
    SERVER.client().health().expect("health failed");
}

#[test]
fn health_includes_user() {
    let body = SERVER.client().health_json().unwrap();
    assert!(body["ok"].as_bool().unwrap());
    let user = body["user"].as_str().expect("health should include 'user' field");
    assert!(!user.is_empty());
}

#[test]
fn wrong_token_rejected() {
    let bad = Client::new(&ServerConfig {
        url: SERVER.config.url.clone(),
        api_key: "wrong".into(),
        cert_fingerprint: SERVER.config.cert_fingerprint.clone(),
        cert_pem: SERVER.config.cert_pem.clone(),
    });
    assert!(bad.list_agents().is_err());
}

#[test]
fn port_file_contains_server_port() {
    let port_path = SERVER._tmpdir_path().join(".config/vesta/vestad/port");
    let stored = std::fs::read_to_string(&port_path)
        .expect("port file should exist")
        .trim()
        .parse::<u16>()
        .expect("port file should contain a valid u16");
    assert_eq!(stored, SERVER.port, "port file should match the running server port");
}

#[test]
fn api_key_file_exists_and_nonempty() {
    let key_path = SERVER._tmpdir_path().join(".config/vesta/vestad/api-key");
    let key = std::fs::read_to_string(&key_path)
        .expect("api-key file should exist")
        .trim()
        .to_string();
    assert!(!key.is_empty());
    assert_eq!(key, SERVER.config.api_key);
}

#[test]
fn second_vestad_same_home_rejected() {
    let _ = &*SERVER;

    let vestad = find_vestad().unwrap();
    let output = std::process::Command::new(&vestad)
        .args(["serve", "--standalone", "--no-tunnel"])
        .env("HOME", SERVER._tmpdir_path())
        .env("DOCKER_CONFIG", format!("{}/.docker", std::env::var("HOME").unwrap_or_default()))
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .output()
        .expect("failed to run vestad");

    assert!(
        !output.status.success(),
        "second vestad with same HOME should fail"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("already running"),
        "error should mention 'already running', got: {stderr}"
    );
}
