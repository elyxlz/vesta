use vesta_tests::{TestAgent, SERVER};

const FAKE_TOKEN: &str = r#"{"claudeAiOauth":{"accessToken":"test","refreshToken":"test","expiresAt":4102444800000}}"#;

fn inject_fake_token(c: &vesta_common::client::Client, name: &str) {
    c.inject_token(name, FAKE_TOKEN).unwrap();
}

// ── Health & Auth ──────────────────────────────────────────────

#[test]
fn health() {
    SERVER.client().health().expect("health failed");
}

#[test]
fn wrong_token_rejected() {
    let bad = vesta_common::client::Client::new(&vesta_common::ServerConfig {
        url: SERVER.config.url.clone(),
        api_key: "wrong".into(),
        cert_fingerprint: SERVER.config.cert_fingerprint.clone(),
        cert_pem: SERVER.config.cert_pem.clone(),
    });
    assert!(bad.list_agents().is_err());
}

// ── Agent lifecycle ────────────────────────────────────────────

#[test]
fn create_and_list() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-create-list").unwrap();
    let list = c.list_agents().unwrap();
    assert!(list.iter().any(|a| a.name == agent.name));
}

#[test]
fn create_duplicate_fails() {
    let c = SERVER.client();
    let _agent = TestAgent::create(&c, "test-dup").unwrap();
    let result = c.create_agent("test-dup", false);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.contains("already exists"), "unexpected error: {err}");
}

#[test]
fn status_not_found() {
    let c = SERVER.client();
    let status = c.agent_status("nonexistent-agent-xyz").unwrap();
    assert_eq!(status.status, "not_found");
}

#[test]
fn start_stop_restart() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-start-stop").unwrap();

    c.start_agent(&agent.name).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");

    c.stop_agent(&agent.name).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert_ne!(st.status, "running");

    c.start_agent(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");
}

#[test]
fn destroy_removes_agent() {
    let c = SERVER.client();
    let name = c.create_agent("test-destroy", false).unwrap();
    c.destroy_agent(&name).unwrap();
    let st = c.agent_status(&name).unwrap();
    assert_eq!(st.status, "not_found");
}

#[test]
fn start_nonexistent_fails() {
    assert!(SERVER.client().start_agent("does-not-exist").is_err());
}

#[test]
fn stop_nonexistent_fails() {
    assert!(SERVER.client().stop_agent("does-not-exist").is_err());
}

// ── Name handling ──────────────────────────────────────────────

#[test]
fn name_normalization() {
    let c = SERVER.client();
    let name = c.create_agent("My Test Agent", false).unwrap();
    assert_eq!(name, "my-test-agent");
    let _ = c.destroy_agent(&name);
}

#[test]
fn empty_name_fails() {
    assert!(SERVER.client().create_agent("", false).is_err());
}

#[test]
fn special_chars_name_normalized() {
    assert!(SERVER.client().create_agent("!!!", false).is_err(), "name normalizing to empty should fail");
}

// ── Auth flow ──────────────────────────────────────────────────

#[test]
fn start_auth_returns_url() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-auth-flow").unwrap();
    let auth = c.start_auth(&agent.name).unwrap();
    assert!(!auth.auth_url.is_empty());
    assert!(!auth.session_id.is_empty());
    assert!(auth.auth_url.contains("oauth"));
}

#[test]
fn complete_auth_bad_session_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-auth-bad").unwrap();
    assert!(c.complete_auth(&agent.name, "bogus-session", "bogus-code").is_err());
}

#[test]
fn inject_token_marks_authenticated() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-inject-tok").unwrap();

    inject_fake_token(&c, &agent.name);
    let st = c.agent_status(&agent.name).unwrap();
    assert!(st.authenticated);
}

// ── Backup & Restore ───────────────────────────────────────────

#[test]
fn backup_restore_roundtrip() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup").unwrap();

    let tmp = tempfile::NamedTempFile::new().unwrap();
    let path = tmp.path().to_path_buf();
    c.backup(&agent.name, &path).unwrap();
    assert!(std::fs::metadata(&path).unwrap().len() > 0);

    c.stop_agent(&agent.name).ok();
    c.destroy_agent(&agent.name).unwrap();
    c.restore(&path, Some(&agent.name), false).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_ne!(st.status, "not_found");
}

#[test]
fn restore_conflict_without_replace_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-restore-conflict").unwrap();

    let tmp = tempfile::NamedTempFile::new().unwrap();
    c.backup(&agent.name, tmp.path()).unwrap();

    assert!(c.restore(tmp.path(), Some(&agent.name), false).is_err());
}

// ── WebSocket ──────────────────────────────────────────────────

// ── Rebuild ────────────────────────────────────────────────────

#[test]
fn rebuild_preserves_auth() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-rebuild").unwrap();
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).unwrap();

    c.rebuild_agent(&agent.name).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");
    assert!(st.authenticated);
}

// ── Restore with replace ───────────────────────────────────────

#[test]
fn restore_with_replace() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-restore-replace").unwrap();

    let tmp = tempfile::NamedTempFile::new().unwrap();
    c.backup(&agent.name, tmp.path()).unwrap();

    // Restore over existing — should succeed with replace=true
    c.restore(tmp.path(), Some(&agent.name), true).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert_ne!(st.status, "not_found");
}

#[test]
fn restore_with_different_name() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-restore-src").unwrap();

    let tmp = tempfile::NamedTempFile::new().unwrap();
    c.backup(&agent.name, tmp.path()).unwrap();

    let restored_name = c.restore(tmp.path(), Some("test-restore-dst"), false).unwrap();
    assert_eq!(restored_name, "test-restore-dst");

    let st = c.agent_status("test-restore-dst").unwrap();
    assert_ne!(st.status, "not_found");

    // Cleanup
    let _ = c.destroy_agent("test-restore-dst");
}

// ── Multi-agent ────────────────────────────────────────────────

#[test]
fn multi_agent_unique_ports() {
    let c = SERVER.client();
    let a1 = TestAgent::create(&c, "test-multi-1").unwrap();
    let a2 = TestAgent::create(&c, "test-multi-2").unwrap();
    let a3 = TestAgent::create(&c, "test-multi-3").unwrap();

    let list = c.list_agents().unwrap();
    let ports: Vec<u16> = [&a1.name, &a2.name, &a3.name]
        .iter()
        .filter_map(|n| list.iter().find(|a| &a.name == *n))
        .map(|a| a.ws_port)
        .collect();

    assert_eq!(ports.len(), 3);
    assert_ne!(ports[0], ports[1]);
    assert_ne!(ports[0], ports[2]);
    assert_ne!(ports[1], ports[2]);
}

#[test]
fn start_all_starts_authenticated_agents() {
    let c = SERVER.client();
    let a1 = TestAgent::create(&c, "test-startall-1").unwrap();
    let a2 = TestAgent::create(&c, "test-startall-2").unwrap();
    inject_fake_token(&c, &a1.name);
    inject_fake_token(&c, &a2.name);

    c.start_all().unwrap();

    // Verify our agents specifically are running (other agents from other tests may also be affected)
    assert_eq!(c.agent_status(&a1.name).unwrap().status, "running");
    assert_eq!(c.agent_status(&a2.name).unwrap().status, "running");
}

// ── Destroy auto-stops ─────────────────────────────────────────

#[test]
fn destroy_stops_running_agent() {
    let c = SERVER.client();
    let name = c.create_agent("test-destroy-running", false).unwrap();
    inject_fake_token(&c, &name);
    c.start_agent(&name).unwrap();
    assert_eq!(c.agent_status(&name).unwrap().status, "running");

    c.destroy_agent(&name).unwrap();
    assert_eq!(c.agent_status(&name).unwrap().status, "not_found");
}

// ── Error message content ──────────────────────────────────────

#[test]
fn start_nonexistent_error_message() {
    let err = SERVER.client().start_agent("no-such-agent").unwrap_err();
    assert!(err.contains("not found") || err.contains("not_found"), "error should mention not found: {err}");
}

#[test]
fn destroy_nonexistent_error_message() {
    let err = SERVER.client().destroy_agent("no-such-agent").unwrap_err();
    assert!(err.contains("not found") || err.contains("not_found"), "error should mention not found: {err}");
}

// ── WebSocket ──────────────────────────────────────────────────

#[tokio::test]
async fn ws_connect_to_running_agent() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-ws").unwrap();
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).unwrap();

    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    let ws_url = format!(
        "{}/agents/{}/ws?token={}",
        vesta_common::client::ws_base_url(&SERVER.config.url),
        agent.name,
        SERVER.config.api_key
    );

    let tls = vesta_common::client::make_ws_rustls_config(SERVER.config.cert_fingerprint.clone());
    let connector = tokio_tungstenite::Connector::Rustls(tls);

    let result = tokio_tungstenite::connect_async_tls_with_config(
        &ws_url, None, false, Some(connector),
    ).await;

    match result {
        Ok((ws, _)) => { drop(ws); }
        Err(e) => {
            let err = e.to_string();
            assert!(
                err.contains("503") || err.contains("502"),
                "unexpected WS error (not a proxy issue): {err}"
            );
        }
    }
}

#[tokio::test]
async fn ws_rejected_without_auth() {
    let ws_url = format!(
        "{}/agents/test-ws-noauth/ws",
        vesta_common::client::ws_base_url(&SERVER.config.url),
    );

    let tls = vesta_common::client::make_ws_rustls_config(SERVER.config.cert_fingerprint.clone());
    let connector = tokio_tungstenite::Connector::Rustls(tls);

    let result = tokio_tungstenite::connect_async_tls_with_config(
        &ws_url, None, false, Some(connector),
    ).await;

    assert!(result.is_err(), "WS without auth should be rejected");
}

// ── Server detection ───────────────────────────────────────────

#[test]
fn wait_for_server_port_detects_running() {
    assert!(vesta_common::wait_for_server_port(SERVER.port, 1));
}

#[test]
fn wait_for_server_port_fails_on_closed_port() {
    assert!(!vesta_common::wait_for_server_port(1, 1));
}

// ── ensure_server detection ────────────────────────────────────
// Tests the "server already running, just extract creds" path of ensure_server.
// This is the code path that broke twice (SocketAddr parse panic, migration flow).
// Skips if port 7860 is in use (local dev).

#[test]
fn ensure_server_detects_running_and_saves_config() {
    // Skip if port 7860 is already in use
    if vesta_common::wait_for_server(1) {
        eprintln!("SKIPPED: port 7860 already in use");
        return;
    }

    let tmp = tempfile::TempDir::new().unwrap();
    let home = tmp.path();
    let real_home = std::env::var("HOME").unwrap();

    // Start vestad on port 7860 with HOME in tmpdir
    let vestad = vesta_tests::find_vestad().unwrap();
    let mut child = std::process::Command::new(&vestad)
        .args(["serve", "--port", "7860"])
        .env("HOME", home)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .expect("failed to start vestad");

    // Wait for TCP + credential files to be ready
    assert!(vesta_common::wait_for_server(30), "vestad didn't start on 7860");
    let api_key_path = home.join(".config/vesta/api-key");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    while !api_key_path.exists() {
        assert!(std::time::Instant::now() < deadline, "vestad didn't write api-key");
        std::thread::sleep(std::time::Duration::from_millis(100));
    }

    // Point HOME to tmpdir so ensure_server reads/writes creds there
    std::env::set_var("HOME", home);
    let result = vesta_common::ensure_server();
    std::env::set_var("HOME", &real_home);

    // Verify
    let did_setup = result.expect("ensure_server failed");
    assert!(did_setup, "should have performed setup (config was missing)");

    let config_path = home.join(".config/vesta/server.json");
    assert!(config_path.exists(), "server.json should be created");

    // Idempotent: second call with config + server running
    std::env::set_var("HOME", home);
    let second = vesta_common::ensure_server();
    std::env::set_var("HOME", &real_home);
    assert_eq!(second.unwrap(), false, "second call should be no-op");

    // Cleanup
    let _ = child.kill();
    let _ = child.wait();
}

