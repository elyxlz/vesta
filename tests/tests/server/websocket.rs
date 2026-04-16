use vesta_tests::{TestAgent, SERVER, inject_fake_token, unique_agent};

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

#[tokio::test]
async fn ws_connect_to_running_agent() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("ws")).unwrap();
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
        "{}/agents/{}/ws",
        ws_base_url(&SERVER.config.url),
        unique_agent("ws-noauth"),
    );

    let tls = make_ws_rustls_config(SERVER.config.cert_fingerprint.clone());
    let connector = tokio_tungstenite::Connector::Rustls(tls);

    let result = tokio_tungstenite::connect_async_tls_with_config(
        &ws_url, None, false, Some(connector),
    ).await;

    assert!(result.is_err(), "WS without auth should be rejected");
}
