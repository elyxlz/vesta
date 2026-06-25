//! Thin HTTP proxy into an agent's config/provider endpoints.
//!
//! Vestad owns NO knowledge of credential file formats or provider parsing —
//! that all lives in the agent's `core/provider.py`. This module is just the
//! plumbing to call the agent's HTTP API authenticated with its agent token.

use std::path::Path;
use std::time::Duration;

use serde::Deserialize;

use crate::docker::read_agent_port_and_token;

/// Short HTTP timeout for the per-status-poll call; a hung agent should not
/// stall vestad's status loop. Status callers treat a timeout as `Starting`.
const STATUS_TIMEOUT: Duration = Duration::from_secs(2);
/// Longer timeout for config writes — the agent does file I/O.
const SET_TIMEOUT: Duration = Duration::from_secs(10);

/// The slice of the agent's `GET /config` that vestad needs to gate Alive vs SettingUp vs
/// NotAuthenticated. The rest of the config is opaque to vestad (it just relays it to the app).
#[derive(Deserialize, Debug)]
pub struct AgentStatusView {
    /// LEGACY(remove-when: no fleet agent runs pre-`/config/auth` core — i.e. every agent's GET /config
    /// reports `authed`): defaults to `true` so an agent still on pre-unification core (whose GET /config
    /// is a plain config dump with no `authed` key) isn't mislabeled NotAuthenticated mid-upgrade. A
    /// new-core not-authenticated agent reports `authed: false` explicitly. The cost is the inverse case
    /// (a genuinely signed-out old-core agent briefly shows Alive), accepted as the smaller, transient
    /// wrong for the common authenticated agent. Drop the default once the fleet has converged.
    #[serde(default = "default_true")]
    pub authed: bool,
    /// Same legacy back-compat default so an older agent that doesn't report the field isn't stuck in `SettingUp`.
    #[serde(default = "default_true")]
    pub setup_complete: bool,
}

fn default_true() -> bool {
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

    /// GET the auth/readiness slice of the agent's /config to gate its Alive status. Returns Err on
    /// network failure, missing env file (agent not yet provisioned), non-2xx, or timeout.
    pub async fn status(&self) -> Result<AgentStatusView, String> {
        let (port, token) = self.port_and_token()?;
        let resp = self.http_client
            .get(format!("http://127.0.0.1:{port}/config"))
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

    /// GET the agent's /config (its current config; vestad relays it to the app).
    pub async fn get_config(&self) -> Result<serde_json::Value, String> {
        let (port, token) = self.port_and_token()?;
        let resp = self.http_client
            .get(format!("http://127.0.0.1:{port}/config"))
            .header("X-Agent-Token", token)
            .timeout(STATUS_TIMEOUT)
            .send()
            .await
            .map_err(|e| format!("agent /config request failed: {e}"))?;
        if !resp.status().is_success() {
            return Err(format!("agent /config returned HTTP {}", resp.status()));
        }
        resp.json().await.map_err(|e| format!("agent /config parse failed: {e}"))
    }

    /// PUT a sparse preferences body to the agent's /config. Write only — caller restarts to apply.
    pub async fn put_config(&self, body: &serde_json::Value) -> Result<(), String> {
        self.write("PUT", "/config", Some(body)).await
    }

    /// PUT credentials to the agent's /config/auth (sign in). Write only — caller restarts to apply.
    pub async fn put_auth(&self, body: &serde_json::Value) -> Result<(), String> {
        self.write("PUT", "/config/auth", Some(body)).await
    }

    /// DELETE the agent's /config/auth (sign out, clearing credentials). Write only — caller restarts.
    pub async fn delete_auth(&self) -> Result<(), String> {
        self.write("DELETE", "/config/auth", None).await
    }

    /// Shared body for the write endpoints: send `method path` with the agent token and an optional
    /// JSON body, mapping any non-2xx (or transport error) to a descriptive string.
    async fn write(&self, method: &str, path: &str, body: Option<&serde_json::Value>) -> Result<(), String> {
        let (port, token) = self.port_and_token()?;
        let url = format!("http://127.0.0.1:{port}{path}");
        let mut req = match method {
            "PUT" => self.http_client.put(url),
            "DELETE" => self.http_client.delete(url),
            other => return Err(format!("unsupported agent write method {other}")),
        }
        .header("X-Agent-Token", token)
        .timeout(SET_TIMEOUT);
        if let Some(body) = body {
            req = req.json(body);
        }
        let resp = req.send().await.map_err(|e| format!("agent {path} request failed: {e}"))?;
        let status = resp.status();
        if status.is_success() {
            return Ok(());
        }
        let body_text = resp.text().await.unwrap_or_default();
        Err(format!("agent {path} returned HTTP {status}: {body_text}"))
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
        let s: AgentStatusView = serde_json::from_str(r#"{"authed":true}"#).unwrap();
        assert!(s.setup_complete);
    }

    #[test]
    fn authed_defaults_true_for_pre_unification_core() {
        // A pre-unification agent's GET /config is just the config dump with no `authed` key; it must
        // not be mislabeled NotAuthenticated mid-upgrade (it defaults Alive until it restarts).
        let s: AgentStatusView = serde_json::from_str(r#"{"agent_model":"opus"}"#).unwrap();
        assert!(s.authed && s.setup_complete);
    }

    #[test]
    fn parses_authed_and_setup_complete_ignoring_rest_of_config() {
        // GET /config carries the whole config; vestad reads only the two gating fields.
        let s: AgentStatusView =
            serde_json::from_str(r#"{"authed":true,"kind":"openrouter","setup_complete":false,"agent_model":"opus"}"#).unwrap();
        assert!(s.authed && !s.setup_complete);
    }
}
