use std::sync::Arc;
use ureq::http::Response;
use ureq::Body;

use crate::{AuthFlowResponse, ListEntry, ServerConfig, StartAllResult, StatusJson};

// ── TLS fingerprint verification ────────────────────────────────

fn make_rustls_config(fingerprint: Option<String>) -> Arc<rustls::ClientConfig> {
    Arc::new(
        rustls::ClientConfig::builder()
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(FingerprintVerifier {
                expected: fingerprint,
            }))
            .with_no_client_auth(),
    )
}

/// TLS cert verifier that checks SHA-256 fingerprint instead of CA chain.
/// Falls back to accepting any cert if no fingerprint is configured.
#[derive(Debug)]
struct FingerprintVerifier {
    expected: Option<String>,
}

impl rustls::client::danger::ServerCertVerifier for FingerprintVerifier {
    fn verify_server_cert(
        &self,
        end_entity: &rustls::pki_types::CertificateDer<'_>,
        _intermediates: &[rustls::pki_types::CertificateDer<'_>],
        _server_name: &rustls::pki_types::ServerName<'_>,
        _ocsp_response: &[u8],
        _now: rustls::pki_types::UnixTime,
    ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
        let Some(expected) = &self.expected else {
            return Ok(rustls::client::danger::ServerCertVerified::assertion());
        };

        let actual = cert_fingerprint(end_entity.as_ref());

        if actual == *expected {
            Ok(rustls::client::danger::ServerCertVerified::assertion())
        } else {
            Err(rustls::Error::General(format!(
                "certificate fingerprint mismatch: expected {}, got {}",
                expected, actual
            )))
        }
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

fn cert_fingerprint(der: &[u8]) -> String {
    let digest = ring::digest::digest(&ring::digest::SHA256, der);
    format!(
        "sha256:{}",
        digest
            .as_ref()
            .iter()
            .map(|b| format!("{:02X}", b))
            .collect::<Vec<_>>()
            .join(":")
    )
}

// ── Rustls config for WebSocket (CLI chat) ──────────────────────

pub fn make_ws_rustls_config(fingerprint: Option<String>) -> Arc<rustls::ClientConfig> {
    make_rustls_config(fingerprint)
}

// ── HTTP client ─────────────────────────────────────────────────

#[derive(serde::Deserialize)]
struct StartAllResponse {
    results: Vec<StartAllResult>,
}

fn check_response(resp: Response<Body>) -> Result<Response<Body>, String> {
    let status = resp.status().as_u16();
    if (200..300).contains(&status) {
        return Ok(resp);
    }

    let error_msg = resp
        .into_body()
        .read_to_string()
        .ok()
        .and_then(|body| extract_server_error(&body));

    match status {
        401 => Err("invalid API key".into()),
        404 => Err(error_msg.unwrap_or_else(|| "not found".into())),
        409 => Err(error_msg.unwrap_or_else(|| "conflict".into())),
        503 => Err(error_msg.unwrap_or_else(|| "agent not running".into())),
        _ => Err(error_msg.unwrap_or_else(|| format!("server error ({})", status))),
    }
}

fn map_error(e: ureq::Error) -> String {
    match e {
        ureq::Error::ConnectionFailed | ureq::Error::Io(_) => {
            "server not running. run: vesta boot".into()
        }
        other => format!("request failed: {}", other),
    }
}

pub fn extract_server_error(body: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    v["error"].as_str().map(|s| s.to_string())
}

pub struct Client {
    agent: ureq::Agent,
    base_url: String,
    api_key: String,
    cert_fingerprint: Option<String>,
}

impl Client {
    pub fn new(config: &ServerConfig) -> Self {
        let tls_config = if let Some(ref pem) = config.cert_pem {
            let cert = ureq::tls::Certificate::from_pem(pem.as_bytes())
                .expect("invalid cert PEM in server config");
            ureq::tls::TlsConfig::builder()
                .root_certs(ureq::tls::RootCerts::Specific(Arc::new(vec![cert])))
                .build()
        } else {
            ureq::tls::TlsConfig::builder().build()
        };
        let agent = ureq::Agent::config_builder()
            .http_status_as_error(false)
            .tls_config(tls_config)
            .build()
            .new_agent();
        Self {
            agent,
            base_url: config.url.clone(),
            api_key: config.api_key.clone(),
            cert_fingerprint: config.cert_fingerprint.clone(),
        }
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    pub fn api_key(&self) -> &str {
        &self.api_key
    }

    pub fn cert_fingerprint(&self) -> Option<&str> {
        self.cert_fingerprint.as_deref()
    }

    fn get(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .get(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
            .map_err(map_error)?;
        check_response(resp)
    }

    fn post(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_empty()
            .map_err(map_error)?;
        check_response(resp)
    }

    fn post_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(map_error)?;
        check_response(resp)
    }

    pub fn health(&self) -> Result<(), String> {
        let resp = self
            .agent
            .get(&format!("{}/health", self.base_url))
            .call()
            .map_err(map_error)?;
        check_response(resp)?;
        Ok(())
    }

    pub fn list_agents(&self) -> Result<Vec<ListEntry>, String> {
        let resp = self.get("/agents")?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn agent_status(&self, name: &str) -> Result<StatusJson, String> {
        let resp = self.get(&format!("/agents/{}", name))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn create_agent(&self, name: &str, build: bool) -> Result<String, String> {
        let body = serde_json::json!({"name": name, "build": build});
        let resp = self.post_json("/agents", &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    pub fn start_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/start", name))?;
        Ok(())
    }

    pub fn start_all(&self) -> Result<Vec<StartAllResult>, String> {
        let resp = self.post("/agents/start")?;
        let v: StartAllResponse = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))?;
        Ok(v.results)
    }

    pub fn stop_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/stop", name))?;
        Ok(())
    }

    pub fn restart_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/restart", name))?;
        Ok(())
    }

    pub fn destroy_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/destroy", name))?;
        Ok(())
    }

    pub fn rebuild_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/rebuild", name))?;
        Ok(())
    }

    pub fn wait_ready(&self, name: &str, timeout: u64) -> Result<(), String> {
        self.get(&format!(
            "/agents/{}/wait-ready?timeout={}",
            name, timeout
        ))?;
        Ok(())
    }

    pub fn start_auth(&self, name: &str) -> Result<AuthFlowResponse, String> {
        let resp = self.post(&format!("/agents/{}/auth", name))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn complete_auth(&self, name: &str, session_id: &str, code: &str) -> Result<(), String> {
        let body = serde_json::json!({"session_id": session_id, "code": code});
        self.post_json(&format!("/agents/{}/auth/code", name), &body)?;
        Ok(())
    }

    pub fn inject_token(&self, name: &str, token: &str) -> Result<(), String> {
        let token_value: serde_json::Value =
            serde_json::from_str(token).map_err(|e| format!("invalid token JSON: {}", e))?;
        let body = serde_json::json!({"token": token_value});
        self.post_json(&format!("/agents/{}/auth/token", name), &body)?;
        Ok(())
    }

    pub fn backup(&self, name: &str, output: &std::path::Path) -> Result<(), String> {
        let resp = self.post(&format!("/agents/{}/backup", name))?;
        let mut file = std::fs::File::create(output)
            .map_err(|e| format!("failed to create {}: {}", output.display(), e))?;
        let mut reader = resp.into_body().into_reader();
        std::io::copy(&mut reader, &mut file)
            .map_err(|e| format!("failed to write backup: {}", e))?;
        Ok(())
    }

    pub fn restore(
        &self,
        input: &std::path::Path,
        name: Option<&str>,
        replace: bool,
    ) -> Result<String, String> {
        let data = std::fs::read(input)
            .map_err(|e| format!("failed to read {}: {}", input.display(), e))?;

        let mut query = String::new();
        if let Some(n) = name {
            query.push_str(&format!("name={}", n));
        }
        if replace {
            if !query.is_empty() {
                query.push('&');
            }
            query.push_str("replace=true");
        }
        let url = if query.is_empty() {
            format!("{}/agents/restore", self.base_url)
        } else {
            format!("{}/agents/restore?{}", self.base_url, query)
        };

        let resp = self
            .agent
            .post(&url)
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/gzip")
            .send(data.as_slice())
            .map_err(map_error)?;
        let resp = check_response(resp)?;

        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))?;
        Ok(v["name"].as_str().unwrap_or("unknown").to_string())
    }

    /// Connect to SSE logs endpoint and print lines to stdout.
    pub fn stream_logs(&self, name: &str) -> Result<(), String> {
        let resp = self.get(&format!("/agents/{}/logs", name))?;
        let reader = std::io::BufReader::new(resp.into_body().into_reader());
        for line in std::io::BufRead::lines(reader) {
            let line = line.map_err(|e| format!("read error: {}", e))?;
            if let Some(data) = line.strip_prefix("data:") {
                println!("{}", data.trim_start());
            } else if line.starts_with("event:agent_stopped") {
                eprintln!("agent stopped");
                break;
            }
        }
        Ok(())
    }
}
