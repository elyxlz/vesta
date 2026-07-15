use std::io::BufRead;
use std::sync::Arc;
use ureq::http::Response;
use ureq::Body;

use crate::types::{
    AuthFlowResponse, BackupInfo, ListEntry, ServerConfig, StartAllResult, StatusJson,
};

// ── HTTP client ─────────────────────────────────────────────────

/// How a proxied request authenticates, for `Client::proxy_status`.
pub enum ProxyAuth<'a> {
    /// No auth header at all — the browser's plain iframe request.
    None,
    /// The vestad API key as a Bearer token.
    ApiKey,
    /// An agent token via `X-Agent-Token`.
    AgentToken(&'a str),
}

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
            .map(|s| s.to_string())
    });
    match status {
        401 => Err("invalid API key".into()),
        404 => Err(error_msg.unwrap_or_else(|| "not found".into())),
        409 => Err(error_msg.unwrap_or_else(|| "conflict".into())),
        _ => Err(error_msg.unwrap_or_else(|| format!("server error ({})", status))),
    }
}

fn map_error(e: ureq::Error) -> String {
    format!("request failed: {}", e)
}

fn urlencod(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 3);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
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
        }
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

    fn put_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .put(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body)
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

    fn delete(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self
            .agent
            .delete(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call()
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

    pub fn health_json(&self) -> Result<serde_json::Value, String> {
        let resp = self
            .agent
            .get(&format!("{}/health", self.base_url))
            .call()
            .map_err(map_error)?;
        let resp = check_response(resp)?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    pub fn list_agents(&self) -> Result<Vec<ListEntry>, String> {
        let resp = self.get("/agents")?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    /// Register a background service exactly as the in-container skill does:
    /// `POST /agents/{name}/services` authenticated by the agent token. Returns the
    /// JSON body (`{ok, port, public}`).
    pub fn register_service_as_agent(&self, name: &str, service: &str, agent_token: &str) -> Result<serde_json::Value, String> {
        let resp = self
            .agent
            .post(&format!("{}/agents/{}/services", self.base_url, name))
            .header("X-Agent-Token", agent_token)
            .send_json(serde_json::json!({"name": service}))
            .map_err(map_error)?;
        check_response(resp)?
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
    }

    /// The registered services for an agent (`GET /agents/{name}/services`), as the raw
    /// `{service: {port, public, key, ...}}` map so tests can read a service's access key.
    pub fn services_json(&self, name: &str) -> Result<serde_json::Value, String> {
        let resp = self.get(&format!("/agents/{}/services", name))?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    /// GET a proxied path with a chosen authorization and return only the HTTP status code.
    /// Used to observe the proxy's auth decision (401 vs forwarded) for the session-key path.
    pub fn proxy_status(&self, path: &str, auth: ProxyAuth) -> Result<u16, String> {
        let mut req = self.agent.get(&format!("{}{}", self.base_url, path));
        match auth {
            ProxyAuth::None => {}
            ProxyAuth::ApiKey => req = req.header("Authorization", &format!("Bearer {}", self.api_key)),
            ProxyAuth::AgentToken(token) => req = req.header("X-Agent-Token", token),
        }
        let resp = req.call().map_err(map_error)?;
        Ok(resp.status().as_u16())
    }

    pub fn agent_status(&self, name: &str) -> Result<StatusJson, String> {
        let resp = self.get(&format!("/agents/{}", name))?;
        resp.into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))
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
            .map_err(|e| format!("parse error: {}", e))?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    pub fn start_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/start", name))?;
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
        self.delete(&format!("/agents/{}", name))?;
        Ok(())
    }

    pub fn rename_agent(&self, name: &str, new_name: &str) -> Result<String, String> {
        let body = serde_json::json!({"new_name": new_name});
        let resp = self.patch_json(&format!("/agents/{}", name), &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))?;
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
                    "{}: timeout waiting for stopped (status: {})",
                    name, status
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
                "not_found" | "dead" => return Err(format!("{}: {}", name, status)),
                _ => {}
            }
            if std::time::Instant::now() >= deadline {
                crate::dump_agent_diagnostics(name);
                return Err(format!(
                    "{}: timeout waiting for running (status: {})",
                    name, status
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
            .map_err(|e| format!("parse error: {}", e))
    }

    /// Standalone Claude OAuth completion. Returns the credentials JSON on success.
    pub fn oauth_complete(&self, session_id: &str, code: &str) -> Result<String, String> {
        let body = serde_json::json!({"session_id": session_id, "code": code});
        let resp = self.post_json("/providers/claude/oauth/complete", &body)?;
        let v: serde_json::Value = resp
            .into_body()
            .read_json()
            .map_err(|e| format!("parse error: {}", e))?;
        v["credentials"]
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| "missing credentials in response".to_string())
    }

    /// Sign an agent in with an OpenRouter key + model via `PUT /provider`. The write doesn't restart
    /// — callers (e.g. provision_and_settle) restart afterwards. The agent must be running (its WS
    /// port bound) to receive the call, so this waits first.
    pub fn sign_in_openrouter(&self, name: &str, key: &str, model: &str) -> Result<(), String> {
        self.wait_until_running(name, 60)?;
        let body = serde_json::json!({"kind": "openrouter", "model": model, "key": key});
        self.put_json(&format!("/agents/{}/provider", name), &body)?;
        Ok(())
    }

    /// Sign an agent in with a Claude OAuth credentials blob + model via `PUT /provider`. The write
    /// doesn't restart; callers restart afterwards. The agent must be running to receive the call.
    pub fn sign_in_claude(&self, name: &str, credentials: &str, model: &str) -> Result<(), String> {
        self.wait_until_running(name, 60)?;
        let body =
            serde_json::json!({"kind": "claude", "credentials": credentials, "model": model});
        self.put_json(&format!("/agents/{}/provider", name), &body)?;
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
            .map_err(map_error)?;
        check_response(resp)?;
        Ok(())
    }

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
