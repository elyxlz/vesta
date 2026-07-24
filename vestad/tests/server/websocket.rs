use vesta_tests::{
    agent_container_name, exec_in_container, inject_fake_token, unique_agent, TestAgent, SERVER,
};

fn ws_base_url(url: &str) -> String {
    url.replace("https://", "wss://")
        .replace("http://", "ws://")
}

fn make_ws_rustls_config(fingerprint: Option<String>) -> std::sync::Arc<rustls::ClientConfig> {
    use std::sync::Arc;

    #[derive(Debug)]
    struct AcceptAll {
        expected: Option<String>,
    }

    impl rustls::client::danger::ServerCertVerifier for AcceptAll {
        fn verify_server_cert(
            &self,
            end_entity: &rustls::pki_types::CertificateDer<'_>,
            _: &[rustls::pki_types::CertificateDer<'_>],
            _: &rustls::pki_types::ServerName<'_>,
            _: &[u8],
            _: rustls::pki_types::UnixTime,
        ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
            if let Some(ref expected) = self.expected {
                let digest = ring::digest::digest(&ring::digest::SHA256, end_entity.as_ref());
                let actual = format!(
                    "sha256:{}",
                    digest
                        .as_ref()
                        .iter()
                        .map(|b| format!("{:02X}", b))
                        .collect::<Vec<_>>()
                        .join(":")
                );
                if actual != *expected {
                    return Err(rustls::Error::General("fingerprint mismatch".into()));
                }
            }
            Ok(rustls::client::danger::ServerCertVerified::assertion())
        }
        fn verify_tls12_signature(
            &self,
            _: &[u8],
            _: &rustls::pki_types::CertificateDer<'_>,
            _: &rustls::DigitallySignedStruct,
        ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
            Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
        }
        fn verify_tls13_signature(
            &self,
            _: &[u8],
            _: &rustls::pki_types::CertificateDer<'_>,
            _: &rustls::DigitallySignedStruct,
        ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
            Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
        }
        fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
            rustls::crypto::ring::default_provider()
                .signature_verification_algorithms
                .supported_schemes()
        }
    }

    let _ = rustls::crypto::ring::default_provider().install_default();
    Arc::new(
        rustls::ClientConfig::builder()
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(AcceptAll {
                expected: fingerprint,
            }))
            .with_no_client_auth(),
    )
}

const WS_AGENT_RUNNING_TIMEOUT_SECS: u64 = 60;

async fn ws_connect(url: &str) -> Result<(), tokio_tungstenite::tungstenite::Error> {
    let tls = make_ws_rustls_config(SERVER.config.cert_fingerprint.clone());
    let connector = tokio_tungstenite::Connector::Rustls(tls);
    tokio_tungstenite::connect_async_tls_with_config(url, None, false, Some(connector))
        .await
        .map(|(ws, _)| drop(ws))
}

/// The raw agent event bus is no longer client-exposed: a WS upgrade to `/agents/{name}/ws`
/// (no registered service) is rejected with 404, while a registered-service WS still upgrades.
#[tokio::test]
async fn raw_bus_ws_rejected_but_registered_service_ws_upgrades() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("ws")).unwrap();
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).unwrap();
    // The WS handler runs ensure_running() before the service guard, so the container must be up
    // for a raw-port upgrade to reach (and be rejected by) that guard rather than a docker error.
    c.wait_until_running(&agent.name, WS_AGENT_RUNNING_TIMEOUT_SECS)
        .unwrap();

    // Register a service so the service plane has a live route to upgrade against.
    let cname = agent_container_name(&agent.name);
    exec_in_container(
        &cname,
        ". /run/vestad-env && curl -fsSk -X POST -H \"X-Agent-Token: $AGENT_TOKEN\" \
         -H 'Content-Type: application/json' -d '{\"name\":\"probe\"}' \
         \"https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services\"",
    )
    .expect("register probe service");

    // A registered-service WS upgrades: the proxy completes the 101 handshake before touching
    // the (here dead) upstream, so a successful upgrade proves the service plane is intact.
    let service_url = format!(
        "{}/agents/{}/probe?token={}",
        ws_base_url(&SERVER.config.url),
        agent.name,
        SERVER.config.api_key
    );
    ws_connect(&service_url)
        .await
        .expect("registered-service WS should still upgrade");

    // The raw event-bus port is rejected before any upgrade.
    let raw_url = format!(
        "{}/agents/{}/ws?token={}",
        ws_base_url(&SERVER.config.url),
        agent.name,
        SERVER.config.api_key
    );
    let err = ws_connect(&raw_url)
        .await
        .expect_err("raw event-bus WS must be rejected")
        .to_string();
    assert!(
        err.contains("404"),
        "raw event-bus WS should be rejected with 404, got: {err}"
    );

    // Auth runs on the proxy WS path: the same route without a token is rejected. The service-WS
    // auth path shares this handler, so this covers registered-service auth too.
    let noauth_url = format!("{}/agents/{}/ws", ws_base_url(&SERVER.config.url), agent.name);
    let noauth_err = ws_connect(&noauth_url)
        .await
        .expect_err("WS without auth must be rejected")
        .to_string();
    assert!(
        noauth_err.contains("401"),
        "unauthenticated WS should be rejected with 401, got: {noauth_err}"
    );
}
