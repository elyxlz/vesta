use std::io::BufRead;
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message;
use ureq::http::Response;
use ureq::Body;

use crate::types::{
    AccessToken, AuthFlowResponse, BackupInfo, ListEntry, ServerConfig, StartAllResult, StatusJson,
};

// ── HTTP client ─────────────────────────────────────────────────

fn check_response(resp: Response<Body>) -> Result<Response<Body>, String> {
    let status = resp.status().as_u16();
    if (200..300).contains(&status) {
        return Ok(resp);
    }
    let error_msg = resp.into_body().read_to_string().ok().and_then(|body| {
        serde_json::from_str::<serde_json::Value>(&body)
            .ok()?
            .get("error")?
            .as_str()
            .map(std::string::ToString::to_string)
    });
    match status {
        401 => Err("invalid API key".into()),
        404 => Err(error_msg.unwrap_or_else(|| "not found".into())),
        409 => Err(error_msg.unwrap_or_else(|| "conflict".into())),
        _ => Err(error_msg.unwrap_or_else(|| format!("server error ({status})"))),
    }
}

fn map_error(e: &ureq::Error) -> String {
    format!("request failed: {e}")
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
                                .map(std::string::ToString::to_string)
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
            let cert = ureq::tls::Certificate::from_pem(pem.as_bytes()).expect("invalid cert PEM");
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

    fn get(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .get(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
            .map_err(|e| map_error(&e))?;
        check_response(resp)
    }

    fn post(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_empty()
            .map_err(|e| map_error(&e))?;
        check_response(resp)
    }

    fn post_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(|e| map_error(&e))?;
        check_response(resp)
    }

    fn put_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .put(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(|e| map_error(&e))?;
        check_response(resp)
    }

    fn patch_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .patch(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
            .map_err(|e| map_error(&e))?;
        check_response(resp)
    }

    fn delete(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .delete(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
            .map_err(|e| map_error(&e))?;
        check_response(resp)
    }

    pub fn health(&self) -> Result<(), String> {
        let resp = self
            .agent
            .get(&format!("{}/health", self.base_url))
            .call()
            .map_err(|e| map_error(&e))?;
        check_response(resp)?;
        Ok(())
    }

    pub fn health_json(&self) -> Result<serde_json::Value, String> {
        let resp = self
            .agent
            .get(&format!("{}/health", self.base_url))
            .call()
            .map_err(|e| map_error(&e))?;
        let resp = check_response(resp)?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
    }

    pub fn list_agents(&self) -> Result<Vec<ListEntry>, String> {
        let resp = self.get("/agents")?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
    }

    pub fn agent_status(&self, name: &str) -> Result<StatusJson, String> {
        let resp = self.get(&format!("/agents/{name}"))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
    }

    pub fn create_agent(&self, name: &str) -> Result<String, String> {
        self.create_agent_ex(name, None)
    }

    pub fn create_agent_ex(
        &self,
        name: &str,
        manage_agent_code: Option<bool>,
    ) -> Result<String, String> {
        let mut body = serde_json::json!({"name": name});
        if let Some(m) = manage_agent_code {
            body["manage_agent_code"] = serde_json::json!(m);
        }
        let resp = self.post_json("/agents", &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    pub fn start_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/start"))?;
        Ok(())
    }

    pub fn start_all(&self) -> Result<Vec<StartAllResult>, String> {
        #[derive(serde::Deserialize)]
        struct Resp {
            results: Vec<StartAllResult>,
        }
        let resp = self.post("/agents/start")?;
        let v: Resp = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))?;
        Ok(v.results)
    }

    pub fn stop_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/stop"))?;
        Ok(())
    }

    pub fn restart_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/restart"))?;
        Ok(())
    }

    pub fn destroy_agent(&self, name: &str) -> Result<(), String> {
        self.delete(&format!("/agents/{name}"))?;
        Ok(())
    }

    pub fn rename_agent(&self, name: &str, new_name: &str) -> Result<String, String> {
        let body = serde_json::json!({"new_name": new_name});
        let resp = self.patch_json(&format!("/agents/{name}"), &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))?;
        Ok(v["name"].as_str().unwrap_or(new_name).to_string())
    }

    pub fn wait_until_alive(&self, name: &str, timeout_secs: u64) -> Result<(), String> {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
        let mut backoff = std::time::Duration::from_millis(200);
        loop {
            let status = self.agent_status(name)?;
            match status.status.as_str() {
                "alive" => return Ok(()),
                "not_found" | "dead" | "stopped" | "not_authenticated" | "unprovisioned" => {
                    return Err(format!("{}: {}", name, status.status))
                }
                _ => {}
            }
            if std::time::Instant::now() >= deadline {
                crate::dump_agent_diagnostics(name);
                return Err(format!(
                    "{}: timeout waiting for ready (status: {})",
                    name, status.status
                ));
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(std::time::Duration::from_secs(1));
        }
    }

    /// Poll until the agent is no longer up (settled to `stopped`/`dead`/`not_found`).
    /// `stop`/`destroy` are asynchronous — the container takes time to wind down — so
    /// tests must wait for the transition rather than reading status immediately.
    pub fn wait_until_stopped(&self, name: &str, timeout_secs: u64) -> Result<(), String> {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
        let mut backoff = std::time::Duration::from_millis(200);
        loop {
            let status = self.agent_status(name)?.status;
            if !crate::is_up(&status) {
                return Ok(());
            }
            if std::time::Instant::now() >= deadline {
                crate::dump_agent_diagnostics(name);
                return Err(format!(
                    "{name}: timeout waiting for stopped (status: {status})"
                ));
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(std::time::Duration::from_secs(1));
        }
    }

    /// Poll until the agent's HTTP server is bound (a settled status, not the
    /// transient "starting"). Auth state is now served by the agent over its WS
    /// port, so callers must wait for that port before asserting auth status.
    pub fn wait_until_running(&self, name: &str, timeout_secs: u64) -> Result<String, String> {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
        let mut backoff = std::time::Duration::from_millis(200);
        loop {
            let status = self.agent_status(name)?.status;
            match status.as_str() {
                "alive" | "setting_up" | "not_authenticated" | "unprovisioned" => {
                    return Ok(status)
                }
                "not_found" | "dead" => return Err(format!("{name}: {status}")),
                _ => {}
            }
            if std::time::Instant::now() >= deadline {
                crate::dump_agent_diagnostics(name);
                return Err(format!(
                    "{name}: timeout waiting for running (status: {status})"
                ));
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(std::time::Duration::from_secs(1));
        }
    }

    /// Standalone Claude OAuth start (not agent-scoped). Returns the auth URL and session id.
    pub fn oauth_start(&self) -> Result<AuthFlowResponse, String> {
        let resp = self.post("/providers/claude/oauth/start")?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
    }

    /// Standalone Claude OAuth completion. Returns the credentials JSON on success.
    pub fn oauth_complete(&self, session_id: &str, code: &str) -> Result<String, String> {
        let body = serde_json::json!({"session_id": session_id, "code": code});
        let resp = self.post_json("/providers/claude/oauth/complete", &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))?;
        v["credentials"]
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| "missing credentials in response".to_string())
    }

    /// Sign an agent in with an `OpenRouter` key + model via `PUT /provider`. The write doesn't restart
    /// — callers (e.g. `provision_and_settle`) restart afterwards. The agent must be running (its WS
    /// port bound) to receive the call, so this waits first.
    pub fn sign_in_openrouter(&self, name: &str, key: &str, model: &str) -> Result<(), String> {
        self.wait_until_running(name, 60)?;
        let body = serde_json::json!({"kind": "openrouter", "model": model, "key": key});
        self.put_json(&format!("/agents/{name}/provider"), &body)?;
        Ok(())
    }

    /// Sign an agent in with a Claude OAuth credentials blob + model via `PUT /provider`. The write
    /// doesn't restart; callers restart afterwards. The agent must be running to receive the call.
    pub fn sign_in_claude(&self, name: &str, credentials: &str, model: &str) -> Result<(), String> {
        self.wait_until_running(name, 60)?;
        let body =
            serde_json::json!({"kind": "claude", "credentials": credentials, "model": model});
        self.put_json(&format!("/agents/{name}/provider"), &body)?;
        Ok(())
    }

    /// Deliver a chat message to the agent's `app-chat` skill service via `POST
    /// /agents/{name}/app-chat/message` (the generic authenticated proxy), the same path the web/mobile
    /// clients use. A `200` means the daemon durably intook it (persisted, echoed, notification
    /// written); delivery truth is still the `append` echo carrying `intent_id`. Pass `intent_id` to
    /// correlate that echo; omit with `None`. Requires the agent's app-chat daemon to be running
    /// (`start_app_chat_daemon` for model-less fake-token agents).
    pub fn send_message(&self, name: &str, text: &str, intent_id: Option<&str>) -> Result<(), String> {
        let mut body = serde_json::json!({ "text": text });
        if let Some(id) = intent_id {
            body["intent_id"] = serde_json::Value::String(id.to_string());
        }
        self.post_json(&format!("/agents/{name}/app-chat/message"), &body)?;
        Ok(())
    }

    /// Fetch the agent's app-chat conversation tail via `GET /agents/{name}/app-chat/history` (the
    /// skill service through the proxy), the same `{events, cursor}` page the clients read. `limit`
    /// caps the page size.
    pub fn fetch_app_chat_history(&self, name: &str, limit: u32) -> Result<serde_json::Value, String> {
        let resp = self.get(&format!("/agents/{name}/app-chat/history?limit={limit}"))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
    }

    /// Start the agent's `app-chat` daemon in-container, idempotently. Model-less fake-token agents
    /// never run the skill's setup or the restart daemon block, so send/history scenarios install the
    /// CLI and start the daemon by hand before the service can accept a request. Docker-exec, not HTTP:
    /// the daemon owns the service the proxy targets. Sources `/run/vestad-env` (`WS_PORT`,
    /// `AGENT_TOKEN`, `VESTAD_PORT`, `AGENT_NAME`) that register-service and `serve` read; `PATH`
    /// carries uv and `/root/.local/bin` from the image env. Re-runnable across a restart (the daemon dies with the
    /// container's process tree): `--force` reinstall is a no-op and `daemon start` is idempotent.
    pub fn start_app_chat_daemon(&self, name: &str) -> Result<(), String> {
        let container = crate::agent_container_name(name);
        crate::exec_in_container(
            &container,
            ". /run/vestad-env && uv tool install --force --editable /root/agent/core/skills/app-chat/cli && app-chat daemon start",
        )?;
        Ok(())
    }

    /// Mint a JWT access token (+ rotating refresh token) via `POST /auth/session`, exchanging the
    /// raw API key. Use the returned `access_token` for `open_sync_with_token` to exercise the `/sync`
    /// deadline/`reauth` path a raw-key connect never hits.
    pub fn mint_access_token(&self) -> Result<AccessToken, String> {
        let body = serde_json::json!({ "api_key": self.api_key });
        let resp = self.post_json("/auth/session", &body)?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
    }

    /// Open a `/sync` WebSocket authenticated with the raw API key (never-expiring, no deadline).
    pub async fn open_sync(&self) -> Result<SyncSocket, String> {
        self.connect_sync(&self.api_key).await
    }

    /// Open a `/sync` WebSocket authenticated with a JWT access token (from `mint_access_token`),
    /// so the connection carries a `token_deadline` the server enforces unless a `reauth` extends it.
    pub async fn open_sync_with_token(&self, jwt: &str) -> Result<SyncSocket, String> {
        self.connect_sync(jwt).await
    }

    async fn connect_sync(&self, token: &str) -> Result<SyncSocket, String> {
        let url = format!(
            "{}/sync?token={}",
            ws_base_url(&self.base_url),
            urlencod(token)
        );
        let tls = make_ws_rustls_config(self.cert_fingerprint.clone());
        let connector = tokio_tungstenite::Connector::Rustls(tls);
        let (ws, _resp) =
            tokio_tungstenite::connect_async_tls_with_config(&url, None, false, Some(connector))
                .await
                .map_err(|e| format!("sync connect failed: {e}"))?;
        Ok(SyncSocket { ws })
    }

    pub fn create_backup(&self, name: &str) -> Result<BackupInfo, String> {
        let resp = self.post(&format!("/agents/{name}/backups"))?;
        let data = read_sse_result(resp)?;
        serde_json::from_str(&data).map_err(|e| format!("parse error: {e}"))
    }

    pub fn list_backups(&self, name: &str) -> Result<Vec<BackupInfo>, String> {
        let resp = self.get(&format!("/agents/{name}/backups"))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {e}"))
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
        let resp = self
            .agent
            .delete(&format!(
                "{}/agents/{}/backups/{}",
                self.base_url,
                name,
                urlencod(backup_id)
            ))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
            .map_err(|e| map_error(&e))?;
        check_response(resp)?;
        Ok(())
    }

    pub fn stream_logs(&self, name: &str) -> Result<(), String> {
        let resp = self.get(&format!("/agents/{name}/logs"))?;
        let reader = std::io::BufReader::new(resp.into_body().into_reader());
        for line in std::io::BufRead::lines(reader) {
            let line = line.map_err(|e| format!("read error: {e}"))?;
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

// ── /sync WebSocket client ──────────────────────────────────────

type WsStream =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

/// A live `/sync` connection. Frames are parsed as `serde_json::Value` keyed on `type` (lighter than
/// mirroring the server's protocol enum here); ping/pong are drained transparently on `recv_frame`.
pub struct SyncSocket {
    ws: WsStream,
}

impl SyncSocket {
    /// Send a raw client frame (`watch`/`unwatch`/`reauth`, or an arbitrary one to probe the
    /// server's ignore-unknown rule).
    pub async fn send_client_frame(&mut self, frame: &serde_json::Value) -> Result<(), String> {
        self.ws
            .send(Message::Text(frame.to_string().into()))
            .await
            .map_err(|e| format!("send frame: {e}"))
    }

    pub async fn watch(&mut self, agent: &str) -> Result<(), String> {
        self.send_client_frame(&serde_json::json!({ "type": "watch", "agent": agent }))
            .await
    }

    pub async fn unwatch(&mut self, agent: &str) -> Result<(), String> {
        self.send_client_frame(&serde_json::json!({ "type": "unwatch", "agent": agent }))
            .await
    }

    pub async fn reauth(&mut self, token: &str) -> Result<(), String> {
        self.send_client_frame(&serde_json::json!({ "type": "reauth", "token": token }))
            .await
    }

    /// Read the next text frame within `timeout`, draining ping/pong/binary. Errors on timeout, a
    /// close frame, a transport error, or a stream end.
    pub async fn recv_frame(&mut self, timeout: Duration) -> Result<serde_json::Value, String> {
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            let next = tokio::time::timeout(remaining, self.ws.next())
                .await
                .map_err(|_| "timed out waiting for sync frame".to_string())?;
            match next {
                Some(Ok(Message::Text(text))) => {
                    return serde_json::from_str(text.as_str())
                        .map_err(|e| format!("parse frame: {e}"));
                }
                Some(Ok(Message::Close(_))) => return Err("sync socket closed by server".into()),
                Some(Err(e)) => return Err(format!("sync socket error: {e}")),
                None => return Err("sync socket ended".into()),
                // Ping/pong/binary/raw: drain and keep waiting for a text frame.
                Some(Ok(_)) => {}
            }
        }
    }

    /// Read frames until one satisfies `pred` or `timeout` elapses, mirroring the harness's
    /// `wait_until_*` deadline idiom for the WS stream.
    pub async fn expect_frame_matching<F>(
        &mut self,
        mut pred: F,
        timeout: Duration,
    ) -> Result<serde_json::Value, String>
    where
        F: FnMut(&serde_json::Value) -> bool,
    {
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err("timed out waiting for a matching sync frame".into());
            }
            let frame = self.recv_frame(remaining).await?;
            if pred(&frame) {
                return Ok(frame);
            }
        }
    }

    pub async fn close(mut self) -> Result<(), String> {
        self.ws.close(None).await.map_err(|e| format!("close: {e}"))
    }
}

fn ws_base_url(url: &str) -> String {
    url.replace("https://", "wss://").replace("http://", "ws://")
}

/// Build a rustls client config that pins the server's self-signed cert by SHA-256 fingerprint,
/// matching vestad's fingerprint-verification TLS (no CA chain). Lifted from
/// `vestad/tests/server/websocket.rs` so the shared harness owns the one connector.
fn make_ws_rustls_config(fingerprint: Option<String>) -> Arc<rustls::ClientConfig> {
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
                        .map(|b| format!("{b:02X}"))
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
