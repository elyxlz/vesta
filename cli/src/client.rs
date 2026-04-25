use std::io::{BufRead, IsTerminal, Write};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use ureq::http::Response;
use ureq::Body;

use crate::common::{
    AuthFlowResponse, BackupInfo, ListEntry, ServerConfig, StartAllResult, StatusJson,
};

// ── TLS fingerprint verification ────────────────────────────────

fn make_rustls_config(fingerprint: Option<String>) -> Arc<rustls::ClientConfig> {
    let _ = rustls::crypto::ring::default_provider().install_default();
    Arc::new(
        rustls::ClientConfig::builder()
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(FingerprintVerifier {
                expected: fingerprint,
            }))
            .with_no_client_auth(),
    )
}

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

pub fn make_ws_rustls_config(fingerprint: Option<String>) -> Arc<rustls::ClientConfig> {
    make_rustls_config(fingerprint)
}

fn ws_base_url(url: &str) -> String {
    url.replace("https://", "wss://")
        .replace("http://", "ws://")
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
        503 => Err(error_msg.unwrap_or_else(|| "vestad is not reachable — is it running?".into())),
        _ => Err(error_msg.unwrap_or_else(|| format!("server error ({})", status))),
    }
}

fn map_error(e: ureq::Error) -> String {
    match e {
        ureq::Error::ConnectionFailed | ureq::Error::Io(_) => {
            "server not reachable. check your connection.".into()
        }
        other => format!("request failed: {}", other),
    }
}

fn extract_server_error(body: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    v["error"].as_str().map(|s| s.to_string())
}

fn urlencod(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 3);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                out.push('%');
                out.push(char::from(b"0123456789ABCDEF"[(b >> 4) as usize]));
                out.push(char::from(b"0123456789ABCDEF"[(b & 0xf) as usize]));
            }
        }
    }
    out
}

/// Read an SSE stream, returning the data from the "done" event or an error.
/// SSE keepalive comments are silently ignored.
fn read_sse_result(resp: Response<Body>) -> Result<String, String> {
    let reader = std::io::BufReader::new(resp.into_body().into_reader());
    let mut event_type = String::new();
    let mut data = String::new();

    for line in BufRead::lines(reader) {
        let line = line.map_err(|e| format!("read error: {}", e))?;

        if let Some(ev) = line.strip_prefix("event:") {
            event_type = ev.trim().to_string();
        } else if let Some(d) = line.strip_prefix("data:") {
            data = d.trim().to_string();
        } else if line.is_empty() && !event_type.is_empty() {
            match event_type.as_str() {
                "done" => return Ok(data),
                "error" => {
                    let msg = serde_json::from_str::<serde_json::Value>(&data)
                        .ok()
                        .and_then(|v| {
                            v["error"]["message"]
                                .as_str()
                                .or(v["error"].as_str())
                                .map(|s| s.to_string())
                        })
                        .unwrap_or(data);
                    return Err(msg);
                }
                _ => {}
            }
            event_type.clear();
            data.clear();
        }
    }

    Err("server closed connection before completing".into())
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

    fn delete_req(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .delete(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
            .map_err(map_error)?;
        check_response(resp)
    }

    fn patch_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .patch(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(map_error)?;
        check_response(resp)
    }

    fn put_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .put(&format!("{}{}", self.base_url, path))
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

    pub fn create_agent(&self, name: &str, manage_agent_code: bool, timezone: Option<&str>) -> Result<String, String> {
        let mut body = serde_json::json!({"name": name, "manage_agent_code": manage_agent_code});
        if let Some(tz) = timezone {
            body["timezone"] = serde_json::json!(tz);
        }
        let resp = self.post_json("/agents", &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    pub fn get_agent_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.get(&format!("/agents/{}/settings", name))?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    pub fn patch_agent_settings(&self, name: &str, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        let resp = self.patch_json(&format!("/agents/{}/settings", name), body)?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
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

    pub fn restart_gateway(&self) -> Result<(), String> {
        self.post("/gateway/restart")?;
        Ok(())
    }

    pub fn stream_gateway_logs(&self, tail: u64, follow: bool) -> Result<(), String> {
        let resp = self.get(&format!("/gateway/logs?tail={}&follow={}", tail, follow))?;
        consume_sse_log_stream(resp, "gateway_stopped", None)
    }

    pub fn destroy_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/destroy", name))?;
        Ok(())
    }

    pub fn rebuild_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/rebuild", name))?;
        Ok(())
    }

    /// Poll `/agents/{name}` until `status == "alive"` or the deadline passes.
    /// Terminal non-alive states (not_found, dead, stopped, not_authenticated)
    /// surface as immediate errors — the agent cannot become ready from those.
    pub fn wait_until_alive(&self, name: &str, timeout: Duration) -> Result<(), String> {
        let deadline = Instant::now() + timeout;
        let mut backoff = Duration::from_millis(200);
        loop {
            let status = self.agent_status(name)?;
            match status.status.as_str() {
                "alive" => return Ok(()),
                "not_found" | "dead" | "stopped" | "not_authenticated" =>
                    return Err(format!("{}: {}", name, status.status)),
                _ => {}
            }
            if Instant::now() >= deadline {
                return Err(format!("{}: timeout waiting for ready (status: {})", name, status.status));
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(Duration::from_secs(1));
        }
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

    pub fn create_backup(&self, name: &str) -> Result<BackupInfo, String> {
        let resp = self.post(&format!("/agents/{}/backups", name))?;
        let data = read_sse_result(resp)?;
        serde_json::from_str(&data).map_err(|e| format!("parse error: {}", e))
    }

    pub fn list_backups(&self, name: &str) -> Result<Vec<BackupInfo>, String> {
        let resp = self.get(&format!("/agents/{}/backups", name))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn restore_backup(&self, name: &str, backup_id: &str) -> Result<(), String> {
        let resp = self.post(&format!(
            "/agents/{}/backups/{}/restore",
            name,
            urlencod(backup_id)
        ))?;
        read_sse_result(resp)?;
        Ok(())
    }

    pub fn delete_backup(&self, name: &str, backup_id: &str) -> Result<(), String> {
        self.delete_req(&format!("/agents/{}/backups/{}", name, urlencod(backup_id)))?;
        Ok(())
    }

    pub fn get_auto_backup_settings(&self) -> Result<serde_json::Value, String> {
        let resp = self.get("/settings/auto-backup")?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn set_auto_backup_settings(&self, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        let resp = self.put_json("/settings/auto-backup", body)?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn list_all_backups(&self) -> Result<Vec<BackupInfo>, String> {
        let resp = self.get("/backups")?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn get_agent_backup_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.get(&format!("/agents/{}/settings/backup", name))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn set_agent_backup_settings(&self, name: &str, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        let resp = self.put_json(&format!("/agents/{}/settings/backup", name), body)?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn delete_agent_backup_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.delete_req(&format!("/agents/{}/settings/backup", name))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn stream_logs(&self, name: &str, tail: u64) -> Result<(), String> {
        let resp = self.get(&format!("/agents/{}/logs?tail={}", name, tail))?;
        consume_sse_log_stream(resp, "agent_stopped", Some("agent stopped"))
    }
}

fn consume_sse_log_stream(
    resp: Response<Body>,
    stop_event: &str,
    stop_message: Option<&str>,
) -> Result<(), String> {
    let reader = std::io::BufReader::new(resp.into_body().into_reader());
    let stop_marker = format!("event:{stop_event}");
    for line in std::io::BufRead::lines(reader) {
        let line = line.map_err(|e| format!("read error: {}", e))?;
        if let Some(data) = line.strip_prefix("data:") {
            println!("{}", data.trim_start());
        } else if line.starts_with(&stop_marker) {
            if let Some(msg) = stop_message {
                eprintln!("{msg}");
            }
            break;
        }
    }
    Ok(())
}

// ── WebSocket chat (CLI-only) ──────────────────────────────────

const CHAT_READ_TIMEOUT_MS: u64 = 100;

const ANSI_RESET: &str = "\x1b[0m";
const ANSI_TS: &str = "\x1b[90m";
const ANSI_YOU: &str = "\x1b[1;36m";
const ANSI_AGENT: &str = "\x1b[1;35m";

fn time_from_ts(ts: &str) -> String {
    if ts.len() >= 16 && ts.is_char_boundary(11) && ts.is_char_boundary(16) {
        ts[11..16].to_string()
    } else {
        ts.to_string()
    }
}

fn time_now_utc() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{:02}:{:02}", (secs / 3600) % 24, (secs / 60) % 60)
}

fn render_line(time: &str, nick: &str, nick_color: &str, text: &str, color: bool) {
    if color {
        println!(
            "{ts_c}[{time}]{r} {nc}<{nick}>{r} {text}",
            ts_c = ANSI_TS,
            r = ANSI_RESET,
            nc = nick_color,
        );
    } else {
        println!("[{}] <{}> {}", time, nick, text);
    }
}

/// Connect to Chat WebSocket and run interactive chat (CLI-only).
pub fn chat(client: &Client, name: &str) -> Result<(), String> {
    let url = format!(
        "{}/agents/{}/ws?token={}",
        ws_base_url(&client.base_url),
        name,
        client.api_key()
    );

    let parsed: url::Url =
        url.parse().map_err(|e| format!("invalid ws url: {}", e))?;
    let host = parsed.host_str().unwrap_or("localhost");
    let port = parsed.port_or_known_default().unwrap_or(443);
    let tcp = std::net::TcpStream::connect((host, port))
        .map_err(|e| format!("ws tcp connect failed: {}", e))?;
    tcp.set_read_timeout(Some(std::time::Duration::from_millis(CHAT_READ_TIMEOUT_MS)))
        .map_err(|e| format!("failed to set read timeout: {}", e))?;
    let connector =
        tungstenite::Connector::Rustls(make_ws_rustls_config(client.cert_fingerprint().map(|s| s.to_string())));
    let (mut socket, _) =
        tungstenite::client_tls_with_config(url, tcp, None, Some(connector))
            .map_err(|e| format!("ws connect failed: {}", e))?;

    let color = std::io::stdout().is_terminal();

    eprintln!("connected to {}. type a message and press enter.", name);

    let (tx, rx) = std::sync::mpsc::channel::<String>();

    let _stdin_handle = std::thread::spawn(move || {
        let stdin = std::io::stdin();
        let mut line = String::new();
        loop {
            line.clear();
            match stdin.lock().read_line(&mut line) {
                Ok(0) => break,
                Ok(_) => {
                    if tx.send(line.trim().to_string()).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });

    loop {
        if let Ok(input) = rx.try_recv() {
            if !input.is_empty() {
                if color {
                    print!("\x1b[1A\x1b[2K\r");
                }
                render_line(&time_now_utc(), "you", ANSI_YOU, &input, color);
                std::io::stdout().flush().ok();
                let msg = serde_json::json!({"type": "message", "text": input});
                if socket
                    .send(tungstenite::Message::Text(msg.to_string().into()))
                    .is_err()
                {
                    break;
                }
            }
        }

        match socket.read() {
            Ok(tungstenite::Message::Text(text)) => {
                if let Ok(msg) = serde_json::from_str::<serde_json::Value>(text.as_ref()) {
                    match msg["type"].as_str() {
                        Some("chat") => {
                            if let Some(content) = msg["text"].as_str() {
                                let time = time_from_ts(msg["ts"].as_str().unwrap_or(""));
                                render_line(&time, name, ANSI_AGENT, content.trim_end(), color);
                                std::io::stdout().flush().ok();
                            }
                        }
                        Some("history") => {
                            if let Some(events) = msg["events"].as_array() {
                                for event in events {
                                    let event_type = event["type"].as_str().unwrap_or("");
                                    let time = time_from_ts(event["ts"].as_str().unwrap_or(""));
                                    if event_type == "user" {
                                        if let Some(content) = event["text"].as_str() {
                                            render_line(&time, "you", ANSI_YOU, content.trim_end(), color);
                                        }
                                    } else if event_type == "chat" {
                                        if let Some(content) = event["text"].as_str() {
                                            render_line(&time, name, ANSI_AGENT, content.trim_end(), color);
                                        }
                                    }
                                }
                                std::io::stdout().flush().ok();
                            }
                        }
                        _ => {}
                    }
                }
            }
            Ok(tungstenite::Message::Close(_)) | Err(tungstenite::Error::ConnectionClosed) => break,
            Ok(_) => {}
            Err(tungstenite::Error::Io(ref e))
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(_) => break,
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ws_base_url_converts_schemes() {
        assert_eq!(ws_base_url("https://example.com"), "wss://example.com");
        assert_eq!(ws_base_url("http://localhost:8080"), "ws://localhost:8080");
        assert_eq!(ws_base_url("http://127.0.0.1:9001"), "ws://127.0.0.1:9001");
    }

    #[test]
    fn chat_url_uses_ws_route() {
        // The URL must use /ws, not /ws/app-chat (agent only exposes /ws).
        let base = "http://127.0.0.1:9001";
        let name = "myagent";
        let token = "mytoken";
        let url = format!(
            "{}/agents/{}/ws?token={}",
            ws_base_url(base),
            name,
            token
        );
        assert!(url.contains("/ws?"), "chat URL must use /ws, got: {}", url);
        assert!(!url.contains("/ws/app-chat"), "chat URL must not use /ws/app-chat, got: {}", url);
        assert_eq!(url, "ws://127.0.0.1:9001/agents/myagent/ws?token=mytoken");
    }
}
