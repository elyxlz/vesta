use vesta_tests::{TestAgent, SERVER};
use vesta_tests::client::Client;
use vesta_tests::types::{BackupType, ServerConfig};

const FAKE_TOKEN: &str = r#"{"claudeAiOauth":{"accessToken":"test","refreshToken":"test","expiresAt":4102444800000}}"#;

fn inject_fake_token(c: &Client, name: &str) {
    c.inject_token(name, FAKE_TOKEN).unwrap();
}

// ── Helper: WS URL ────────────────────────────────────────────

fn ws_base_url(url: &str) -> String {
    url.replace("https://", "wss://").replace("http://", "ws://")
}

fn make_ws_rustls_config(fingerprint: Option<String>) -> std::sync::Arc<rustls::ClientConfig> {
    use std::sync::Arc;

    #[derive(Debug)]
    struct AcceptAll { expected: Option<String> }

    impl rustls::client::danger::ServerCertVerifier for AcceptAll {
        fn verify_server_cert(&self, end_entity: &rustls::pki_types::CertificateDer<'_>, _: &[rustls::pki_types::CertificateDer<'_>], _: &rustls::pki_types::ServerName<'_>, _: &[u8], _: rustls::pki_types::UnixTime) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
            if let Some(ref expected) = self.expected {
                let digest = ring::digest::digest(&ring::digest::SHA256, end_entity.as_ref());
                let actual = format!("sha256:{}", digest.as_ref().iter().map(|b| format!("{:02X}", b)).collect::<Vec<_>>().join(":"));
                if actual != *expected {
                    return Err(rustls::Error::General("fingerprint mismatch".into()));
                }
            }
            Ok(rustls::client::danger::ServerCertVerified::assertion())
        }
        fn verify_tls12_signature(&self, _: &[u8], _: &rustls::pki_types::CertificateDer<'_>, _: &rustls::DigitallySignedStruct) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
            Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
        }
        fn verify_tls13_signature(&self, _: &[u8], _: &rustls::pki_types::CertificateDer<'_>, _: &rustls::DigitallySignedStruct) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
            Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
        }
        fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
            rustls::crypto::ring::default_provider().signature_verification_algorithms.supported_schemes()
        }
    }

    let _ = rustls::crypto::ring::default_provider().install_default();
    Arc::new(rustls::ClientConfig::builder().dangerous().with_custom_certificate_verifier(Arc::new(AcceptAll { expected: fingerprint })).with_no_client_auth())
}

// ── Health & Auth ──────────────────────────────────────────────

#[test]
fn health() {
    SERVER.client().health().expect("health failed");
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
fn backup_create() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-create").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    assert_eq!(backup.agent_name, agent.name);
    assert_eq!(backup.backup_type, BackupType::Manual);
    assert!(backup.size > 0);
    assert!(!backup.id.is_empty());

    c.delete_backup(&agent.name, &backup.id).ok();
}

#[test]
fn backup_list() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-list").unwrap();

    let b1 = c.create_backup(&agent.name).unwrap();
    let b2 = c.create_backup(&agent.name).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(backups.len() >= 2);
    assert!(backups[0].created_at >= backups[1].created_at);

    c.delete_backup(&agent.name, &b1.id).ok();
    c.delete_backup(&agent.name, &b2.id).ok();
}

#[test]
fn backup_list_empty() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-empty").unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(backups.is_empty());
    drop(agent);
}

#[test]
fn backup_restore() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-restore").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.restore_backup(&agent.name, &backup.id).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");

    let backups = c.list_backups(&agent.name).unwrap();
    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

#[test]
fn backup_restore_creates_safety_snapshot() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-safety").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.restore_backup(&agent.name, &backup.id).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    let pre_restore = backups
        .iter()
        .find(|b| b.backup_type == BackupType::PreRestore);
    assert!(pre_restore.is_some(), "expected a pre-restore safety backup");

    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

#[test]
fn backup_delete() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-delete").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.delete_backup(&agent.name, &backup.id).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(!backups.iter().any(|b| b.id == backup.id));
}

#[test]
fn backup_delete_nonexistent_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-del-bad").unwrap();

    let result = c.delete_backup(&agent.name, "vesta-backup:fake-manual-20260101-000000");
    assert!(result.is_err());
    drop(agent);
}

#[test]
fn backup_restore_nonexistent_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-res-bad").unwrap();

    let result = c.restore_backup(&agent.name, "vesta-backup:fake-manual-20260101-000000");
    assert!(result.is_err());
    drop(agent);
}

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

// ── Creation flow ─────────────────────────────────────────────

#[test]
fn create_auto_starts() {
    // POST /agents now auto-starts the agent.
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-create-autostart").unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");
}

#[test]
fn creation_flow() {
    // Mirrors the app's NewAgent creation flow:
    //   create (auto-starts) → authenticate → complete_auth (auto-restarts + waits)
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-creation-flow").unwrap();

    // Agent is auto-started by create, no separate start needed
    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");
    assert!(!st.authenticated);

    // Simulate OAuth: inject token then restart + wait (as complete_auth would)
    inject_fake_token(&c, &agent.name);
    assert!(c.agent_status(&agent.name).unwrap().authenticated);

    c.restart_agent(&agent.name).unwrap();
    c.wait_ready(&agent.name, 60).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "running");
    assert!(st.authenticated);
    assert!(st.agent_ready);
}

#[tokio::test]
async fn ws_connect_to_running_agent() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-ws").unwrap();
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).unwrap();

    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    let ws_url = format!(
        "{}/agents/{}/ws?token={}",
        ws_base_url(&SERVER.config.url),
        agent.name,
        SERVER.config.api_key
    );

    let tls = make_ws_rustls_config(SERVER.config.cert_fingerprint.clone());
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
        ws_base_url(&SERVER.config.url),
    );

    let tls = make_ws_rustls_config(SERVER.config.cert_fingerprint.clone());
    let connector = tokio_tungstenite::Connector::Rustls(tls);

    let result = tokio_tungstenite::connect_async_tls_with_config(
        &ws_url, None, false, Some(connector),
    ).await;

    assert!(result.is_err(), "WS without auth should be rejected");
}
