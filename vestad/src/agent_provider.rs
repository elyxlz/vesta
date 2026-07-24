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

/// The agent's `GET /status`: the readiness slice vestad needs to gate Alive vs `SettingUp` vs
/// `NotAuthenticated`. Distinct from the provider config it relays to the app via `GET /provider`.
#[derive(Deserialize, Debug)]
pub struct AgentStatusView {
    /// Defaults to `true` so a response missing the field isn't mislabeled `NotAuthenticated`; a
    /// not-authenticated agent reports `authed: false` explicitly.
    #[serde(default = "default_true")]
    pub authed: bool,
    /// Same back-compat default so a response without the field isn't stuck in `SettingUp`.
    #[serde(default = "default_true")]
    pub setup_complete: bool,
    /// Whether the agent has a provider chosen at all. Defaults to `true` for back-compat so an older
    /// agent that omits the field isn't mislabeled Unprovisioned; a fresh/signed-out agent reports
    /// `provider_configured: false` explicitly.
    #[serde(default = "default_true")]
    pub provider_configured: bool,
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
    pub fn new(
        http_client: &'a reqwest::Client,
        agents_dir: &'a Path,
        name: impl Into<String>,
    ) -> Self {
        Self {
            http_client,
            agents_dir,
            name: name.into(),
        }
    }

    /// GET the agent's /status readiness slice to gate its Alive status. Returns Err on network
    /// failure, missing env file (agent not yet provisioned), non-2xx, or timeout.
    pub async fn status(&self) -> Result<AgentStatusView, String> {
        self.get_json("/status", STATUS_TIMEOUT, "status").await
    }

    /// GET the agent's /config (prefs; vestad relays it to the app).
    pub async fn get_config(&self) -> Result<serde_json::Value, String> {
        self.get_json("/config", STATUS_TIMEOUT, "/config").await
    }

    /// GET the agent's /provider (active provider; vestad relays it to the app).
    pub async fn get_provider(&self) -> Result<serde_json::Value, String> {
        self.get_json("/provider", STATUS_TIMEOUT, "/provider")
            .await
    }

    /// PUT a prefs body to the agent's /config. Write only — caller restarts to apply.
    pub async fn put_config(&self, body: &serde_json::Value) -> Result<(), String> {
        self.write("PUT", "/config", Some(body)).await
    }

    /// PUT a provider body to /provider (sign in / switch). Write only — caller restarts to apply.
    pub async fn put_provider(&self, body: &serde_json::Value) -> Result<(), String> {
        self.write("PUT", "/provider", Some(body)).await
    }

    /// PATCH /provider (change model / context / thinking). Write only — caller restarts.
    pub async fn patch_provider(&self, body: &serde_json::Value) -> Result<(), String> {
        self.write("PATCH", "/provider", Some(body)).await
    }

    /// DELETE /provider (sign out, clearing credentials). Write only — caller restarts.
    pub async fn delete_provider(&self) -> Result<(), String> {
        self.write("DELETE", "/provider", None).await
    }

    /// Shared GET-and-parse helper for the relayed read endpoints.
    async fn get_json<T: serde::de::DeserializeOwned>(
        &self,
        path: &str,
        timeout: Duration,
        label: &str,
    ) -> Result<T, String> {
        let (port, token) = self.port_and_token()?;
        let resp = self
            .http_client
            .get(format!("http://127.0.0.1:{port}{path}"))
            .header("X-Agent-Token", token)
            .timeout(timeout)
            .send()
            .await
            .map_err(|e| format!("agent {label} request failed: {e}"))?;
        if !resp.status().is_success() {
            return Err(format!("agent {label} returned HTTP {}", resp.status()));
        }
        resp.json()
            .await
            .map_err(|e| format!("agent {label} parse failed: {e}"))
    }

    /// Shared body for the write endpoints: send `method path` with the agent token and an optional
    /// JSON body, mapping any non-2xx (or transport error) to a descriptive string.
    async fn write(
        &self,
        method: &str,
        path: &str,
        body: Option<&serde_json::Value>,
    ) -> Result<(), String> {
        let (port, token) = self.port_and_token()?;
        let url = format!("http://127.0.0.1:{port}{path}");
        let mut req = match method {
            "PUT" => self.http_client.put(url),
            "PATCH" => self.http_client.patch(url),
            "DELETE" => self.http_client.delete(url),
            other => return Err(format!("unsupported agent write method {other}")),
        }
        .header("X-Agent-Token", token)
        .timeout(SET_TIMEOUT);
        if let Some(body) = body {
            req = req.json(body);
        }
        let resp = req
            .send()
            .await
            .map_err(|e| format!("agent {path} request failed: {e}"))?;
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
            _ => Err(format!(
                "agent '{}' missing port/token (env file not yet written)",
                self.name
            )),
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
    fn authed_defaults_true_when_field_absent() {
        // A response without the `authed` key must not be mislabeled NotAuthenticated.
        let s: AgentStatusView = serde_json::from_str(r#"{"model":"opus"}"#).unwrap();
        assert!(s.authed && s.setup_complete);
    }

    #[test]
    fn parses_authed_and_setup_complete_ignoring_rest_of_provider() {
        // GET /status carries the two gating fields; vestad parses them and ignores any extras.
        let s: AgentStatusView = serde_json::from_str(
            r#"{"authed":true,"kind":"openrouter","setup_complete":false,"model":"deepseek/v4"}"#,
        )
        .unwrap();
        assert!(s.authed && !s.setup_complete);
    }
}
