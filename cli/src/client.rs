use std::io::BufRead;
use std::sync::Arc;
use std::time::{Duration, Instant};
use ureq::http::Response;
use ureq::Body;

use crate::common::{
    AuthFlowResponse, BackupInfo, ListEntry, MountEntry, ServerConfig, StartAllResult, StatusJson,
};

const HTTP_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// Bounds time-to-headers only (`recv_response`); SSE streams and long bodies stay unbounded.
const HTTP_RESPONSE_TIMEOUT: Duration = Duration::from_mins(5);

#[derive(serde::Serialize, serde::Deserialize)]
struct MountsBody {
    mounts: Vec<MountEntry>,
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
        503 => error_msg.unwrap_or_else(|| "vestad is not reachable, is it running?".into()),
        _ => error_msg.unwrap_or_else(|| format!("server error ({status})")),
    }
}

fn read_json<T: serde::de::DeserializeOwned>(resp: Response<Body>) -> Result<T, String> {
    resp.into_body().read_json().map_err(|e| format!("parse error: {e}"))
}

fn require_str(value: &serde_json::Value, field: &str) -> Result<String, String> {
    value[field].as_str().map(str::to_string).ok_or_else(|| format!("response missing {field}"))
}

/// The Claude sign-in body for `update_settings` (PUT /provider); `update_settings` folds in the model.
pub fn claude_auth(credentials: &str) -> serde_json::Value {
    serde_json::json!({ "kind": "claude", "credentials": credentials })
}

/// The `OpenRouter` sign-in body for `update_settings` (PUT /provider): a full provider with the key.
pub fn openrouter_auth(args: &OpenRouterArgs) -> serde_json::Value {
    serde_json::json!({ "kind": "openrouter", "model": args.model, "key": args.key })
}

/// The fields an `update_settings` call may change; unset fields are left as they are.
#[derive(Debug, Default)]
pub struct SettingsUpdate<'a> {
    pub auth: Option<serde_json::Value>,
    pub model: Option<&'a str>,
    pub max_context_tokens: Option<u64>,
    pub timezone: Option<&'a str>,
}

fn require_bool(value: &serde_json::Value, field: &str) -> Result<bool, String> {
    value[field].as_bool().ok_or_else(|| format!("response missing {field}"))
}

fn map_error(host: &str, e: ureq::Error) -> String {
    match e {
        ureq::Error::ConnectionFailed | ureq::Error::Io(_) => {
            format!("server not reachable at {host}, run 'vesta connect <host>' to point at a different one")
        }
        other => format!("request failed: {other}"),
    }
}

fn extract_server_error(body: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    v["error"].as_str().map(std::string::ToString::to_string)
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
}

/// `OpenRouter` creation args, set when an agent runs on an `OpenRouter` API key instead of a Claude account.
pub struct OpenRouterArgs {
    pub key: String,
    pub model: String,
}

/// A model entry from `OpenRouter`'s top-weekly list, used to populate the
/// interactive model picker in `vesta setup`.
#[derive(serde::Deserialize)]
pub struct OpenRouterModel {
    pub slug: String,
    pub label: String,
    pub author: String,
    /// USD per million prompt/completion/cache-read tokens, when `OpenRouter` reports it.
    #[serde(default)]
    pub input_price: Option<f64>,
    #[serde(default)]
    pub output_price: Option<f64>,
    #[serde(default)]
    pub cache_read_price: Option<f64>,
}

#[derive(serde::Deserialize)]
pub struct ContextPreset {
    pub tokens: u64,
    pub label: String,
    pub note: String,
}

#[derive(serde::Deserialize)]
pub struct ProviderContext {
    pub default: u64,
    pub presets: Vec<ContextPreset>,
}

/// A provider's model catalog: explicit slugs (claude) or "live" (openrouter, fetched separately).
pub enum ModelCatalog {
    Static(Vec<String>),
    /// The "live" sentinel (openrouter); the CLI fetches that catalog from its own endpoint instead.
    Live,
}

impl<'de> serde::Deserialize<'de> for ModelCatalog {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct CatalogVisitor;
        impl<'de> serde::de::Visitor<'de> for CatalogVisitor {
            type Value = ModelCatalog;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("a list of model slugs or the \"live\" sentinel string")
            }

            fn visit_str<E: serde::de::Error>(self, _sentinel: &str) -> Result<Self::Value, E> {
                Ok(ModelCatalog::Live)
            }

            fn visit_seq<A: serde::de::SeqAccess<'de>>(self, seq: A) -> Result<Self::Value, A::Error> {
                serde::Deserialize::deserialize(serde::de::value::SeqAccessDeserializer::new(seq))
                    .map(ModelCatalog::Static)
            }
        }
        deserializer.deserialize_any(CatalogVisitor)
    }
}

#[derive(serde::Deserialize)]
pub struct ProviderEntry {
    pub models: ModelCatalog,
    pub context: ProviderContext,
}

/// The provider manifest (`GET /manifest`): per-provider catalog + new-agent defaults, generated from
/// the agent's models. The CLI reads model/context choices from here so it keeps no hardcoded copy.
#[derive(serde::Deserialize)]
pub struct Manifest {
    pub providers: std::collections::HashMap<String, ProviderEntry>,
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
            .timeout_connect(Some(HTTP_CONNECT_TIMEOUT))
            .timeout_recv_response(Some(HTTP_RESPONSE_TIMEOUT))
            .tls_config(tls_config)
            .build()
            .new_agent();
        Ok(Self {
            agent,
            base_url: config.url.clone(),
            api_key: config.api_key.clone(),
        })
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }

    /// Attach the bearer auth header. Generic over the request's body typestate so
    /// the GET/DELETE (no body) and POST/PUT (with body) builders share one site.
    fn authorized<B>(&self, builder: ureq::RequestBuilder<B>) -> ureq::RequestBuilder<B> {
        builder.header("Authorization", &format!("Bearer {}", self.api_key))
    }

    /// The one place the request error pipeline lives: surface a transport failure
    /// via `map_error`, then reject any non-2xx status.
    fn finish(&self, result: Result<Response<Body>, ureq::Error>) -> Result<Response<Body>, String> {
        check_response(result.map_err(|e| map_error(&self.base_url, e))?)
    }

    fn get(&self, path: &str) -> Result<Response<Body>, String> {
        self.finish(self.authorized(self.agent.get(self.url(path))).call())
    }

    fn post(&self, path: &str) -> Result<Response<Body>, String> {
        self.finish(self.authorized(self.agent.post(self.url(path))).send_empty())
    }

    fn post_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        self.finish(self.authorized(self.agent.post(self.url(path))).send_json(body))
    }

    fn delete_req(&self, path: &str) -> Result<Response<Body>, String> {
        self.finish(self.authorized(self.agent.delete(self.url(path))).call())
    }

    fn put_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        self.finish(self.authorized(self.agent.put(self.url(path))).send_json(body))
    }

    fn patch_json(&self, path: &str, body: &serde_json::Value) -> Result<Response<Body>, String> {
        self.finish(self.authorized(self.agent.patch(self.url(path))).send_json(body))
    }

    pub fn health(&self) -> Result<(), String> {
        self.finish(self.agent.get(self.url("/health")).call())?;
        Ok(())
    }

    // Read vestad's cached view of the latest release. vestad polls GitHub on
    // our behalf (with an ETag conditional request), so routing through it keeps
    // every client on one machine from hitting the GitHub API independently.
    pub fn latest_release_tag(&self) -> Result<Option<String>, String> {
        let value: serde_json::Value = read_json(self.get("/version")?)?;
        Ok(extract_latest_version(&value))
    }

    // Force vestad to refresh from GitHub, then return the latest tag. Used by
    // the explicit `vesta update` so it does not act on a stale cached value.
    pub fn check_latest_release_tag(&self) -> Result<Option<String>, String> {
        let value: serde_json::Value = read_json(self.post("/version/check")?)?;
        Ok(extract_latest_version(&value))
    }

    // The version vestad itself is running (the `version` field of `/version`),
    // used to gate the CLI against a mismatched gateway the same way the app does.
    pub fn gateway_version(&self) -> Result<String, String> {
        let value: serde_json::Value = read_json(self.get("/version")?)?;
        match value["version"].as_str() {
            Some(version) => Ok(version.trim().trim_start_matches('v').to_string()),
            None => Err("version response missing 'version'".into()),
        }
    }

    // Ask vestad to self-update to the latest release on its channel. Mirrors the
    // app's "update your gateway" button (POST /gateway/update). vestad restarts on
    // success, so the caller should re-run its command once the daemon is back.
    pub fn update_gateway(&self) -> Result<(), String> {
        self.post("/gateway/update")?;
        Ok(())
    }

    pub fn get_channel(&self) -> Result<String, String> {
        let value: serde_json::Value = read_json(self.get("/gateway/settings")?)?;
        require_str(&value, "channel")
    }

    pub fn set_channel(&self, channel: &str) -> Result<String, String> {
        let value: serde_json::Value = read_json(self.put_json("/gateway/settings", &serde_json::json!({ "channel": channel }))?)?;
        require_str(&value, "channel")
    }

    pub fn get_auto_update(&self) -> Result<bool, String> {
        let value: serde_json::Value = read_json(self.get("/gateway/settings")?)?;
        require_bool(&value, "auto_update")
    }

    pub fn set_auto_update(&self, enabled: bool) -> Result<bool, String> {
        let value: serde_json::Value = read_json(self.put_json("/gateway/settings", &serde_json::json!({ "auto_update": enabled }))?)?;
        require_bool(&value, "auto_update")
    }

    pub fn get_gateway_settings(&self) -> Result<serde_json::Value, String> {
        read_json(self.get("/gateway/settings")?)
    }

    pub fn get_gateway_info(&self) -> Result<serde_json::Value, String> {
        read_json(self.get("/gateway/info")?)
    }

    pub fn list_agents(&self) -> Result<Vec<ListEntry>, String> {
        read_json(self.get("/agents")?)
    }

    pub fn agent_status(&self, name: &str) -> Result<StatusJson, String> {
        read_json(self.get(&format!("/agents/{name}"))?)
    }

    /// Create an empty agent container. Credentials, timezone, and other preferences are sent
    /// separately via `update_settings` once the agent is up (vestad no longer accepts credentials or
    /// timezone at create time — the agent owns its config store).
    pub fn create_agent(&self, name: &str, manage_agent_code: bool) -> Result<String, String> {
        let body = serde_json::json!({"name": name, "manage_agent_code": manage_agent_code});
        // vestad pulls/builds the agent image before responding; a cold multi-GB pull
        // legitimately exceeds any fixed response ceiling.
        let request = self
            .authorized(self.agent.post(self.url("/agents")))
            .config()
            .timeout_recv_response(None)
            .build();
        let v: serde_json::Value = read_json(self.finish(request.send_json(&body))?)?;
        Ok(v["name"].as_str().unwrap_or(name).to_string())
    }

    /// Apply a settings change in one go, then restart once to apply. A sign-in body (`auth`, from
    /// `claude_auth`/`openrouter_auth`) goes to `PUT /provider` with the model/context folded in; a
    /// bare model/context change goes to `PATCH /provider`; timezone goes to `PUT /config`. The writes
    /// don't restart on their own, so a fresh agent gets its provider in a single race-free restart.
    /// No-op (no restart) if nothing is set.
    pub fn update_settings(&self, name: &str, update: SettingsUpdate) -> Result<(), String> {
        let SettingsUpdate { auth, model, max_context_tokens, timezone } = update;
        let mut changed = false;
        if let Some(mut signin) = auth {
            // Pre-flight: fail fast on a malformed Claude credentials blob locally, rather than after a
            // round-trip + agent restart that surfaces as an opaque BAD_GATEWAY.
            if let Some(creds) = signin.get("credentials").and_then(|c| c.as_str()) {
                serde_json::from_str::<serde_json::Value>(creds).map_err(|e| format!("invalid credentials JSON: {e}"))?;
            }
            if let Some(model) = model {
                signin["model"] = serde_json::json!(model);
            }
            if let Some(ctx) = max_context_tokens {
                signin["max_context_tokens"] = serde_json::json!(ctx);
            }
            self.put_json(&format!("/agents/{name}/provider"), &signin)?;
            changed = true;
        } else {
            let mut patch = serde_json::Map::new();
            if let Some(model) = model {
                patch.insert("model".to_string(), serde_json::json!(model));
            }
            if let Some(ctx) = max_context_tokens {
                patch.insert("max_context_tokens".to_string(), serde_json::json!(ctx));
            }
            if !patch.is_empty() {
                self.patch_json(&format!("/agents/{name}/provider"), &serde_json::Value::Object(patch))?;
                changed = true;
            }
        }
        if let Some(tz) = timezone {
            self.put_json(&format!("/agents/{name}/config"), &serde_json::json!({ "timezone": tz }))?;
            changed = true;
        }
        if changed { self.restart_agent(name) } else { Ok(()) }
    }

    /// The agent's active provider + derived `{authed, kind, ...}`, proxied from its `GET /provider`.
    pub fn get_provider(&self, name: &str) -> Result<serde_json::Value, String> {
        read_json(self.get(&format!("/agents/{name}/provider"))?)
    }

    /// Sign out: clear the agent's provider credentials (`DELETE /provider`), then restart so it
    /// boots `not_authenticated`.
    pub fn logout(&self, name: &str) -> Result<(), String> {
        self.delete_req(&format!("/agents/{name}/provider"))?;
        self.restart_agent(name)
    }

    pub fn start_agent(&self, name: &str) -> Result<(), String> {
        self.post(&format!("/agents/{name}/start"))?;
        Ok(())
    }

    pub fn start_all(&self) -> Result<Vec<StartAllResult>, String> {
        let response: StartAllResponse = read_json(self.post("/agents/start")?)?;
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
        consume_sse_log_stream(std::io::BufReader::new(resp.into_body().into_reader()), "gateway_stopped", None)
    }

    pub fn destroy_agent(&self, name: &str) -> Result<(), String> {
        self.delete_req(&format!("/agents/{name}"))?;
        Ok(())
    }

    /// Poll until status is `alive`, `not_authenticated`, or `unprovisioned`. Used right after
    /// `create_agent` to know the agent's HTTP server is up and ready to accept
    /// `PUT /agents/{name}/config` — a brand-new empty agent reports `unprovisioned`
    /// (no provider chosen) until the provider is provisioned.
    pub fn wait_until_running(&self, name: &str, timeout: Duration) -> Result<(), String> {
        self.wait_for_status(name, timeout, &["alive", "not_authenticated", "unprovisioned"], "HTTP server", |_| {})
    }

    /// Poll `/agents/{name}` until `status == "alive"` or the deadline passes.
    /// Terminal non-alive states (`not_found`, dead, stopped, `not_authenticated`)
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
        on_change: impl FnMut(&str),
    ) -> Result<(), String> {
        self.wait_for_status(name, timeout, &["alive"], "ready", on_change)
    }

    /// Poll `/agents/{name}` until the status enters `ready`, hits a terminal state,
    /// or the deadline passes. `ready` is checked before the terminal set, so a state
    /// like `not_authenticated` can be a success for one caller and a failure for
    /// another (it is terminal only when not listed in `ready`). `on_change` fires on
    /// every distinct status so callers can surface progress.
    fn wait_for_status(
        &self,
        name: &str,
        timeout: Duration,
        ready: &[&str],
        wait_label: &str,
        mut on_change: impl FnMut(&str),
    ) -> Result<(), String> {
        const TERMINAL_STATES: [&str; 5] = ["not_found", "dead", "stopped", "not_authenticated", "unprovisioned"];
        let deadline = Instant::now() + timeout;
        let mut backoff = Duration::from_millis(200);
        let mut last = String::new();
        loop {
            // A transient transport error is not terminal: a missing agent comes back as a
            // 200 with status "not_found", so an Err here is only the network blipping.
            match self.agent_status(name) {
                Ok(status) => {
                    if status.status != last {
                        on_change(&status.status);
                        last.clone_from(&status.status);
                    }
                    if ready.contains(&status.status.as_str()) {
                        return Ok(());
                    }
                    if TERMINAL_STATES.contains(&status.status.as_str()) {
                        return Err(format!("{}: {}", name, status.status));
                    }
                    if Instant::now() >= deadline {
                        return Err(format!("{}: timeout waiting for {} (status: {})", name, wait_label, status.status));
                    }
                }
                Err(poll_err) => {
                    if Instant::now() >= deadline {
                        return Err(format!("{name}: timeout waiting for {wait_label} (last error: {poll_err})"));
                    }
                }
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(Duration::from_secs(1));
        }
    }

    // Agent-less OAuth — runs the PKCE dance independent of any agent. Used by
    // `vesta setup` (pre-create) and `vesta auth <name>` (post-create reauth),
    // followed by either POST /agents or PUT /agents/{name}/config.
    pub fn start_auth_standalone(&self) -> Result<AuthFlowResponse, String> {
        read_json(self.post("/providers/claude/oauth/start")?)
    }

    pub fn complete_auth_standalone(&self, session_id: &str, code: &str) -> Result<String, String> {
        let body = serde_json::json!({"session_id": session_id, "code": code});
        let v: serde_json::Value = read_json(self.post_json("/providers/claude/oauth/complete", &body)?)?;
        require_str(&v, "credentials")
    }

    pub fn validate_openrouter_key(&self, key: &str) -> Result<(), String> {
        let body = serde_json::json!({"key": key});
        self.post_json("/providers/openrouter/validate-key", &body)?;
        Ok(())
    }

    pub fn fetch_top_openrouter_models(&self) -> Result<Vec<OpenRouterModel>, String> {
        read_json(self.get("/providers/openrouter/models/top")?)
    }

    pub fn fetch_manifest(&self) -> Result<Manifest, String> {
        read_json(self.get("/manifest")?)
    }


    pub fn create_backup(&self, name: &str) -> Result<BackupInfo, String> {
        let resp = self.post(&format!("/agents/{name}/backups"))?;
        let data = read_sse_result(resp)?;
        serde_json::from_str(&data).map_err(|e| format!("parse error: {e}"))
    }

    pub fn list_backups(&self, name: &str) -> Result<Vec<BackupInfo>, String> {
        read_json(self.get(&format!("/agents/{name}/backups"))?)
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
        let value: serde_json::Value = read_json(self.get("/gateway/settings")?)?;
        Ok(value["auto_backup"].clone())
    }

    pub fn set_auto_backup_settings(&self, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        let value: serde_json::Value = read_json(self.put_json("/gateway/settings", &serde_json::json!({ "auto_backup": body }))?)?;
        Ok(value["auto_backup"].clone())
    }

    pub fn list_all_backups(&self) -> Result<Vec<BackupInfo>, String> {
        read_json(self.get("/backups")?)
    }

    pub fn get_agent_mounts(&self, name: &str) -> Result<Vec<MountEntry>, String> {
        let body: MountsBody = read_json(self.get(&format!("/agents/{name}/mounts"))?)?;
        Ok(body.mounts)
    }

    pub fn set_agent_mounts(&self, name: &str, mounts: Vec<MountEntry>) -> Result<serde_json::Value, String> {
        let body = serde_json::to_value(MountsBody { mounts }).map_err(|e| e.to_string())?;
        read_json(self.put_json(&format!("/agents/{name}/mounts"), &body)?)
    }

    pub fn get_agent_backup_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        read_json(self.get(&format!("/agents/{name}/settings/backup"))?)
    }

    pub fn set_agent_backup_settings(&self, name: &str, body: &serde_json::Value) -> Result<serde_json::Value, String> {
        read_json(self.put_json(&format!("/agents/{name}/settings/backup"), body)?)
    }

    pub fn delete_agent_backup_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        read_json(self.delete_req(&format!("/agents/{name}/settings/backup"))?)
    }

    pub fn get_agent_constitution(&self, name: &str) -> Result<String, String> {
        let body: serde_json::Value = read_json(self.get(&format!("/agents/{name}/constitution"))?)?;
        require_str(&body, "content")
    }

    pub fn set_agent_constitution(&self, name: &str, content: &str) -> Result<(), String> {
        let body = serde_json::json!({ "content": content });
        self.put_json(&format!("/agents/{name}/constitution"), &body)?;
        Ok(())
    }

    pub fn stream_logs(&self, name: &str, tail: u64) -> Result<(), String> {
        let resp = self.get(&format!("/agents/{name}/logs?tail={tail}"))?;
        consume_sse_log_stream(std::io::BufReader::new(resp.into_body().into_reader()), "agent_stopped", Some("agent stopped"))
    }

    /// The agent's notification interrupt rules, read from its GET /config (the `notification_rules`
    /// array; empty when absent). A notification with no matching rule interrupts.
    pub fn get_notification_rules(&self, name: &str) -> Result<Vec<serde_json::Value>, String> {
        let config: serde_json::Value = read_json(self.get(&format!("/agents/{name}/config"))?)?;
        Ok(config["notification_rules"].as_array().cloned().unwrap_or_default())
    }

    /// Replace the agent's notification rules (PUT /config with {`notification_rules`}); the server assigns
    /// ids to any missing one and stores rules canonically. Live — applied on the agent's next monitor
    /// tick, no restart. Ignores the `{ok: true}` body.
    pub fn set_notification_rules(&self, name: &str, rules: &[serde_json::Value]) -> Result<(), String> {
        self.put_json(&format!("/agents/{name}/config"), &serde_json::json!({ "notification_rules": rules }))?;
        Ok(())
    }

}

fn consume_sse_log_stream(reader: impl BufRead, stop_event: &str, stop_message: Option<&str>) -> Result<(), String> {
    for line in reader.lines() {
        let line = line.map_err(|e| format!("read error: {e}"))?;
        if let Some(data) = line.strip_prefix("data:") {
            println!("{}", data.trim_start());
        } else if let Some(event) = line.strip_prefix("event:") {
            if event.trim() == stop_event {
                if let Some(msg) = stop_message {
                    eprintln!("{msg}");
                }
                return Ok(());
            }
        }
    }
    Err("log stream closed unexpectedly".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_client() -> Client {
        Client::new(&ServerConfig {
            url: "https://127.0.0.1:1".to_string(),
            api_key: "tok".to_string(),
            cert_fingerprint: None,
            cert_pem: None,
        })
        .expect("client builds")
    }

    #[test]
    fn wait_for_status_treats_poll_errors_as_transient_until_the_deadline() {
        // An unreachable server is a transport blip, not a terminal state: the wait keeps
        // polling and only reports the failure once the deadline passes.
        let err = test_client()
            .wait_until_alive("ghost", Duration::from_millis(300))
            .unwrap_err();
        assert!(err.contains("timeout waiting for ready"), "got: {err}");
        assert!(err.contains("server not reachable"), "got: {err}");
    }

    #[test]
    fn consume_sse_log_stream_requires_the_stop_event() {
        struct Case {
            stream: &'static str,
            ok: bool,
        }
        let cases = [
            // Stop event without and with the SSE-valid space after the colon.
            Case { stream: "data: hello\nevent:agent_stopped\ndata: \n\n", ok: true },
            Case { stream: "data: hello\nevent: agent_stopped\ndata: \n\n", ok: true },
            // A longer event name must not match, and a dropped stream is an error.
            Case { stream: "data: hello\nevent: agent_stopped_late\ndata: \n\n", ok: false },
            Case { stream: "data: hello\n", ok: false },
        ];
        for case in cases {
            let result = consume_sse_log_stream(case.stream.as_bytes(), "agent_stopped", None);
            assert_eq!(result.is_ok(), case.ok, "stream: {:?} got: {result:?}", case.stream);
        }
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
            Case { status: 503, body: None, expected: "vestad is not reachable, is it running?" },
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
    fn deserializes_vestad_api_contract_fixtures() {
        // Cross-language API contract: the fixtures are generated by vestad's own production
        // serializer (serve.rs::api_contract_fixtures_up_to_date). Deserializing each one into
        // the CLI's own response type fails loudly here if vestad renames or drops a field the
        // CLI needs, instead of only surfacing as a runtime parse error against a real vestad.
        // Regenerate: cd vestad && REGEN_API_FIXTURES=1 cargo test -p vestad api_contract
        let raw = include_str!("../tests/fixtures/vestad-api.json");
        let fixtures: serde_json::Value = serde_json::from_str(raw).expect("valid fixture JSON");

        let _status: StatusJson = serde_json::from_value(fixtures["agent_status_json"].clone()).expect("StatusJson");
        let _agents: Vec<ListEntry> = serde_json::from_value(fixtures["agents"].clone()).expect("Vec<ListEntry>");
        let _backups: Vec<BackupInfo> = serde_json::from_value(fixtures["backups"].clone()).expect("Vec<BackupInfo>");
        let _auth: AuthFlowResponse = serde_json::from_value(fixtures["auth_start"].clone()).expect("AuthFlowResponse");
        let _start_all: StartAllResponse = serde_json::from_value(fixtures["start_all"].clone()).expect("StartAllResponse");
    }

}
