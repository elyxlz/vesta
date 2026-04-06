use std::sync::Arc;
use ureq::http::Response;
use ureq::Body;

use crate::types::{
    AuthFlowResponse, BackupInfo, ListEntry, ServerConfig, StartAllResult, StatusJson,
};

// ── HTTP client ─────────────────────────────────────────────────

fn check_response(resp: Response<Body>) -> Result<Response<Body>, String> {
    let status = resp.status().as_u16();
    if (200..300).contains(&status) {
        return Ok(resp);
    }
    let error_msg = resp.into_body().read_to_string().ok().and_then(|body| {
        serde_json::from_str::<serde_json::Value>(&body).ok()?.get("error")?.as_str().map(|s| s.to_string())
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
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => {
                out.push('%');
                out.push(char::from(b"0123456789ABCDEF"[(b >> 4) as usize]));
                out.push(char::from(b"0123456789ABCDEF"[(b & 0xf) as usize]));
            }
        }
    }
    out
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
        let resp = self.agent.get(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call().map_err(map_error)?;
        check_response(resp)
    }

    fn post(&self, path: &str) -> Result<Response<Body>, String> {
        let resp = self.agent.post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_empty().map_err(map_error)?;
        check_response(resp)
    }

    fn post_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        let resp = self.agent.post(&format!("{}{}", self.base_url, path))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .send_json(body).map_err(map_error)?;
        check_response(resp)
    }

    pub fn health(&self) -> Result<(), String> {
        let resp = self.agent.get(&format!("{}/health", self.base_url)).call().map_err(map_error)?;
        check_response(resp)?;
        Ok(())
    }

    pub fn list_agents(&self) -> Result<Vec<ListEntry>, String> {
        let resp = self.get("/agents")?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    pub fn agent_status(&self, name: &str) -> Result<StatusJson, String> {
        let resp = self.get(&format!("/agents/{}", name))?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    pub fn create_agent(&self, name: &str, build: bool) -> Result<String, String> {
        let body = serde_json::json!({"name": name, "build": build});
        let resp = self.post_json("/agents", &body)?;
        let v: serde_json::Value = resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    pub fn start_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/start", name))?;
        Ok(())
    }

    pub fn start_all(&self) -> Result<Vec<StartAllResult>, String> {
        #[derive(serde::Deserialize)]
        struct Resp { results: Vec<StartAllResult> }
        let resp = self.post("/agents/start")?;
        let v: Resp = resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))?;
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
        self.get(&format!("/agents/{}/wait-ready?timeout={}", name, timeout))?;
        Ok(())
    }

    pub fn start_auth(&self, name: &str) -> Result<AuthFlowResponse, String> {
        let resp = self.post(&format!("/agents/{}/auth", name))?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    pub fn complete_auth(&self, name: &str, session_id: &str, code: &str) -> Result<(), String> {
        let body = serde_json::json!({"session_id": session_id, "code": code});
        self.post_json(&format!("/agents/{}/auth/code", name), &body)?;
        Ok(())
    }

    pub fn inject_token(&self, name: &str, token: &str) -> Result<(), String> {
        let token_value: serde_json::Value = serde_json::from_str(token).map_err(|e| format!("invalid token JSON: {}", e))?;
        let body = serde_json::json!({"token": token_value});
        self.post_json(&format!("/agents/{}/auth/token", name), &body)?;
        Ok(())
    }

    pub fn create_backup(&self, name: &str) -> Result<BackupInfo, String> {
        let resp = self.post(&format!("/agents/{}/backups", name))?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    pub fn list_backups(&self, name: &str) -> Result<Vec<BackupInfo>, String> {
        let resp = self.get(&format!("/agents/{}/backups", name))?;
        resp.into_body().read_json().map_err(|e| format!("parse error: {}", e))
    }

    pub fn restore_backup(&self, name: &str, backup_id: &str) -> Result<(), String> {
        self.post(&format!("/agents/{}/backups/{}/restore", name, urlencod(backup_id)))?;
        Ok(())
    }

    pub fn delete_backup(&self, name: &str, backup_id: &str) -> Result<(), String> {
        let resp = self.agent.delete(&format!("{}/agents/{}/backups/{}", self.base_url, name, urlencod(backup_id)))
            .header("Authorization", &format!("Bearer {}", self.api_key))
            .call().map_err(map_error)?;
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
