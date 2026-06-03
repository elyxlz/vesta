//! Thin HTTP proxy into an agent's /provider endpoints.
//!
//! Vestad owns NO knowledge of credential file formats or provider parsing —
//! that all lives in the agent's `core/provider.py`. This module is just the
//! plumbing to call the agent's HTTP API authenticated with its agent token.

use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::docker::read_agent_port_and_token;

/// Short HTTP timeout for the per-status-poll call; a hung agent should not
/// stall vestad's status loop. Status callers treat a timeout as `Starting`.
const STATUS_TIMEOUT: Duration = Duration::from_secs(2);
/// Longer timeout for provider writes — the agent does file I/O.
const SET_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Deserialize, Serialize, Debug)]
pub struct ProviderStatus {
    pub state: String,
    pub kind: String,
    #[serde(default)]
    pub model: Option<String>,
    /// Whether the agent finished first-start setup. Defaults to `true` so an
    /// older agent that doesn't report the field isn't stuck reporting `SettingUp`.
    #[serde(default = "default_setup_complete")]
    pub setup_complete: bool,
}

fn default_setup_complete() -> bool {
    true
}

pub struct AgentProvider<'a> {
    http_client: &'a reqwest::Client,
    agents_dir: &'a Path,
    name: String,
}

impl<'a> AgentProvider<'a> {
    pub fn new(http_client: &'a reqwest::Client, agents_dir: &'a Path, name: impl Into<String>) -> Self {
        Self {
            http_client,
            agents_dir,
            name: name.into(),
        }
    }

    /// GET the agent's /provider/status. Returns Err on network failure,
    /// missing env file (agent not yet provisioned), non-2xx, or timeout.
    pub async fn status(&self) -> Result<ProviderStatus, String> {
        let (port, token) = self.port_and_token()?;
        let resp = self.http_client
            .get(format!("http://127.0.0.1:{port}/provider/status"))
            .header("X-Agent-Token", token)
            .timeout(STATUS_TIMEOUT)
            .send()
            .await
            .map_err(|e| format!("agent status request failed: {e}"))?;
        if !resp.status().is_success() {
            return Err(format!("agent status returned HTTP {}", resp.status()));
        }
        resp.json().await.map_err(|e| format!("agent status parse failed: {e}"))
    }

    /// POST the agent's /provider with the given JSON body. Body shape (one of):
    /// `{ "credentials": "...", "model"?: "..." }` (Claude),
    /// `{ "openrouter_key": "...", "openrouter_model": "..." }` (OpenRouter), or
    /// `{ "model": "..." }` (change model only, keep current provider).
    pub async fn set(&self, body: &serde_json::Value) -> Result<(), String> {
        let (port, token) = self.port_and_token()?;
        let resp = self.http_client
            .post(format!("http://127.0.0.1:{port}/provider"))
            .header("X-Agent-Token", token)
            .json(body)
            .timeout(SET_TIMEOUT)
            .send()
            .await
            .map_err(|e| format!("agent /provider request failed: {e}"))?;
        let status = resp.status();
        if status.is_success() {
            return Ok(());
        }
        let body_text = resp.text().await.unwrap_or_default();
        Err(format!("agent /provider returned HTTP {status}: {body_text}"))
    }

    fn port_and_token(&self) -> Result<(u16, String), String> {
        let (port, token) = read_agent_port_and_token(&self.name, self.agents_dir);
        match (port, token) {
            (Some(p), Some(t)) => Ok((p, t)),
            _ => Err(format!("agent '{}' missing port/token (env file not yet written)", self.name)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn setup_complete_defaults_true_when_absent() {
        // Older agents predate the field; absence must not strand them in SettingUp.
        let s: ProviderStatus = serde_json::from_str(r#"{"state":"authenticated","kind":"claude"}"#).unwrap();
        assert!(s.setup_complete);
    }

    #[test]
    fn setup_complete_parsed_when_present() {
        let s: ProviderStatus =
            serde_json::from_str(r#"{"state":"authenticated","kind":"openrouter","setup_complete":false}"#).unwrap();
        assert!(!s.setup_complete);
    }
}
