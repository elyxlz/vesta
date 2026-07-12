use std::io::{BufRead, IsTerminal, Write};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use ureq::http::Response;
use ureq::Body;

use crate::common::{
    AuthFlowResponse, BackupInfo, ListEntry, MountEntry, ServerConfig, StartAllResult, StatusJson,
};

const HTTP_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// Bounds time-to-headers only (recv_response); SSE streams and long bodies stay unbounded.
const HTTP_RESPONSE_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(serde::Serialize, serde::Deserialize)]
struct MountsBody {
    mounts: Vec<MountEntry>,
}

// ── TLS fingerprint verification ────────────────────────────────

fn make_rustls_config(fingerprint: String) -> Arc<rustls::ClientConfig> {
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
    expected: String,
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
        let actual = cert_fingerprint(end_entity.as_ref());

        match fingerprint_match(&self.expected, &actual) {
            Ok(()) => Ok(rustls::client::danger::ServerCertVerified::assertion()),
            Err(msg) => Err(rustls::Error::General(msg)),
        }
    }
    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &rustls::pki_types::CertificateDer<'_>,
        dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        rustls::crypto::verify_tls12_signature(
            message,
            cert,
            dss,
            &rustls::crypto::ring::default_provider().signature_verification_algorithms,
        )
    }
    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &rustls::pki_types::CertificateDer<'_>,
        dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        rustls::crypto::verify_tls13_signature(
            message,
            cert,
            dss,
            &rustls::crypto::ring::default_provider().signature_verification_algorithms,
        )
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

/// The OpenRouter sign-in body for `update_settings` (PUT /provider): a full provider with the key.
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
#[derive(serde::Deserialize)]
#[serde(untagged)]
pub enum ModelCatalog {
    Static(Vec<String>),
    /// The "live" sentinel (openrouter); the CLI fetches that catalog from its own endpoint instead.
    Live(#[allow(dead_code)] String),
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
            cert_fingerprint: config.cert_fingerprint.clone(),
        })
    }

    pub fn api_key(&self) -> &str {
        &self.api_key
    }

    pub fn cert_fingerprint(&self) -> Option<&str> {
        self.cert_fingerprint.as_deref()
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
    /// boots not_authenticated.
    pub fn logout(&self, name: &str) -> Result<(), String> {
        self.delete_req(&format!("/agents/{name}/provider"))?;
        self.restart_agent(name)
    }

    pub fn get_agent_settings(&self, name: &str) -> Result<serde_json::Value, String> {
        read_json(self.get(&format!("/agents/{name}/settings"))?)
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

    pub fn rebuild_agent(&self, name: &str) -> Result<(), String> {
        // A rebuild may pull a fresh agent image before responding, same as create_agent.
        let request = self
            .authorized(self.agent.post(self.url(&format!("/agents/{name}/rebuild"))))
            .config()
            .timeout_recv_response(None)
            .build();
        self.finish(request.send_empty())?;
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
                        last = status.status.clone();
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

    /// Replace the agent's notification rules (PUT /config with {notification_rules}); the server assigns
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

// ── WebSocket chat (CLI-only) ──────────────────────────────────

const CHAT_READ_TIMEOUT_MS: u64 = 100;

/// How long to keep retrying the chat WebSocket after an unexpected drop before giving up.
/// The agent bounces its in-container WS server on every self-restart (e.g. installing a
/// skill), so a transient drop usually heals within a few seconds once it boots back up.
const CHAT_RECONNECT_WINDOW_SECS: u64 = 90;
/// Delay between reconnect attempts within the window.
const CHAT_RECONNECT_DELAY_MS: u64 = 1500;

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

type ChatSocket = tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>;

/// How a single chat session ended.
enum SessionEnd {
    /// The server closed the stream cleanly (agent stopped) — exit without retrying.
    Closed,
    /// The connection dropped unexpectedly — the agent is likely restarting, so reconnect.
    /// `unsent` carries a message the drop swallowed mid-send, already rendered on screen,
    /// so the reconnect loop can deliver it on the fresh socket.
    Lost { reason: String, unsent: Option<String> },
}

fn chat_message_frame(text: &str) -> tungstenite::Message {
    tungstenite::Message::Text(serde_json::json!({"type": "message", "text": text}).to_string().into())
}

/// Open one chat WebSocket. A pinned fingerprint gets the same verification as the HTTP
/// client; without one, tungstenite's default connector verifies against native roots.
fn connect_chat_socket(client: &Client, url: &str) -> Result<ChatSocket, String> {
    // Both ring and aws-lc-rs are compiled in, so tungstenite's default rustls config
    // needs a process-level provider picked before the handshake.
    let _ = rustls::crypto::ring::default_provider().install_default();
    let parsed: url::Url = url.parse().map_err(|e| format!("invalid ws url: {e}"))?;
    let host = parsed.host_str().unwrap_or("localhost");
    let port = parsed.port_or_known_default().unwrap_or(443);
    let tcp = std::net::TcpStream::connect((host, port))
        .map_err(|e| format!("ws tcp connect failed: {e}"))?;
    // The read timeout is for the chat read loop (so socket.read() returns to poll typed input),
    // not the handshake. Applying it before client_tls_with_config kills the blocking TLS+WS
    // handshake over any non-local link (e.g. a cloudflare tunnel): a handshake read that exceeds
    // CHAT_READ_TIMEOUT_MS returns WouldBlock and tungstenite aborts with "Interrupted handshake".
    // So hand the handshake a timeout-free socket, then set the timeout via a clone (the dup'd fd
    // shares the same kernel socket, so SO_RCVTIMEO applies to the moved-in stream too).
    let timeout_handle = tcp
        .try_clone()
        .map_err(|e| format!("failed to clone ws socket: {e}"))?;
    let connector = client
        .cert_fingerprint()
        .map(|fp| tungstenite::Connector::Rustls(make_rustls_config(fp.to_string())));
    let (socket, _) = tungstenite::client_tls_with_config(url.to_string(), tcp, None, connector)
        .map_err(|e| format!("ws connect failed: {e}"))?;
    timeout_handle
        .set_read_timeout(Some(Duration::from_millis(CHAT_READ_TIMEOUT_MS)))
        .map_err(|e| format!("failed to set read timeout: {e}"))?;
    Ok(socket)
}

/// Pump one connected socket until it ends. `render_history` is false on reconnect so the
/// replayed backlog isn't printed twice. Input typed while disconnected stays buffered in `rx`
/// and is flushed here once the socket is live again.
fn run_chat_session(
    socket: &mut ChatSocket,
    rx: &std::sync::mpsc::Receiver<String>,
    name: &str,
    color: bool,
    render_history: bool,
) -> SessionEnd {
    loop {
        if let Ok(input) = rx.try_recv() {
            if !input.is_empty() {
                if color {
                    print!("\x1b[1A\x1b[2K\r");
                }
                render_line(&time_now_utc(), "you", ANSI_YOU, &input, color);
                std::io::stdout().flush().ok();
                if let Err(send_err) = socket.send(chat_message_frame(&input)) {
                    return SessionEnd::Lost {
                        reason: format!("connection lost while sending: {send_err}"),
                        unsent: Some(input),
                    };
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
                        Some("snapshot") if render_history => {
                            if let Some(events) = msg["chat"]["events"].as_array() {
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
            Ok(tungstenite::Message::Close(_)) | Err(tungstenite::Error::ConnectionClosed) => {
                return SessionEnd::Closed;
            }
            Ok(_) => {}
            Err(tungstenite::Error::Io(ref e))
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(read_err) => {
                return SessionEnd::Lost {
                    reason: format!("connection lost: {read_err}"),
                    unsent: None,
                }
            }
        }
    }
}

/// Retry connecting for up to `CHAT_RECONNECT_WINDOW_SECS` after a drop. Returns the fresh
/// socket once the agent is reachable again, or `None` if the window elapses first.
fn reconnect_chat_socket(client: &Client, url: &str, name: &str, reason: &str) -> Option<ChatSocket> {
    eprintln!("{reason}; agent may be restarting, reconnecting to {name}...");
    let deadline = Instant::now() + Duration::from_secs(CHAT_RECONNECT_WINDOW_SECS);
    while Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(CHAT_RECONNECT_DELAY_MS));
        if let Ok(socket) = connect_chat_socket(client, url) {
            eprintln!("reconnected to {name}.");
            return Some(socket);
        }
    }
    None
}

/// Connect to Chat WebSocket and run interactive chat (CLI-only).
pub fn chat(client: &Client, name: &str) -> Result<(), String> {
    let url = format!(
        "{}/agents/{}/ws?token={}",
        ws_base_url(&client.base_url),
        name,
        client.api_key()
    );

    let mut socket = connect_chat_socket(client, &url)?;

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

    // The agent bounces its WS server on every self-restart. Rather than crash on the drop,
    // keep the session alive across restarts: run until the socket ends, then reconnect within
    // a bounded window. Only a clean server close (agent stopped) or an exhausted window exits.
    let mut render_history = true;
    loop {
        match run_chat_session(&mut socket, &rx, name, color, render_history) {
            SessionEnd::Closed => return Ok(()),
            SessionEnd::Lost { reason, unsent } => loop {
                match reconnect_chat_socket(client, &url, name, &reason) {
                    Some(fresh) => socket = fresh,
                    None => return Err(reason),
                }
                render_history = false;
                // The lost message is already on screen as sent; deliver it silently on the
                // fresh socket, and if that send also dies, retry through another reconnect.
                let resent = match &unsent {
                    Some(text) => socket.send(chat_message_frame(text)).is_ok(),
                    None => true,
                };
                if resent {
                    break;
                }
            },
        }
    }
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
    fn connect_chat_socket_rejects_invalid_url() {
        let err = connect_chat_socket(&test_client(), "not a ws url").unwrap_err();
        assert!(err.contains("invalid ws url"), "got: {err}");
    }

    #[test]
    fn connect_chat_socket_errors_on_unreachable_port_without_panicking() {
        // Port 1 on loopback refuses fast — the helper must surface an Err, never panic,
        // so the reconnect loop can keep retrying.
        let err = connect_chat_socket(&test_client(), "wss://127.0.0.1:1/agents/x/ws?token=tok").unwrap_err();
        assert!(err.contains("ws tcp connect failed") || err.contains("ws connect failed"), "got: {err}");
    }

    #[test]
    fn connect_chat_socket_survives_a_slow_handshake() {
        // Regression: the chat read-loop timeout (CHAT_READ_TIMEOUT_MS) must not be applied to the
        // socket until *after* the handshake. A server slower than that timeout (here a cloudflare
        // tunnel's worth of latency, simulated) used to make the handshake read return WouldBlock,
        // surfacing as "ws connect failed: Interrupted handshake (WouldBlock)".
        let handshake_delay = Duration::from_millis(CHAT_READ_TIMEOUT_MS * 3);
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind loopback");
        let port = listener.local_addr().expect("local addr").port();
        let server = std::thread::spawn(move || {
            let (stream, _) = listener.accept().expect("accept");
            // Stall before reading/answering the upgrade, longer than the read-loop timeout.
            std::thread::sleep(handshake_delay);
            // tungstenite drives the server side of the handshake (correct Sec-WebSocket-Accept).
            let _ws = tungstenite::accept(stream).expect("server handshake");
            std::thread::sleep(Duration::from_millis(50));
        });

        let url = format!("ws://127.0.0.1:{port}/agents/x/ws?token=tok");
        let socket = connect_chat_socket(&test_client(), &url).expect("handshake should survive a slow server");
        drop(socket);
        server.join().expect("server thread");
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
