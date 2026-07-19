use std::io::{BufRead, IsTerminal, Write};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
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
    cert_fingerprint: Option<String>,
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

// ── /sync chat DTOs, send-message intent, history tail ──────────

/// The CLI's own minimal mirror of the `/sync` server->client union (spec "Delta catalog").
/// Only the frames chat consumes are modelled; every other `type` (state/agent/notifications/alert
/// and any future addition) folds into `Unknown` and is ignored by rule. No shared crate: this
/// duplicates just the shapes chat reads from vestad/src/sync/protocol.rs.
#[derive(serde::Deserialize, Debug)]
#[serde(tag = "type", rename_all = "snake_case")]
enum SyncFrame {
    Hello { floor: u32 },
    Snapshot { tree: RosterSnapshot },
    Append { agent: String, events: Vec<ChatEvent> },
    Resync { agent: String },
    AgentRemoved { name: String },
    #[serde(other)]
    Unknown,
}

/// The snapshot is tail-less; chat only needs the roster key set to confirm the agent exists.
#[derive(serde::Deserialize, Debug)]
struct RosterSnapshot {
    #[serde(deserialize_with = "deserialize_roster_keys")]
    agents: std::collections::BTreeSet<String>,
}

/// Collect just the roster's agent names, ignoring each node body: chat only needs the key set to
/// confirm an agent exists, so the values never have to be retained or modelled.
fn deserialize_roster_keys<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<std::collections::BTreeSet<String>, D::Error> {
    struct KeysVisitor;
    impl<'de> serde::de::Visitor<'de> for KeysVisitor {
        type Value = std::collections::BTreeSet<String>;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("a map of agent names to nodes")
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
            let mut keys = std::collections::BTreeSet::new();
            while let Some(key) = map.next_key::<String>()? {
                map.next_value::<serde::de::IgnoredAny>()?;
                keys.insert(key);
            }
            Ok(keys)
        }
    }
    deserializer.deserialize_map(KeysVisitor)
}

/// One conversation event as chat renders it. `id` is the events.db rowid (dedup key); `intent_id`
/// is present on the user echo of a send (delivery-truth match); other fields are opaque.
#[derive(serde::Deserialize, Debug)]
struct ChatEvent {
    id: i64,
    #[serde(rename = "type")]
    kind: String,
    #[serde(default)]
    text: Option<String>,
    #[serde(default)]
    ts: Option<String>,
    #[serde(default)]
    intent_id: Option<String>,
}

/// The history page shape (`{events, cursor}`); the cursor is dropped (chat loads one recent page).
#[derive(serde::Deserialize, Debug)]
struct HistoryPage {
    events: Vec<ChatEvent>,
}

const CLI_PROTOCOL: u32 = 1;
const CHAT_TAIL_LIMIT: u32 = 50;

/// A send-message failure the engine branches on without string-matching: retry the same intent id,
/// or surface and stop.
#[derive(Debug)]
enum SendError {
    /// The tap is down (agent restarting/evicted): retry with the SAME `intent_id`.
    Retryable(String),
    /// A non-retryable failure (auth, 4xx, transport): surface and stop retrying.
    Fatal(String),
}

impl std::fmt::Display for SendError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SendError::Retryable(msg) | SendError::Fatal(msg) => f.write_str(msg),
        }
    }
}

impl std::error::Error for SendError {}

/// True when the CLI's protocol is at or above the server's advertised floor.
fn is_compatible(cli_protocol: u32, hello_floor: u32) -> bool {
    cli_protocol >= hello_floor
}

/// A process-unique, strictly increasing send-message intent id. The per-process nonce keeps two
/// concurrent CLI sessions from minting colliding ids (which the agent would dedup as a replay); the
/// zero-padded counter makes ids sort in mint order.
fn next_intent_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    static NONCE: std::sync::OnceLock<u64> = std::sync::OnceLock::new();
    let nonce = *NONCE.get_or_init(|| {
        u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_nanos())).unwrap_or(0)
    });
    let seq = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("cli-{nonce:016x}-{seq:016x}")
}

/// Advance the printed-watermark and report whether this event id is new (`id > last`); dedup keyed
/// on the events.db rowid so a snapshot/append overlap never double-prints a line.
fn should_print(id: i64, last: &mut i64) -> bool {
    if id > *last {
        *last = id;
        true
    } else {
        false
    }
}

/// Classify a send-message response: 2xx means accepted/queued (delivery truth is the append echo
/// carrying the intent id, not this ack), a retryable `503` keeps the composer for a same-intent
/// retry, anything else is fatal. Pure so the mapping is unit-tested without a socket.
fn classify_send(status: u16, body: &str) -> Result<(), SendError> {
    if (200..300).contains(&status) {
        return Ok(());
    }
    let value = serde_json::from_str::<serde_json::Value>(body).ok();
    let error_msg = value.as_ref().and_then(|v| v["error"].as_str()).map(str::to_string);
    let retryable = value.as_ref().and_then(|v| v["retryable"].as_bool()).unwrap_or(false);
    if status == 503 && retryable {
        return Err(SendError::Retryable(error_msg.unwrap_or_else(|| "send unavailable, tap is down".into())));
    }
    Err(SendError::Fatal(error_msg.unwrap_or_else(|| format!("send failed ({status})"))))
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
    /// boots `not_authenticated`.
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

    /// One recent page of the app-chat conversation (`GET /agents/{name}/history`), oldest-to-newest
    /// within the page as the agent serves it; the cursor is dropped (the terminal has no scrollback).
    fn fetch_chat_tail(&self, name: &str) -> Result<Vec<ChatEvent>, String> {
        let page: HistoryPage =
            read_json(self.get(&format!("/agents/{name}/history?channel=app-chat&limit={CHAT_TAIL_LIMIT}"))?)?;
        Ok(page.events)
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

/// How many times a send worker retries a tap-down `503` under the same intent id before reporting
/// the message as not delivered. Times `CHAT_SEND_RETRY_DELAY_MS`, this spans the reconnect window,
/// so a send that raced an agent restart keeps trying for as long as the socket keeps reconnecting.
const CHAT_SEND_RETRIES: u32 = 60;
/// Delay between same-intent send retries while the tap is down.
const CHAT_SEND_RETRY_DELAY_MS: u64 = 1500;

/// The subtle dim glyph trailing an optimistic "you" line until its append echo confirms delivery.
const PENDING_GLYPH: &str = "…";

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
        .map_or(0, |d| d.as_secs());
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

type SyncSocket = tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>;

/// How a single chat session ended.
#[derive(Debug)]
enum SessionEnd {
    /// The server closed the stream cleanly (agent stopped or removed) — exit without retrying.
    Closed,
    /// The connection dropped unexpectedly — the agent is likely restarting, so reconnect. Delivery
    /// no longer rides the socket (the send worker retries over HTTP), so nothing is carried here.
    Lost { reason: String },
}

/// Open one `/sync` WebSocket. A pinned fingerprint gets the same verification as the HTTP
/// client; without one, tungstenite's default connector verifies against native roots.
fn connect_sync_socket(client: &Client, url: &str) -> Result<SyncSocket, String> {
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

/// The optimistic "you" lines shown before their append echo arrives. Delivery truth is the echo
/// carrying the intent id (never the send POST's 200): `clear` drops a line on confirmation or on a
/// terminal send failure. `last` names the most recently printed still-pending line so a confirm
/// arriving right after it can be rewritten in place.
struct Pending {
    lines: std::collections::HashMap<String, PendingLine>,
    last: Option<String>,
}

/// One optimistic line, retained so a confirmation can rewrite it and a failure can name its text.
struct PendingLine {
    text: String,
    time: String,
}

impl Pending {
    fn new() -> Self {
        Self { lines: std::collections::HashMap::new(), last: None }
    }

    /// Record an optimistic line just printed for `intent_id`; it becomes the last line printed.
    fn begin(&mut self, intent_id: String, text: String, time: String) {
        self.lines.insert(intent_id.clone(), PendingLine { text, time });
        self.last = Some(intent_id);
    }

    /// Drop the pending line for `intent_id`, returning it plus whether it was still the last line
    /// printed (so the caller may rewrite it in place). An unknown id is a no-op (`None`).
    fn clear(&mut self, intent_id: &str) -> Option<(PendingLine, bool)> {
        let line = self.lines.remove(intent_id)?;
        let was_last = self.last.as_deref() == Some(intent_id);
        if was_last {
            self.last = None;
        }
        Some((line, was_last))
    }

    /// Note that some non-optimistic output was just printed, so no pending line is "last" anymore.
    fn mark_interposed(&mut self) {
        self.last = None;
    }
}

/// A send worker's report back to the chat loop. A 2xx ack is NOT delivery truth (the append echo
/// is), so a success carries no signal the loop acts on: `error` is `Some` only on a terminal
/// failure, which surfaces as a `-- not delivered --` line and drops the pending entry.
#[derive(Debug)]
struct SendOutcome {
    intent_id: String,
    error: Option<String>,
}

/// Deliver one send-message intent with bounded same-intent retry: a `Retryable` failure (tap down)
/// sleeps and retries under the SAME `intent_id` up to `retries` times, then reports it not
/// delivered; a `Fatal` reports at once; a 2xx reports success (no `error`). Generic over the send
/// call so the retry policy is unit-tested without a socket.
fn drive_send(intent_id: &str, retries: u32, retry_delay: Duration, mut attempt_send: impl FnMut() -> Result<(), SendError>) -> SendOutcome {
    let mut attempts = 0u32;
    loop {
        match attempt_send() {
            Ok(()) => return SendOutcome { intent_id: intent_id.to_string(), error: None },
            Err(SendError::Fatal(msg)) => return SendOutcome { intent_id: intent_id.to_string(), error: Some(msg) },
            Err(SendError::Retryable(msg)) => {
                if attempts >= retries {
                    return SendOutcome { intent_id: intent_id.to_string(), error: Some(msg) };
                }
                attempts += 1;
                std::thread::sleep(retry_delay);
            }
        }
    }
}

/// Deliver a send-message intent over HTTP (`POST /agents/{name}/message` with `intent_id`),
/// classifying the raw status/body via `classify_send` so a retryable `503` (tap down) stays
/// distinct from a fatal failure. A free function (not a `Client` method) so a detached send worker
/// owns cheap clones of the agent + base url + key and delivers off the chat thread.
fn post_message(agent: &ureq::Agent, base_url: &str, api_key: &str, name: &str, text: &str, intent_id: &str) -> Result<(), SendError> {
    let body = serde_json::json!({ "text": text, "intent_id": intent_id });
    let resp = agent
        .post(format!("{base_url}/agents/{name}/message"))
        .header("Authorization", &format!("Bearer {api_key}"))
        .send_json(&body)
        .map_err(|e| SendError::Fatal(map_error(base_url, e)))?;
    let status = resp.status().as_u16();
    let response_body = resp.into_body().read_to_string().unwrap_or_default();
    classify_send(status, &response_body)
}

/// Render an optimistic "you" line, tagged with a subtle dim pending glyph (color only) until the
/// append echo confirms delivery. Reuses `render_line`; the marker rides inside the text argument.
fn render_optimistic(time: &str, text: &str, color: bool) {
    if color {
        render_line(time, "you", ANSI_YOU, &format!("{text} {ANSI_TS}{PENDING_GLYPH}{ANSI_RESET}"), true);
    } else {
        render_line(time, "you", ANSI_YOU, text, false);
    }
}

/// The live wiring a `/sync` session drains alongside the socket: typed lines in, send outcomes
/// back, the pending optimistic lines, and the sink that fires a detached send worker. Bundled so
/// the session signature stays small and the reconnect wrapper hands one handle through unchanged.
struct ChatIo<'a> {
    input: &'a std::sync::mpsc::Receiver<String>,
    outcomes: &'a std::sync::mpsc::Receiver<SendOutcome>,
    pending: &'a mut Pending,
    spawn_send: &'a mut dyn FnMut(String, String),
}

/// Drain every buffered input line: mint an intent id, print the optimistic "you" line (erasing the
/// terminal's own echo on a tty), record it pending, and fire a send worker for it.
fn drain_input(io: &mut ChatIo, color: bool) {
    while let Ok(line) = io.input.try_recv() {
        if line.is_empty() {
            continue;
        }
        let intent_id = next_intent_id();
        let time = time_now_utc();
        if color {
            print!("\x1b[1A\x1b[2K\r");
        }
        render_optimistic(&time, &line, color);
        std::io::stdout().flush().ok();
        io.pending.begin(intent_id.clone(), line.clone(), time);
        (io.spawn_send)(intent_id, line);
    }
}

/// Drain send-worker reports: a terminal failure prints a `-- not delivered --` line and drops the
/// pending entry; a success (no `error`) is not delivery truth (the append echo confirms) and is
/// ignored here.
fn drain_outcomes(io: &mut ChatIo, color: bool) {
    while let Ok(outcome) = io.outcomes.try_recv() {
        if outcome.error.is_none() {
            continue;
        }
        if let Some((line, _)) = io.pending.clear(&outcome.intent_id) {
            if color {
                println!("{ANSI_TS}-- not delivered: {} --{ANSI_RESET}", line.text);
            } else {
                println!("-- not delivered: {} --", line.text);
            }
            io.pending.mark_interposed();
        }
    }
}

/// Retry connecting for up to `CHAT_RECONNECT_WINDOW_SECS` after a drop. Returns the fresh
/// socket once the agent is reachable again, or `None` if the window elapses first.
fn reconnect_chat_socket(client: &Client, url: &str, name: &str, reason: &str) -> Option<SyncSocket> {
    eprintln!("{reason}; agent may be restarting, reconnecting to {name}...");
    let deadline = Instant::now() + Duration::from_secs(CHAT_RECONNECT_WINDOW_SECS);
    while Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(CHAT_RECONNECT_DELAY_MS));
        if let Ok(socket) = connect_sync_socket(client, url) {
            eprintln!("reconnected to {name}.");
            return Some(socket);
        }
    }
    None
}

/// Run `/sync` chat under the bounded reconnect window: a clean close exits `Ok`; a mid-session
/// drop (or a handshake-level transport failure) reconnects within `CHAT_RECONNECT_WINDOW_SECS`,
/// re-running the full hello+snapshot+watch+tail on the fresh socket. The high-water id and pending
/// map persist across the reconnect, so nothing double-prints and in-flight sends still confirm on
/// the fresh echo; an incompatible or missing-agent handshake is fatal.
fn run_chat_with_reconnect(client: &Client, name: &str, url: &str, color: bool, last_id: &mut i64, io: &mut ChatIo) -> Result<(), String> {
    let mut socket = connect_sync_socket(client, url)?;
    loop {
        let mut fetch_tail = || client.fetch_chat_tail(name);
        let reason = match run_sync_session(&mut socket, name, color, last_id, &mut fetch_tail, io) {
            Ok(SessionEnd::Closed) => return Ok(()),
            Ok(SessionEnd::Lost { reason }) | Err(ChatError::Transport(reason)) => reason,
            Err(fatal) => return Err(fatal.to_string()),
        };
        match reconnect_chat_socket(client, url, name, &reason) {
            Some(fresh) => socket = fresh,
            None => return Err(reason),
        }
    }
}

/// Interactive chat over the gateway's `/sync` watch socket: a history tail + high-water seed, an
/// optimistic "you" line confirmed by its append echo (never the POST), a detached send worker
/// retrying tap-down 503s under one intent id, and reconnect-on-drop. Stdin lines in, streamed out.
pub fn chat(client: &Client, name: &str) -> Result<(), String> {
    let url = sync_url(&client.base_url, client.api_key());
    let color = std::io::stdout().is_terminal();
    eprintln!("connected to {name}. type a message and press enter.");

    let (input_tx, input_rx) = std::sync::mpsc::channel::<String>();
    std::thread::spawn(move || {
        let stdin = std::io::stdin();
        let mut line = String::new();
        loop {
            line.clear();
            match stdin.lock().read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if input_tx.send(line.trim().to_string()).is_err() {
                        break;
                    }
                }
            }
        }
    });

    // A send rides HTTP off the chat thread: each optimistic line spawns a detached worker that
    // owns cheap clones of the agent + base url + key, retries the tap-down 503s under its intent
    // id, and reports the outcome back over the channel the loop drains.
    let (outcome_tx, outcome_rx) = std::sync::mpsc::channel::<SendOutcome>();
    let send_ctx = (client.agent.clone(), client.base_url.clone(), client.api_key.clone());
    let worker_name = name.to_string();
    let mut spawn_send = move |intent_id: String, text: String| {
        let (agent, base_url, api_key) = send_ctx.clone();
        let name = worker_name.clone();
        let outcomes = outcome_tx.clone();
        std::thread::spawn(move || {
            let outcome = drive_send(&intent_id, CHAT_SEND_RETRIES, Duration::from_millis(CHAT_SEND_RETRY_DELAY_MS), || {
                post_message(&agent, &base_url, &api_key, &name, &text, &intent_id)
            });
            outcomes.send(outcome).ok();
        });
    };

    let mut pending = Pending::new();
    let mut last_id = 0i64;
    let mut io = ChatIo {
        input: &input_rx,
        outcomes: &outcome_rx,
        pending: &mut pending,
        spawn_send: &mut spawn_send,
    };
    run_chat_with_reconnect(client, name, &url, color, &mut last_id, &mut io)
}

// ── /sync watch engine ─────────────────────────────────────────

fn sync_url(base: &str, api_key: &str) -> String {
    // Static-API-key auth carries no exp, so /sync never closes for expiry: no reauth needed
    // (see plan Decision 2). Token rides the query because the blocking tungstenite handshake
    // takes a URL, not custom headers, and the /sync handler accepts ?token=.
    let token = percent_encoding::utf8_percent_encode(api_key, percent_encoding::NON_ALPHANUMERIC);
    format!("{}/sync?token={token}", ws_base_url(base))
}

/// A fatal chat-connect failure, distinct from an in-session drop (which reconnects). `chat()`
/// surfaces it as its `Result<(), String>` via `map_err`.
#[derive(Debug)]
enum ChatError {
    /// The gateway's protocol floor is above this CLI's protocol: the user must update.
    Incompatible,
    /// The watched agent is absent from the roster snapshot (matches `vesta status` `not_found`).
    NotFound,
    /// A transport failure during the handshake or the history tail fetch.
    Transport(String),
}

impl std::fmt::Display for ChatError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ChatError::Incompatible => {
                f.write_str("this vesta is out of date for the gateway; update vesta or the gateway to continue")
            }
            ChatError::NotFound => f.write_str("agent not found"),
            ChatError::Transport(msg) => f.write_str(msg),
        }
    }
}

impl std::error::Error for ChatError {}

/// Which side authored a rendered line, so the printer picks the nick + color.
#[derive(Debug, PartialEq, Eq)]
enum Speaker {
    You,
    Agent,
}

/// One chat line ready to print: the routing seam builds these purely (no IO), the loop prints them.
#[derive(Debug)]
struct RenderedLine {
    time: String,
    speaker: Speaker,
    text: String,
}

/// What the loop does with one routed frame. Keeps the branch logic pure and unit-testable.
#[derive(Debug)]
enum FrameOutcome {
    /// New chat/user lines (`id` > `last_id`) to print in order.
    Print(Vec<RenderedLine>),
    /// A user echo carrying this intent id: delivery truth for a pending send, not reprinted.
    Confirm(String),
    /// The per-watch edge overflowed: re-watch and re-fetch the tail.
    Resync,
    /// The watched agent was removed: exit cleanly.
    Removed,
    /// Nothing to do (another agent, an unknown frame, or a replayed id).
    Ignore,
}

/// Map one conversation event to a printable line, or `None` for a kind chat does not render or a
/// text-less event.
fn event_to_line(event: &ChatEvent) -> Option<RenderedLine> {
    let speaker = match event.kind.as_str() {
        "user" => Speaker::You,
        "chat" => Speaker::Agent,
        _ => return None,
    };
    let text = event.text.as_deref()?;
    let time = match &event.ts {
        Some(ts) => time_from_ts(ts),
        None => time_now_utc(),
    };
    Some(RenderedLine { time, speaker, text: text.trim_end().to_string() })
}

/// Route one parsed frame for the watched agent, advancing `last_id` past every event it accounts
/// for so the history/watch seam never double-prints. A user echo carrying an intent id confirms a
/// pending send and is not reprinted; other user/chat events print; everything else is ignored.
fn route_frame(frame: SyncFrame, name: &str, last_id: &mut i64) -> FrameOutcome {
    match frame {
        SyncFrame::Append { agent, events } if agent == name => {
            let mut lines = Vec::new();
            let mut confirm = None;
            for event in events {
                if !should_print(event.id, last_id) {
                    continue;
                }
                if event.kind == "user" {
                    if let Some(intent_id) = event.intent_id {
                        confirm = Some(intent_id);
                        continue;
                    }
                }
                if let Some(line) = event_to_line(&event) {
                    lines.push(line);
                }
            }
            if !lines.is_empty() {
                FrameOutcome::Print(lines)
            } else if let Some(intent_id) = confirm {
                FrameOutcome::Confirm(intent_id)
            } else {
                FrameOutcome::Ignore
            }
        }
        SyncFrame::Resync { agent } if agent == name => FrameOutcome::Resync,
        SyncFrame::AgentRemoved { name: removed } if removed == name => FrameOutcome::Removed,
        SyncFrame::Append { .. }
        | SyncFrame::Resync { .. }
        | SyncFrame::AgentRemoved { .. }
        | SyncFrame::Hello { .. }
        | SyncFrame::Snapshot { .. }
        | SyncFrame::Unknown => FrameOutcome::Ignore,
    }
}

fn print_line(line: &RenderedLine, name: &str, color: bool) {
    let (nick, nick_color) = match line.speaker {
        Speaker::You => ("you", ANSI_YOU),
        Speaker::Agent => (name, ANSI_AGENT),
    };
    render_line(&line.time, nick, nick_color, &line.text, color);
}

/// Print the history tail once, deduped by id (advancing `last_id`) so live appends that overlap it
/// are not reprinted.
fn print_tail(events: &[ChatEvent], name: &str, color: bool, last_id: &mut i64) {
    for event in events {
        if should_print(event.id, last_id) {
            if let Some(line) = event_to_line(event) {
                print_line(&line, name, color);
            }
        }
    }
    std::io::stdout().flush().ok();
}

fn print_resync_marker(color: bool) {
    if color {
        println!("{ANSI_TS}-- resynced --{ANSI_RESET}");
    } else {
        println!("-- resynced --");
    }
}

/// The client->server watch frame for one agent (the live-edge subscription).
fn watch_frame(name: &str) -> tungstenite::Message {
    tungstenite::Message::Text(serde_json::json!({ "type": "watch", "agent": name }).to_string().into())
}

/// Block until the next parseable frame arrives, retrying across the read timeout. A parse failure
/// folds to `Unknown` (ignored by rule); a socket close during the handshake is a transport error.
fn read_sync_frame(socket: &mut SyncSocket) -> Result<SyncFrame, ChatError> {
    loop {
        match socket.read() {
            Ok(tungstenite::Message::Text(text)) => {
                return Ok(serde_json::from_str::<SyncFrame>(text.as_ref()).unwrap_or(SyncFrame::Unknown));
            }
            Ok(tungstenite::Message::Close(_)) | Err(tungstenite::Error::ConnectionClosed) => {
                return Err(ChatError::Transport("connection closed during handshake".into()));
            }
            Ok(_) => {}
            Err(tungstenite::Error::Io(ref e))
                if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(read_err) => return Err(ChatError::Transport(format!("handshake read failed: {read_err}"))),
        }
    }
}

/// Drive one `/sync` session over a connected socket: gate on `hello` (protocol floor) and the
/// `snapshot` roster (agent existence), send `watch`, print the history tail deduped by id, then
/// fold live `append`/`resync`/`agent_removed` frames until the socket ends. Each live iteration
/// also drains typed input (optimistic echo + send worker) and send outcomes via `io`, and clears a
/// pending line on its append echo. Returns a `ChatError` on a failed handshake, or a `SessionEnd`
/// describing how the live loop finished. `fetch_tail` is injected so the socket path stays
/// hermetically testable without the history HTTP endpoint.
fn run_sync_session(
    socket: &mut SyncSocket,
    name: &str,
    color: bool,
    last_id: &mut i64,
    fetch_tail: &mut dyn FnMut() -> Result<Vec<ChatEvent>, String>,
    io: &mut ChatIo,
) -> Result<SessionEnd, ChatError> {
    match read_sync_frame(socket)? {
        SyncFrame::Hello { floor } => {
            if !is_compatible(CLI_PROTOCOL, floor) {
                return Err(ChatError::Incompatible);
            }
        }
        _ => return Err(ChatError::Transport("expected hello as the first frame".into())),
    }
    let roster = loop {
        if let SyncFrame::Snapshot { tree } = read_sync_frame(socket)? {
            break tree;
        }
    };
    if !roster.agents.contains(name) {
        return Err(ChatError::NotFound);
    }

    socket
        .send(watch_frame(name))
        .map_err(|e| ChatError::Transport(format!("watch send failed: {e}")))?;
    let tail = fetch_tail().map_err(ChatError::Transport)?;
    print_tail(&tail, name, color, last_id);

    loop {
        drain_input(io, color);
        drain_outcomes(io, color);
        match socket.read() {
            Ok(tungstenite::Message::Text(text)) => {
                let frame = serde_json::from_str::<SyncFrame>(text.as_ref()).unwrap_or(SyncFrame::Unknown);
                match route_frame(frame, name, last_id) {
                    FrameOutcome::Print(lines) => {
                        for line in &lines {
                            print_line(line, name, color);
                        }
                        io.pending.mark_interposed();
                        std::io::stdout().flush().ok();
                    }
                    FrameOutcome::Confirm(intent_id) => confirm_pending(io.pending, &intent_id, color),
                    FrameOutcome::Resync => {
                        if let Err(send_err) = socket.send(watch_frame(name)) {
                            return Ok(SessionEnd::Lost { reason: format!("connection lost on resync: {send_err}") });
                        }
                        match fetch_tail() {
                            Ok(events) => {
                                print_resync_marker(color);
                                print_tail(&events, name, color, last_id);
                                io.pending.mark_interposed();
                            }
                            Err(fetch_err) => {
                                return Ok(SessionEnd::Lost { reason: format!("tail refetch failed on resync: {fetch_err}") });
                            }
                        }
                    }
                    FrameOutcome::Removed => return Ok(SessionEnd::Closed),
                    FrameOutcome::Ignore => {}
                }
            }
            Ok(tungstenite::Message::Close(_)) | Err(tungstenite::Error::ConnectionClosed) => {
                return Ok(SessionEnd::Closed);
            }
            Ok(_) => {}
            Err(tungstenite::Error::Io(ref e))
                if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(read_err) => {
                return Ok(SessionEnd::Lost { reason: format!("connection lost: {read_err}") });
            }
        }
    }
}

/// Clear a confirmed pending line: if it is still the last thing printed (and color is on), rewrite
/// it in place without the pending glyph; a scrolled line is left as printed. The append echo is
/// never reprinted (the line was shown optimistically), so this only drops the marker.
fn confirm_pending(pending: &mut Pending, intent_id: &str, color: bool) {
    if let Some((line, was_last)) = pending.clear(intent_id) {
        if was_last && color {
            print!("\x1b[1A\x1b[2K\r");
            render_line(&line.time, "you", ANSI_YOU, &line.text, true);
            std::io::stdout().flush().ok();
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
    fn connect_sync_socket_rejects_invalid_url() {
        let err = connect_sync_socket(&test_client(), "not a ws url").unwrap_err();
        assert!(err.contains("invalid ws url"), "got: {err}");
    }

    #[test]
    fn connect_sync_socket_errors_on_unreachable_port_without_panicking() {
        // Port 1 on loopback refuses fast — the helper must surface an Err, never panic,
        // so the reconnect loop can keep retrying.
        let err = connect_sync_socket(&test_client(), "wss://127.0.0.1:1/sync?token=tok").unwrap_err();
        assert!(err.contains("ws tcp connect failed") || err.contains("ws connect failed"), "got: {err}");
    }

    #[test]
    fn connect_sync_socket_survives_a_slow_handshake() {
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

        let url = format!("ws://127.0.0.1:{port}/sync?token=tok");
        let socket = connect_sync_socket(&test_client(), &url).expect("handshake should survive a slow server");
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
    fn sync_frame_parses_the_frames_chat_consumes() {
        let hello: SyncFrame = serde_json::from_str(r#"{"type":"hello","version":"0.1.0","protocol":1,"floor":1}"#)
            .expect("hello parses (extra version + protocol fields ignored)");
        match hello {
            SyncFrame::Hello { floor } => assert_eq!(floor, 1),
            other => panic!("expected Hello, got {other:?}"),
        }

        let snapshot: SyncFrame =
            serde_json::from_str(r#"{"type":"snapshot","tree":{"gateway":{"any":"thing"},"agents":{"alpha":{"x":1}}}}"#)
                .expect("snapshot parses (gateway branch ignored)");
        match snapshot {
            SyncFrame::Snapshot { tree } => {
                assert!(tree.agents.contains("alpha"), "roster key set is read");
            }
            other => panic!("expected Snapshot, got {other:?}"),
        }

        let append: SyncFrame =
            serde_json::from_str(r#"{"type":"append","agent":"alpha","events":[{"id":5,"type":"chat","text":"hi"}]}"#)
                .expect("append parses");
        match append {
            SyncFrame::Append { agent, events } => {
                assert_eq!(agent, "alpha");
                assert_eq!(events.len(), 1);
                assert_eq!(events[0].id, 5);
            }
            other => panic!("expected Append, got {other:?}"),
        }

        let resync: SyncFrame = serde_json::from_str(r#"{"type":"resync","agent":"alpha"}"#).expect("resync parses");
        match resync {
            SyncFrame::Resync { agent } => assert_eq!(agent, "alpha"),
            other => panic!("expected Resync, got {other:?}"),
        }

        let removed: SyncFrame = serde_json::from_str(r#"{"type":"agent_removed","name":"beta"}"#).expect("agent_removed parses");
        match removed {
            SyncFrame::AgentRemoved { name } => assert_eq!(name, "beta"),
            other => panic!("expected AgentRemoved, got {other:?}"),
        }
    }

    #[test]
    fn sync_frame_folds_unknown_types_and_rejects_a_missing_tag() {
        // Every other delta (state/agent/notifications/alert and any future addition) folds to Unknown.
        for raw in [
            r#"{"type":"state","scope":"gateway","value":{}}"#,
            r#"{"type":"notifications","agent":"alpha","pending":[]}"#,
            r#"{"type":"alert","agent":"alpha","event":{},"preview":"x"}"#,
            r#"{"type":"brand_new_frame","whatever":true}"#,
        ] {
            let frame: SyncFrame = serde_json::from_str(raw).expect("unknown type folds to Unknown");
            assert!(matches!(frame, SyncFrame::Unknown), "raw: {raw}");
        }
        // A frame with no discriminator is a hard parse error, not Unknown.
        assert!(serde_json::from_str::<SyncFrame>(r#"{"agent":"alpha"}"#).is_err(), "missing type must error");
    }

    #[test]
    fn chat_event_parses_with_and_without_intent_id() {
        // Agent echo of a send carries intent_id; other events omit it, and ts is optional.
        let echo: ChatEvent = serde_json::from_str(r#"{"id":9,"type":"user","text":"hey","intent_id":"cli-1"}"#)
            .expect("user echo parses");
        assert_eq!(echo.id, 9);
        assert_eq!(echo.kind, "user");
        assert_eq!(echo.text.as_deref(), Some("hey"));
        assert_eq!(echo.ts, None);
        assert_eq!(echo.intent_id.as_deref(), Some("cli-1"));

        let reply: ChatEvent = serde_json::from_str(r#"{"id":10,"type":"chat","text":"hi","ts":"2026-07-19T12:00:00Z"}"#)
            .expect("agent reply parses");
        assert_eq!(reply.id, 10);
        assert_eq!(reply.kind, "chat");
        assert_eq!(reply.ts.as_deref(), Some("2026-07-19T12:00:00Z"));
        assert_eq!(reply.intent_id, None);
    }

    #[test]
    fn history_page_drops_the_cursor() {
        let page: HistoryPage =
            serde_json::from_str(r#"{"events":[{"id":1,"type":"chat","text":"a"},{"id":2,"type":"user","text":"b"}],"cursor":1}"#)
                .expect("history page parses");
        assert_eq!(page.events.len(), 2);
        assert_eq!(page.events[0].id, 1);
        assert_eq!(page.events[1].kind, "user");
    }

    #[test]
    fn is_compatible_holds_at_or_above_the_floor() {
        struct Case {
            cli: u32,
            floor: u32,
            compatible: bool,
        }
        let cases = [
            Case { cli: 1, floor: 1, compatible: true },
            Case { cli: 2, floor: 1, compatible: true },
            Case { cli: 1, floor: 2, compatible: false },
            Case { cli: 0, floor: 1, compatible: false },
        ];
        for case in cases {
            assert_eq!(is_compatible(case.cli, case.floor), case.compatible, "cli {} vs floor {}", case.cli, case.floor);
        }
        // The CLI speaks protocol 1, so it meets a floor-1 server.
        assert!(is_compatible(CLI_PROTOCOL, 1));
    }

    #[test]
    fn should_print_advances_only_on_a_strictly_newer_id() {
        let mut last = 0i64;
        assert!(should_print(1, &mut last));
        assert_eq!(last, 1);
        // A replay of the same id is skipped and does not rewind the watermark.
        assert!(!should_print(1, &mut last));
        assert_eq!(last, 1);
        // An older id (out-of-order overlap) is skipped.
        assert!(!should_print(0, &mut last));
        assert_eq!(last, 1);
        // A newer id prints and advances.
        assert!(should_print(5, &mut last));
        assert_eq!(last, 5);
    }

    #[test]
    fn classify_send_maps_status_and_retryable_flag() {
        assert!(matches!(classify_send(200, ""), Ok(())));
        assert!(matches!(classify_send(201, "{}"), Ok(())));
        assert!(matches!(classify_send(299, ""), Ok(())));

        // A retryable 503 carries the tap-down message through for the retry.
        match classify_send(503, r#"{"error":"tap is down","retryable":true}"#) {
            Err(SendError::Retryable(msg)) => assert_eq!(msg, "tap is down"),
            other => panic!("expected Retryable, got {other:?}"),
        }
        // A retryable 503 with no error field still gets a default message.
        assert!(matches!(classify_send(503, r#"{"retryable":true}"#), Err(SendError::Retryable(_))));

        // A 503 that is not flagged retryable is fatal, as is any other non-2xx.
        for (status, body) in [(503u16, r#"{"retryable":false}"#), (503, "{}"), (401, "{}"), (500, r#"{"error":"boom"}"#)] {
            assert!(matches!(classify_send(status, body), Err(SendError::Fatal(_))), "status {status} body {body}");
        }
        match classify_send(500, r#"{"error":"boom"}"#) {
            Err(SendError::Fatal(msg)) => assert_eq!(msg, "boom"),
            other => panic!("expected Fatal, got {other:?}"),
        }
        // The fatal default names the status when the body carries no error.
        match classify_send(418, "not json") {
            Err(SendError::Fatal(msg)) => assert_eq!(msg, "send failed (418)"),
            other => panic!("expected Fatal, got {other:?}"),
        }
    }

    #[test]
    fn send_error_display_is_the_bare_message() {
        let fatal: &dyn std::error::Error = &SendError::Fatal("nope".into());
        assert_eq!(fatal.to_string(), "nope");
        assert_eq!(SendError::Retryable("later".into()).to_string(), "later");
    }

    #[test]
    fn next_intent_id_is_unique_and_strictly_increasing() {
        const COUNT: usize = 200;
        let ids: Vec<String> = (0..COUNT).map(|_| next_intent_id()).collect();
        let unique: std::collections::HashSet<&String> = ids.iter().collect();
        assert_eq!(unique.len(), COUNT, "every intent id is unique");
        for pair in ids.windows(2) {
            assert!(pair[0] < pair[1], "ids sort in mint order: {} then {}", pair[0], pair[1]);
        }
    }

    #[test]
    fn post_message_reports_a_transport_failure_as_fatal() {
        // Port 1 refuses fast: a raw transport failure to vestad is fatal (never retryable), and the
        // send must surface it as Err, never panic.
        let client = test_client();
        let err = post_message(&client.agent, &client.base_url, &client.api_key, "ghost", "hi", "cli-1").unwrap_err();
        assert!(matches!(err, SendError::Fatal(_)), "got: {err:?}");
    }

    #[test]
    fn pending_begins_clears_and_ignores_unknown_ids() {
        let mut pending = Pending::new();
        pending.begin("cli-1".into(), "hello".into(), "12:00".into());
        // A matching clear returns the line and reports it was still the last printed.
        let (line, was_last) = pending.clear("cli-1").expect("known id clears");
        assert_eq!(line.text, "hello");
        assert!(was_last);
        // Clearing it again, or an unknown id, is a no-op.
        assert!(pending.clear("cli-1").is_none());
        assert!(pending.clear("nope").is_none());
    }

    #[test]
    fn pending_reports_a_scrolled_line_as_not_last() {
        let mut pending = Pending::new();
        pending.begin("cli-1".into(), "first".into(), "12:00".into());
        pending.begin("cli-2".into(), "second".into(), "12:01".into());
        // cli-1 is no longer the last printed line (cli-2 came after), so it cannot be rewritten in place.
        let (line, was_last) = pending.clear("cli-1").expect("known id clears");
        assert_eq!(line.text, "first");
        assert!(!was_last);
        // An interposing non-optimistic print forgets the last pointer entirely.
        pending.mark_interposed();
        let (_, was_last) = pending.clear("cli-2").expect("known id clears");
        assert!(!was_last);
    }

    #[test]
    fn drive_send_retries_the_same_intent_then_reports_success() {
        let calls = std::cell::Cell::new(0u32);
        let outcome = drive_send("cli-7", CHAT_SEND_RETRIES, Duration::ZERO, || {
            let n = calls.get();
            calls.set(n + 1);
            if n < 3 { Err(SendError::Retryable("tap down".into())) } else { Ok(()) }
        });
        assert_eq!(outcome.intent_id, "cli-7");
        assert!(outcome.error.is_none(), "a 2xx reports success");
        assert_eq!(calls.get(), 4, "three retries then the accepting attempt");
    }

    #[test]
    fn drive_send_reports_not_delivered_past_the_cap() {
        let calls = std::cell::Cell::new(0u32);
        let outcome = drive_send("cli-8", 2, Duration::ZERO, || {
            calls.set(calls.get() + 1);
            Err::<(), _>(SendError::Retryable("still down".into()))
        });
        assert_eq!(outcome.error.as_deref(), Some("still down"));
        assert_eq!(calls.get(), 3, "the initial attempt plus the two allowed retries");
    }

    #[test]
    fn drive_send_reports_a_fatal_without_retrying() {
        let calls = std::cell::Cell::new(0u32);
        let outcome = drive_send("cli-9", CHAT_SEND_RETRIES, Duration::ZERO, || {
            calls.set(calls.get() + 1);
            Err::<(), _>(SendError::Fatal("nope".into()))
        });
        assert_eq!(outcome.error.as_deref(), Some("nope"));
        assert_eq!(calls.get(), 1, "a fatal error stops immediately");
    }

    #[test]
    fn fetch_chat_tail_surfaces_an_unreachable_server() {
        let err = test_client().fetch_chat_tail("ghost").unwrap_err();
        assert!(err.contains("server not reachable"), "got: {err}");
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

    fn chat_event(id: i64, kind: &str, text: Option<&str>, intent: Option<&str>) -> ChatEvent {
        ChatEvent {
            id,
            kind: kind.to_string(),
            text: text.map(str::to_string),
            ts: None,
            intent_id: intent.map(str::to_string),
        }
    }

    #[test]
    fn sync_url_targets_sync_with_a_percent_encoded_token() {
        assert_eq!(sync_url("http://127.0.0.1:9001", "tok"), "ws://127.0.0.1:9001/sync?token=tok");
        // Reserved characters in the key are percent-encoded (NON_ALPHANUMERIC).
        assert_eq!(sync_url("https://example.com", "a b/c"), "wss://example.com/sync?token=a%20b%2Fc");
    }

    #[test]
    fn route_frame_prints_a_chat_line_and_advances_the_watermark() {
        let mut last = 0i64;
        let frame = SyncFrame::Append { agent: "scout".into(), events: vec![chat_event(5, "chat", Some("hi"), None)] };
        match route_frame(frame, "scout", &mut last) {
            FrameOutcome::Print(lines) => {
                assert_eq!(lines.len(), 1);
                assert_eq!(lines[0].speaker, Speaker::Agent);
                assert_eq!(lines[0].text, "hi");
            }
            other => panic!("expected Print, got {other:?}"),
        }
        assert_eq!(last, 5);
    }

    #[test]
    fn route_frame_prints_a_user_line_without_an_intent_id_as_you() {
        let mut last = 0i64;
        let frame = SyncFrame::Append { agent: "scout".into(), events: vec![chat_event(8, "user", Some("from the app"), None)] };
        match route_frame(frame, "scout", &mut last) {
            FrameOutcome::Print(lines) => assert_eq!(lines[0].speaker, Speaker::You),
            other => panic!("expected Print, got {other:?}"),
        }
        assert_eq!(last, 8);
    }

    #[test]
    fn route_frame_confirms_a_user_echo_carrying_an_intent_id_without_reprinting() {
        let mut last = 0i64;
        let frame = SyncFrame::Append { agent: "scout".into(), events: vec![chat_event(7, "user", Some("hey"), Some("cli-1"))] };
        match route_frame(frame, "scout", &mut last) {
            FrameOutcome::Confirm(intent) => assert_eq!(intent, "cli-1"),
            other => panic!("expected Confirm, got {other:?}"),
        }
        // The echo is not reprinted, but its id still advances so a later tail refetch cannot dup it.
        assert_eq!(last, 7);
    }

    #[test]
    fn route_frame_ignores_other_agents_unknown_frames_and_replayed_ids() {
        let mut last = 5i64;
        let other = SyncFrame::Append { agent: "rover".into(), events: vec![chat_event(9, "chat", Some("x"), None)] };
        assert!(matches!(route_frame(other, "scout", &mut last), FrameOutcome::Ignore));
        assert_eq!(last, 5, "another agent's append does not move our watermark");

        assert!(matches!(route_frame(SyncFrame::Unknown, "scout", &mut last), FrameOutcome::Ignore));
        assert_eq!(last, 5);

        // A replayed id (<= watermark) is the history/watch seam overlap: ignored, no rewind.
        let replay = SyncFrame::Append { agent: "scout".into(), events: vec![chat_event(5, "chat", Some("dup"), None)] };
        assert!(matches!(route_frame(replay, "scout", &mut last), FrameOutcome::Ignore));
        assert_eq!(last, 5);
    }

    #[test]
    fn route_frame_maps_resync_and_removed_only_for_the_watched_agent() {
        let mut last = 0i64;
        assert!(matches!(route_frame(SyncFrame::Resync { agent: "scout".into() }, "scout", &mut last), FrameOutcome::Resync));
        assert!(matches!(route_frame(SyncFrame::Resync { agent: "rover".into() }, "scout", &mut last), FrameOutcome::Ignore));
        assert!(matches!(route_frame(SyncFrame::AgentRemoved { name: "scout".into() }, "scout", &mut last), FrameOutcome::Removed));
        assert!(matches!(route_frame(SyncFrame::AgentRemoved { name: "rover".into() }, "scout", &mut last), FrameOutcome::Ignore));
        assert_eq!(last, 0);
    }

    // ── in-process fake `/sync` server (the CLI's own hermetic idiom) ──

    type FakeWs = tungstenite::WebSocket<std::net::TcpStream>;

    fn send_frame(ws: &mut FakeWs, body: &str) {
        ws.send(tungstenite::Message::Text(body.to_string().into())).expect("server send");
    }

    fn read_frame(ws: &mut FakeWs) -> serde_json::Value {
        loop {
            if let tungstenite::Message::Text(text) = ws.read().expect("server read") {
                return serde_json::from_str(text.as_str()).expect("server frame json");
            }
        }
    }

    /// Spawn a loopback server, run `drive` over the accepted `/sync` socket, and return the port
    /// plus the join handle. Mirrors `connect_sync_socket_survives_a_slow_handshake`.
    fn spawn_sync_server(drive: impl FnOnce(&mut FakeWs) + Send + 'static) -> (u16, std::thread::JoinHandle<()>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind loopback");
        let port = listener.local_addr().expect("local addr").port();
        let handle = std::thread::spawn(move || {
            let (stream, _) = listener.accept().expect("accept");
            let mut ws = tungstenite::accept(stream).expect("server handshake");
            drive(&mut ws);
        });
        (port, handle)
    }

    fn connect_at(port: u16) -> SyncSocket {
        connect_sync_socket(&test_client(), &format!("ws://127.0.0.1:{port}/sync?token=tok")).expect("connect")
    }

    fn empty_tail() -> impl FnMut() -> Result<Vec<ChatEvent>, String> {
        || Ok(Vec::new())
    }

    /// A `ChatIo` with no typed input, no send outcomes, and a no-op send sink: for the session
    /// tests that exercise the socket path (handshake/watch/append/resync) with the live wiring idle.
    struct IdleIo {
        _input_tx: std::sync::mpsc::Sender<String>,
        input_rx: std::sync::mpsc::Receiver<String>,
        _outcome_tx: std::sync::mpsc::Sender<SendOutcome>,
        outcome_rx: std::sync::mpsc::Receiver<SendOutcome>,
        pending: Pending,
        spawn: Box<dyn FnMut(String, String)>,
    }

    impl IdleIo {
        fn new() -> Self {
            let (input_tx, input_rx) = std::sync::mpsc::channel();
            let (outcome_tx, outcome_rx) = std::sync::mpsc::channel();
            Self { _input_tx: input_tx, input_rx, _outcome_tx: outcome_tx, outcome_rx, pending: Pending::new(), spawn: Box::new(|_, _| {}) }
        }

        fn io(&mut self) -> ChatIo<'_> {
            ChatIo { input: &self.input_rx, outcomes: &self.outcome_rx, pending: &mut self.pending, spawn_send: self.spawn.as_mut() }
        }
    }

    #[test]
    fn run_sync_session_handshakes_watches_and_folds_an_append() {
        let (port, server) = spawn_sync_server(|ws| {
            send_frame(ws, r#"{"type":"hello","protocol":1,"floor":1}"#);
            send_frame(ws, r#"{"type":"snapshot","tree":{"agents":{"scout":{}}}}"#);
            // The CLI sends watch only after the hello + roster gates pass.
            assert_eq!(read_frame(ws), serde_json::json!({"type":"watch","agent":"scout"}));
            send_frame(ws, r#"{"type":"append","agent":"scout","events":[{"id":5,"type":"chat","text":"hi"}]}"#);
            // Flush a Close frame and drop: the CLI reads it and exits without acking, so the server
            // must not wait on the close handshake completing.
            ws.close(None).ok();
            ws.flush().ok();
        });

        let mut socket = connect_at(port);
        let mut last_id = 0i64;
        let mut fetch = empty_tail();
        let mut idle = IdleIo::new();
        let end = run_sync_session(&mut socket, "scout", false, &mut last_id, &mut fetch, &mut idle.io()).expect("session runs");
        assert!(matches!(end, SessionEnd::Closed), "a clean close ends the session");
        assert_eq!(last_id, 5, "the append advanced the high-water mark");
        server.join().expect("server thread");
    }

    #[test]
    fn run_sync_session_rejects_a_floor_above_the_cli_protocol_before_watching() {
        let (port, server) = spawn_sync_server(|ws| {
            send_frame(ws, r#"{"type":"hello","protocol":2,"floor":2}"#);
            // The CLI bails on the floor gate and never sends watch; the socket goes idle.
        });

        let mut socket = connect_at(port);
        let mut last_id = 0i64;
        let mut fetch = empty_tail();
        let mut idle = IdleIo::new();
        let err = run_sync_session(&mut socket, "scout", false, &mut last_id, &mut fetch, &mut idle.io()).expect_err("incompatible floor");
        assert!(matches!(err, ChatError::Incompatible), "got: {err:?}");
        server.join().expect("server thread");
    }

    #[test]
    fn run_sync_session_errors_not_found_when_the_roster_lacks_the_agent() {
        let (port, server) = spawn_sync_server(|ws| {
            send_frame(ws, r#"{"type":"hello","protocol":1,"floor":1}"#);
            send_frame(ws, r#"{"type":"snapshot","tree":{"agents":{"other":{}}}}"#);
            // The CLI bails on the roster gate and never sends watch.
        });

        let mut socket = connect_at(port);
        let mut last_id = 0i64;
        let mut fetch = empty_tail();
        let mut idle = IdleIo::new();
        let err = run_sync_session(&mut socket, "scout", false, &mut last_id, &mut fetch, &mut idle.io()).expect_err("agent absent");
        assert!(matches!(err, ChatError::NotFound), "got: {err:?}");
        server.join().expect("server thread");
    }

    #[test]
    fn run_sync_session_rewatches_and_refetches_the_tail_on_resync() {
        let (port, server) = spawn_sync_server(|ws| {
            send_frame(ws, r#"{"type":"hello","protocol":1,"floor":1}"#);
            send_frame(ws, r#"{"type":"snapshot","tree":{"agents":{"scout":{}}}}"#);
            assert_eq!(read_frame(ws), serde_json::json!({"type":"watch","agent":"scout"}));
            send_frame(ws, r#"{"type":"resync","agent":"scout"}"#);
            // The CLI re-watches in response to the resync before we close.
            assert_eq!(read_frame(ws), serde_json::json!({"type":"watch","agent":"scout"}));
            ws.close(None).ok();
            ws.flush().ok();
        });

        let mut socket = connect_at(port);
        let mut last_id = 0i64;
        // The tail is fetched once on connect and again on the resync.
        let fetch_calls = std::cell::Cell::new(0usize);
        let mut fetch = || {
            fetch_calls.set(fetch_calls.get() + 1);
            Ok::<_, String>(Vec::<ChatEvent>::new())
        };
        let mut idle = IdleIo::new();
        let end = run_sync_session(&mut socket, "scout", false, &mut last_id, &mut fetch, &mut idle.io()).expect("session runs");
        assert!(matches!(end, SessionEnd::Closed));
        assert_eq!(fetch_calls.get(), 2, "resync triggers a second tail fetch");
        server.join().expect("server thread");
    }
}
