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

        match fingerprint_match(expected, &actual) {
            Ok(()) => Ok(rustls::client::danger::ServerCertVerified::assertion()),
            Err(msg) => Err(rustls::Error::General(msg)),
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

/// Compare a pinned (expected) certificate fingerprint against the actual one
/// computed from the presented cert. Returns the mismatch error message on
/// rejection. Kept pure (string-only) so the pin comparison is unit-testable
/// without opening a TLS connection.
fn fingerprint_match(expected: &str, actual: &str) -> Result<(), String> {
    if actual == expected {
        Ok(())
    } else {
        Err(format!(
            "certificate fingerprint mismatch: expected {expected}, got {actual}"
        ))
    }
}

fn cert_fingerprint(der: &[u8]) -> String {
    let digest = ring::digest::digest(&ring::digest::SHA256, der);
    format!(
        "sha256:{}",
        digest
            .as_ref()
            .iter()
            .map(|b| format!("{b:02X}"))
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

    Err(status_error_message(status, error_msg))
}

/// Map a non-2xx status code plus an optional server-supplied error message to
/// the user-facing error string. Kept pure (no network I/O) so the mapping is
/// directly unit-testable.
fn status_error_message(status: u16, error_msg: Option<String>) -> String {
    match status {
        401 => "invalid API key".into(),
        404 => error_msg.unwrap_or_else(|| "not found".into()),
        409 => error_msg.unwrap_or_else(|| "conflict".into()),
        503 => error_msg.unwrap_or_else(|| "vestad is not reachable — is it running?".into()),
        _ => error_msg.unwrap_or_else(|| format!("server error ({status})")),
    }
}

fn read_json<T: serde::de::DeserializeOwned>(resp: Response<Body>) -> Result<T, String> {
    resp.into_body().read_json().map_err(|e| format!("parse error: {e}"))
}

fn map_error(host: &str, e: ureq::Error) -> String {
    match e {
        ureq::Error::ConnectionFailed | ureq::Error::Io(_) => {
            format!("server not reachable at {host} — run 'vesta connect <host>' to point at a different one")
        }
        other => format!("request failed: {other}"),
    }
}

fn extract_server_error(body: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    v["error"].as_str().map(|s| s.to_string())
}

fn extract_latest_version(value: &serde_json::Value) -> Option<String> {
    let tag = value["latest_version"].as_str()?.trim().trim_start_matches('v');
    if tag.is_empty() {
        None
    } else {
        Some(tag.to_string())
    }
}

fn url_encode(value: &str) -> String {
    percent_encoding::utf8_percent_encode(value, percent_encoding::NON_ALPHANUMERIC).to_string()
}

/// Read an SSE stream, returning the data from the "done" event or an error.
/// SSE keepalive comments are silently ignored.
fn read_sse_result(resp: Response<Body>) -> Result<String, String> {
    let reader = std::io::BufReader::new(resp.into_body().into_reader());
    let mut event_type = String::new();
    let mut data = String::new();

    for line in BufRead::lines(reader) {
        let line = line.map_err(|e| format!("read error: {e}"))?;

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

/// OpenRouter creation args, set when an agent runs on an OpenRouter API key instead of a Claude account.
pub struct OpenRouterArgs {
    pub key: String,
    pub model: String,
}

/// A model entry from OpenRouter's top-weekly list, used to populate the
/// interactive model picker in `vesta setup`.
#[derive(serde::Deserialize)]
pub struct OpenRouterModel {
    pub slug: String,
    pub label: String,
    pub author: String,
    /// USD per million prompt/completion/cache-read tokens, when OpenRouter reports it.
    #[serde(default)]
    pub input_price: Option<f64>,
    #[serde(default)]
    pub output_price: Option<f64>,
    #[serde(default)]
    pub cache_read_price: Option<f64>,
}

impl Client {
    pub fn new(config: &ServerConfig) -> Result<Self, String> {
        let tls_config = if let Some(ref pem) = config.cert_pem {
            let cert = ureq::tls::Certificate::from_pem(pem.as_bytes())
                .map_err(|e| format!("invalid cert PEM in server config: {e}"))?;
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
        Ok(Self {
            agent,
            base_url: config.url.clone(),
            api_key: config.api_key.clone(),
            cert_fingerprint: config.cert_fingerprint.clone(),
        })
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
            .map_err(|e| map_error(&self.base_url, e))?;
        check_response(resp)
    }

    fn post(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_empty()
            .map_err(|e| map_error(&self.base_url, e))?;
        check_response(resp)
    }

    fn post_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(|e| map_error(&self.base_url, e))?;
        check_response(resp)
    }

    fn delete_req(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .delete(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
            .map_err(|e| map_error(&self.base_url, e))?;
        check_response(resp)
    }

    fn put_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .put(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(|e| map_error(&self.base_url, e))?;
        check_response(resp)
    }

    pub fn health(&self) -> Result<(), String> {
        let resp = self
            .agent
            .get(&format!("{}/health", self.base_url))
            .call()
            .map_err(|e| map_error(&self.base_url, e))?;
        check_response(resp)?;
        Ok(())
    }

    // Read vestad's cached view of the latest release. vestad polls GitHub on
    // our behalf (with an ETag conditional request), so routing through it keeps
    // every client on one machine from hitting the GitHub API independently.
    pub fn latest_release_tag(&self) -> Result<Option<String>, String> {
        let resp = self.get("/version")?;
        let value: serde_json::Value = read_json(resp)?;
        Ok(extract_latest_version(&value))
    }

    // Force vestad to refresh from GitHub, then return the latest tag. Used by
    // the explicit `vesta update` so it does not act on a stale cached value.
    pub fn check_latest_release_tag(&self) -> Result<Option<String>, String> {
        let resp = self.post("/version/check")?;
        let value: serde_json::Value = read_json(resp)?;
        Ok(extract_latest_version(&value))
    }

    pub fn get_channel(&self) -> Result<String, String> {
        let resp = self.get("/settings/channel")?;
        let value: serde_json::Value = read_json(resp)?;
        match value.get("channel").and_then(|c| c.as_str()) {
            Some(channel) => Ok(channel.to_string()),
            None => Err("response missing channel".into()),
        }
    }

    pub fn set_channel(&self, channel: &str) -> Result<String, String> {
        let resp = self.put_json("/settings/channel", &serde_json::json!({ "channel": channel }))?;
        let value: serde_json::Value = read_json(resp)?;
        match value.get("channel").and_then(|c| c.as_str()) {
            Some(channel) => Ok(channel.to_string()),
            None => Err("response missing channel".into()),
        }
    }

    pub fn list_agents(&self) -> Result<Vec<ListEntry>, String> {
        let resp = self.get("/agents")?;
        read_json(resp)
    }

    pub fn agent_status(&self, name: &str) -> Result<StatusJson, String> {
        let resp = self.get(&format!("/agents/{name}"))?;
        read_json(resp)
    }

    /// Create an empty agent container. Provider config is sent separately via
    /// `set_provider` once the agent is up (vestad no longer accepts credentials
    /// at create time — see refactor for agent-owned auth state).
    pub fn create_agent(&self, name: &str, manage_agent_code: bool, timezone: Option<&str>) -> Result<String, String> {
        let mut body = serde_json::json!({"name": name, "manage_agent_code": manage_agent_code});
        if let Some(tz) = timezone {
            body["timezone"] = serde_json::json!(tz);
        }
        let resp = self.post_json("/agents", &body)?;
        let v: serde_json::Value = read_json(resp)?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    /// Provision an existing agent with provider credentials. Either Claude
    /// (`credentials`: OAuth JSON blob) or OpenRouter (key/model).
    pub fn set_provider_credentials(&self, name: &str, credentials: &str) -> Result<(), String> {
        serde_json::from_str::<serde_json::Value>(credentials)
            .map_err(|e| format!("invalid credentials JSON: {e}"))?;
        let body = serde_json::json!({"credentials": credentials});
        self.post_json(&format!("/agents/{name}/provider"), &body)?;
        Ok(())
    }

    pub fn set_provider_openrouter(&self, name: &str, args: &OpenRouterArgs) -> Result<(), String> {
        let body = serde_json::json!({
            "openrouter_key": args.key,
            "openrouter_model": args.model,
        });
        self.post_json(&format!("/agents/{name}/provider"), &body)?;
        Ok(())
    }

    pub fn get_agent_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.get(&format!("/agents/{name}/settings"))?;
        read_json(resp)
    }

    pub fn start_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/start"))?;
        Ok(())
    }

    pub fn start_all(&self) -> Result<Vec<StartAllResult>, String> {
        let resp = self.post("/agents/start")?;
        let response: StartAllResponse = read_json(resp)?;
        Ok(response.results)
    }

    pub fn stop_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/stop"))?;
        Ok(())
    }

    pub fn restart_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/restart"))?;
        Ok(())
    }

    pub fn restart_gateway(&self) -> Result<(), String> {
        self.post("/gateway/restart")?;
        Ok(())
    }

    pub fn stream_gateway_logs(&self, tail: u64, follow: bool) -> Result<(), String> {
        let resp = self.get(&format!("/gateway/logs?tail={tail}&follow={follow}"))?;
        consume_sse_log_stream(resp, "gateway_stopped", None)
    }

    pub fn destroy_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/destroy"))?;
        Ok(())
    }

    pub fn rebuild_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/rebuild"))?;
        Ok(())
    }

    /// Poll until status is `alive` OR `not_authenticated`. Used right after
    /// `create_agent` to know the agent's HTTP server is up and ready to accept
    /// `POST /agents/{name}/provider` — a brand-new empty agent will report
    /// `not_authenticated` until the provider is provisioned.
    pub fn wait_until_running(&self, name: &str, timeout: Duration) -> Result<(), String> {
        let deadline = Instant::now() + timeout;
        let mut backoff = Duration::from_millis(200);
        loop {
            let status = self.agent_status(name)?;
            match status.status.as_str() {
                "alive" | "not_authenticated" => return Ok(()),
                "not_found" | "dead" | "stopped" =>
                    return Err(format!("{}: {}", name, status.status)),
                _ => {}
            }
            if Instant::now() >= deadline {
                return Err(format!("{}: timeout waiting for HTTP server (status: {})", name, status.status));
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(Duration::from_secs(1));
        }
    }

    /// Poll `/agents/{name}` until `status == "alive"` or the deadline passes.
    /// Terminal non-alive states (not_found, dead, stopped, not_authenticated)
    /// surface as immediate errors; the agent cannot become ready from those.
    pub fn wait_until_alive(&self, name: &str, timeout: Duration) -> Result<(), String> {
        self.wait_until_alive_with_progress(name, timeout, |_| {})
    }

    /// Same as [`wait_until_alive`], but invokes `on_change` with the new status
    /// each time it changes, so callers can surface progress (e.g. `setting_up`).
    pub fn wait_until_alive_with_progress(
        &self,
        name: &str,
        timeout: Duration,
        mut on_change: impl FnMut(&str),
    ) -> Result<(), String> {
        let deadline = Instant::now() + timeout;
        let mut backoff = Duration::from_millis(200);
        let mut last = String::new();
        loop {
            let status = self.agent_status(name)?;
            if status.status != last {
                on_change(&status.status);
                last = status.status.clone();
            }
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

    // Agent-less OAuth — runs the PKCE dance independent of any agent. Used by
    // `vesta setup` (pre-create) and `vesta auth <name>` (post-create reauth),
    // followed by either POST /agents or POST /agents/{name}/provider.
    pub fn start_auth_standalone(&self) -> Result<AuthFlowResponse, String> {
        let resp = self.post("/providers/claude/oauth/start")?;
        read_json(resp)
    }

    pub fn complete_auth_standalone(&self, session_id: &str, code: &str) -> Result<String, String> {
        let body = serde_json::json!({"session_id": session_id, "code": code});
        let resp = self.post_json("/providers/claude/oauth/complete", &body)?;
        let v: serde_json::Value = read_json(resp)?;
        v["credentials"]
            .as_str()
            .map(String::from)
            .ok_or_else(|| "no credentials in response".to_string())
    }

    pub fn validate_openrouter_key(&self, key: &str) -> Result<(), String> {
        let body = serde_json::json!({"key": key});
        self.post_json("/providers/openrouter/validate-key", &body)?;
        Ok(())
    }

    pub fn fetch_top_openrouter_models(&self) -> Result<Vec<OpenRouterModel>, String> {
        let resp = self.get("/providers/openrouter/models/top")?;
        read_json(resp)
    }


    pub fn create_backup(&self, name: &str) -> Result<BackupInfo, String> {
        let resp = self.post(&format!("/agents/{name}/backups"))?;
        let data = read_sse_result(resp)?;
        serde_json::from_str(&data).map_err(|e| format!("parse error: {e}"))
    }

    pub fn list_backups(&self, name: &str) -> Result<Vec<BackupInfo>, String> {
        let resp = self.get(&format!("/agents/{name}/backups"))?;
        read_json(resp)
    }

    pub fn restore_backup(&self, name: &str, backup_id: &str) -> Result<(), String> {
        let resp = self.post(&format!(
            "/agents/{}/backups/{}/restore",
            name,
            url_encode(backup_id)
        ))?;
        read_sse_result(resp)?;
        Ok(())
    }

    pub fn delete_backup(&self, name: &str, backup_id: &str) -> Result<(), String> {
        self.delete_req(&format!("/agents/{}/backups/{}", name, url_encode(backup_id)))?;
        Ok(())
    }

    pub fn get_auto_backup_settings(&self) -> Result<serde_json::Value, String> {
        let resp = self.get("/settings/auto-backup")?;
        read_json(resp)
    }

    pub fn set_auto_backup_settings(&self, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        let resp = self.put_json("/settings/auto-backup", body)?;
        read_json(resp)
    }

    pub fn list_all_backups(&self) -> Result<Vec<BackupInfo>, String> {
        let resp = self.get("/backups")?;
        read_json(resp)
    }

    pub fn get_agent_backup_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.get(&format!("/agents/{name}/settings/backup"))?;
        read_json(resp)
    }

    pub fn set_agent_backup_settings(&self, name: &str, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        let resp = self.put_json(&format!("/agents/{name}/settings/backup"), body)?;
        read_json(resp)
    }

    pub fn delete_agent_backup_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.delete_req(&format!("/agents/{name}/settings/backup"))?;
        read_json(resp)
    }

    pub fn get_agent_constitution(&self, name: &str) -> Result<String, String> {
        let resp = self.get(&format!("/agents/{name}/constitution"))?;
        let body: serde_json::Value = read_json(resp)?;
        body["content"]
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| "response missing 'content' field".to_string())
    }

    pub fn set_agent_constitution(&self, name: &str, content: &str) -> Result<(), String> {
        let body = serde_json::json!({ "content": content });
        self.put_json(&format!("/agents/{name}/constitution"), &body)?;
        Ok(())
    }

    pub fn stream_logs(&self, name: &str, tail: u64) -> Result<(), String> {
        let resp = self.get(&format!("/agents/{name}/logs?tail={tail}"))?;
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
        let line = line.map_err(|e| format!("read error: {e}"))?;
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
            "{ANSI_TS}[{time}]{ANSI_RESET} {nick_color}<{nick}>{ANSI_RESET} {text}",
        );
    } else {
        println!("[{time}] <{nick}> {text}");
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
        url.parse().map_err(|e| format!("invalid ws url: {e}"))?;
    let host = parsed.host_str().unwrap_or("localhost");
    let port = parsed.port_or_known_default().unwrap_or(443);
    let tcp = std::net::TcpStream::connect((host, port))
        .map_err(|e| format!("ws tcp connect failed: {e}"))?;
    tcp.set_read_timeout(Some(std::time::Duration::from_millis(CHAT_READ_TIMEOUT_MS)))
        .map_err(|e| format!("failed to set read timeout: {e}"))?;
    let connector =
        tungstenite::Connector::Rustls(make_ws_rustls_config(client.cert_fingerprint().map(|s| s.to_string())));
    let (mut socket, _) =
        tungstenite::client_tls_with_config(url, tcp, None, Some(connector))
            .map_err(|e| format!("ws connect failed: {e}"))?;

    let color = std::io::stdout().is_terminal();

    eprintln!("connected to {name}. type a message and press enter.");

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

    let mut loop_error: Option<String> = None;

    loop {
        if let Ok(input) = rx.try_recv() {
            if !input.is_empty() {
                if color {
                    print!("\x1b[1A\x1b[2K\r");
                }
                render_line(&time_now_utc(), "you", ANSI_YOU, &input, color);
                std::io::stdout().flush().ok();
                let msg = serde_json::json!({"type": "message", "text": input});
                match socket.send(tungstenite::Message::Text(msg.to_string().into())) {
                    Ok(_) => {}
                    Err(send_err) => {
                        loop_error = Some(format!("connection lost while sending: {send_err}"));
                        break;
                    }
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
            Err(read_err) => {
                loop_error = Some(format!("connection lost: {read_err}"));
                break;
            }
        }
    }

    match loop_error {
        Some(message) => Err(message),
        None => Ok(()),
    }
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
        assert!(url.contains("/ws?"), "chat URL must use /ws, got: {url}");
        assert!(!url.contains("/ws/app-chat"), "chat URL must not use /ws/app-chat, got: {url}");
        assert_eq!(url, "ws://127.0.0.1:9001/agents/myagent/ws?token=mytoken");
    }

    #[test]
    fn extract_server_error_reads_error_field() {
        assert_eq!(
            extract_server_error(r#"{"error":"agent already exists"}"#),
            Some("agent already exists".to_string())
        );
        // Missing/non-string error field or non-JSON body yields None.
        assert_eq!(extract_server_error(r#"{"detail":"nope"}"#), None);
        assert_eq!(extract_server_error(r#"{"error":42}"#), None);
        assert_eq!(extract_server_error("not json"), None);
    }

    #[test]
    fn status_error_message_maps_status_and_body() {
        struct Case {
            status: u16,
            body: Option<&'static str>,
            expected: &'static str,
        }
        let cases = [
            // 401 is fixed regardless of any server-supplied message.
            Case { status: 401, body: Some("ignored"), expected: "invalid API key" },
            Case { status: 401, body: None, expected: "invalid API key" },
            // 404/409/503 prefer the server message, fall back to a default.
            Case { status: 404, body: Some("no such agent"), expected: "no such agent" },
            Case { status: 404, body: None, expected: "not found" },
            Case { status: 409, body: Some("name taken"), expected: "name taken" },
            Case { status: 409, body: None, expected: "conflict" },
            Case { status: 503, body: Some("down for maintenance"), expected: "down for maintenance" },
            Case { status: 503, body: None, expected: "vestad is not reachable — is it running?" },
            // Other statuses fall through to the generic formatted default.
            Case { status: 500, body: Some("boom"), expected: "boom" },
            Case { status: 500, body: None, expected: "server error (500)" },
            Case { status: 418, body: None, expected: "server error (418)" },
        ];
        for case in cases {
            assert_eq!(
                status_error_message(case.status, case.body.map(str::to_string)),
                case.expected,
                "status {} with body {:?}",
                case.status,
                case.body
            );
        }
    }

    #[test]
    fn extract_latest_version_strips_v_prefix() {
        assert_eq!(
            extract_latest_version(&serde_json::json!({"latest_version": "v1.2.3"})),
            Some("1.2.3".to_string())
        );
        assert_eq!(
            extract_latest_version(&serde_json::json!({"latest_version": " 0.4.0 "})),
            Some("0.4.0".to_string())
        );
        assert_eq!(extract_latest_version(&serde_json::json!({"latest_version": ""})), None);
        assert_eq!(extract_latest_version(&serde_json::json!({})), None);
    }

    #[test]
    fn start_all_response_deserializes_results() {
        let body = r#"{"results":[{"name":"alpha","ok":true,"error":null},{"name":"beta","ok":false,"error":"boom"}]}"#;
        let parsed: StartAllResponse = serde_json::from_str(body).expect("valid StartAllResponse body");
        assert_eq!(parsed.results.len(), 2);
        assert_eq!(parsed.results[0].name, "alpha");
        assert!(parsed.results[0].ok);
        assert_eq!(parsed.results[1].error.as_deref(), Some("boom"));
    }

    #[test]
    fn fingerprint_match_accepts_matching_pin() {
        let pin = "sha256:AA:BB:CC";
        assert!(fingerprint_match(pin, pin).is_ok());
    }

    #[test]
    fn fingerprint_match_rejects_mismatched_pin() {
        let expected = "sha256:AA:BB:CC";
        let actual = "sha256:DD:EE:FF";
        let err = fingerprint_match(expected, actual).expect_err("mismatched pin must be rejected");
        assert!(err.contains("fingerprint mismatch"), "got: {err}");
        assert!(err.contains(expected), "error must name expected pin, got: {err}");
        assert!(err.contains(actual), "error must name actual pin, got: {err}");
    }

    #[test]
    fn cert_fingerprint_is_stable_sha256_hex() {
        // SHA-256 of the empty input, formatted as the pin string.
        let fp = cert_fingerprint(&[]);
        assert_eq!(
            fp,
            "sha256:E3:B0:C4:42:98:FC:1C:14:9A:FB:F4:C8:99:6F:B9:24:27:AE:41:E4:64:9B:93:4C:A4:95:99:1B:78:52:B8:55"
        );
        // A matching computed fingerprint is accepted by the pin comparison.
        assert!(fingerprint_match(&fp, &cert_fingerprint(&[])).is_ok());
    }
}
