#[macro_use]
mod harness;
use harness::TestAgent;

// ── Health & Auth ──────────────────────────────────────────────

#[test]
fn health() {
    let s = server!();
    s.client().health().expect("health failed");
}

#[test]
fn wrong_token_rejected() {
    let s = server!();
    let bad = vesta_common::client::Client::new(&vesta_common::ServerConfig {
        url: s.config.url.clone(),
        api_key: "wrong".into(),
        cert_fingerprint: s.config.cert_fingerprint.clone(),
        cert_pem: s.config.cert_pem.clone(),
    });
    assert!(bad.list_agents().is_err());
}

// ── Agent lifecycle ────────────────────────────────────────────

#[test]
fn create_and_list() {
    let s = server!();
    let c = s.client();
    let agent = TestAgent::create(&c, "test-create-list").unwrap();
    let list = c.list_agents().unwrap();
    assert!(list.iter().any(|a| a.name == agent.name));
}

#[test]
fn create_duplicate_fails() {
    let s = server!();
    let c = s.client();
    let _agent = TestAgent::create(&c, "test-dup").unwrap();
    let result = c.create_agent("test-dup", false);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.contains("already exists"), "unexpected error: {err}");
}

#[test]
fn status_not_found() {
    let s = server!();
    let c = s.client();
    let status = c.agent_status("nonexistent-agent-xyz").unwrap();
    assert_eq!(status.status, "not_found");
}

#[test]
fn start_stop_restart() {
    let s = server!();
    let c = s.client();
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
    let s = server!();
    let c = s.client();
    let name = c.create_agent("test-destroy", false).unwrap();
    c.destroy_agent(&name).unwrap();
    let st = c.agent_status(&name).unwrap();
    assert_eq!(st.status, "not_found");
}

#[test]
fn start_nonexistent_fails() {
    let s = server!();
    assert!(s.client().start_agent("does-not-exist").is_err());
}

#[test]
fn stop_nonexistent_fails() {
    let s = server!();
    assert!(s.client().stop_agent("does-not-exist").is_err());
}

// ── Name handling ──────────────────────────────────────────────

#[test]
fn name_normalization() {
    let s = server!();
    let c = s.client();
    let name = c.create_agent("My Test Agent", false).unwrap();
    assert_eq!(name, "my-test-agent");
    let _ = c.destroy_agent(&name);
}

#[test]
fn empty_name_fails() {
    let s = server!();
    assert!(s.client().create_agent("", false).is_err());
}

#[test]
fn special_chars_name_normalized() {
    let s = server!();
    assert!(s.client().create_agent("!!!", false).is_err(), "name normalizing to empty should fail");
}

// ── Auth flow ──────────────────────────────────────────────────

#[test]
fn start_auth_returns_url() {
    let s = server!();
    let c = s.client();
    let agent = TestAgent::create(&c, "test-auth-flow").unwrap();
    let auth = c.start_auth(&agent.name).unwrap();
    assert!(!auth.auth_url.is_empty());
    assert!(!auth.session_id.is_empty());
    assert!(auth.auth_url.contains("oauth"));
}

#[test]
fn complete_auth_bad_session_fails() {
    let s = server!();
    let c = s.client();
    let agent = TestAgent::create(&c, "test-auth-bad").unwrap();
    let result = c.complete_auth(&agent.name, "bogus-session", "bogus-code");
    assert!(result.is_err());
}

#[test]
fn inject_token_marks_authenticated() {
    let s = server!();
    let c = s.client();
    let agent = TestAgent::create(&c, "test-inject-tok").unwrap();

    let token = serde_json::json!({
        "claudeAiOauth": {
            "accessToken": "test",
            "refreshToken": "test",
            "expiresAt": 4102444800000_u64
        }
    });
    c.inject_token(&agent.name, &token.to_string()).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert!(st.authenticated);
}

// ── Backup & Restore ───────────────────────────────────────────

#[test]
fn backup_restore_roundtrip() {
    let s = server!();
    let c = s.client();
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
    let s = server!();
    let c = s.client();
    let agent = TestAgent::create(&c, "test-restore-conflict").unwrap();

    let tmp = tempfile::NamedTempFile::new().unwrap();
    c.backup(&agent.name, tmp.path()).unwrap();

    let result = c.restore(tmp.path(), Some(&agent.name), false);
    assert!(result.is_err());
}

// ── WebSocket ──────────────────────────────────────────────────

#[tokio::test]
async fn ws_connect_to_running_agent() {
    let s = match harness::SERVER.as_ref() {
        Some(s) => s,
        None => { eprintln!("SKIPPED: vestad not available"); return; }
    };
    let c = s.client();
    let agent = TestAgent::create(&c, "test-ws").unwrap();

    let token = serde_json::json!({
        "claudeAiOauth": {
            "accessToken": "test",
            "refreshToken": "test",
            "expiresAt": 4102444800000_u64
        }
    });
    c.inject_token(&agent.name, &token.to_string()).unwrap();
    c.start_agent(&agent.name).unwrap();

    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    let ws_url = format!(
        "{}/agents/{}/ws?token={}",
        vesta_common::client::ws_base_url(&s.config.url),
        agent.name,
        s.config.api_key
    );

    let tls = vesta_common::client::make_ws_rustls_config(s.config.cert_fingerprint.clone());
    let connector = tokio_tungstenite::Connector::Rustls(tls);

    let result = tokio_tungstenite::connect_async_tls_with_config(
        &ws_url,
        None,
        false,
        Some(connector),
    )
    .await;

    match result {
        Ok((ws, _)) => {
            drop(ws);
        }
        Err(e) => {
            let err = e.to_string();
            assert!(
                err.contains("503") || err.contains("502"),
                "unexpected WS error (not a proxy issue): {err}"
            );
        }
    }
}
