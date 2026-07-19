//! The HTTP layer's shared vocabulary, below every handler module: the daemon's
//! `AppState`, the JSON response helpers, and the request-layer constants. Handler
//! modules (serve.rs, auth.rs, `agent_proxy.rs`, providers/*) all
//! import from here; this module imports none of them.

use std::collections::HashMap;
use std::path::Path;
use std::sync::{atomic::AtomicBool, Arc};

use axum::{http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use tokio::sync::{Mutex, RwLock};

use crate::settings::{load_settings, Settings};
use crate::{agent_status, docker, mobile_app, update_check};

pub(crate) const PROXY_MAX_BODY_BYTES: usize = 10 * 1024 * 1024; // 10 MB

// Server-originated WebSocket ping cadence for the `/sync` and registered-service proxy
// sockets. Idle connections through the Cloudflare tunnel are reaped
// by the edge after ~100s of silence; a periodic ping keeps frames flowing so the socket
// survives an idle client. Must stay comfortably under that window.
pub(crate) const WS_KEEPALIVE_INTERVAL_SECS: u64 = 30;

const AUTH_SESSION_TIMEOUT_SECS: u64 = 600;

/// One in-flight Claude OAuth PKCE session (see providers/claude.rs).
pub(crate) struct AuthSession {
    pub code_verifier: String,
    pub state: String,
    pub created: std::time::Instant,
}

impl AuthSession {
    pub fn is_expired(&self) -> bool {
        self.created.elapsed().as_secs() > AUTH_SESSION_TIMEOUT_SECS
    }
}

/// One refresh-token family (one login). `live` is the only currently-valid jti;
/// `prev` is the jti it was just rotated from, honored ONCE as a retry-grace so a
/// client whose refresh response was lost can re-present it without self-revoking.
/// The rotation policy over this data lives in auth.rs.
#[derive(Clone, Serialize, Deserialize)]
pub(crate) struct RefreshFamily {
    pub(crate) live: String,
    pub(crate) prev: Option<String>,
    /// Idle expiry (unix secs) for pruning: set to now + `REFRESH_TOKEN_TTL` at
    /// registration and slid forward on every successful rotation, so an active
    /// client never expires and an idle one re-auths after the TTL.
    pub(crate) exp: u64,
}

/// Drop expired families (lazy GC on every access; n = active logins, tiny).
pub(crate) fn prune_expired(map: &mut HashMap<String, RefreshFamily>, now: u64) {
    map.retain(|_, f| f.exp > now);
}

/// Path of the persisted registry (small JSON in the config dir).
fn refresh_store_path(config_dir: &Path) -> std::path::PathBuf {
    config_dir.join("refresh-tokens.json")
}

/// Load the persisted registry, dropping already-expired families. Best-effort: a
/// missing/corrupt file just starts empty (clients re-auth).
fn load_refresh_live(config_dir: &Path) -> HashMap<String, RefreshFamily> {
    let now = crate::time_utils::now_epoch_secs();
    let mut map: HashMap<String, RefreshFamily> = std::fs::read(refresh_store_path(config_dir))
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    prune_expired(&mut map, now);
    map
}

/// Persist the registry atomically (temp + rename). Best-effort: a write failure
/// only means a restart re-auths, never a request failure.
pub(crate) async fn persist_refresh_live(config_dir: &Path, map: &HashMap<String, RefreshFamily>) {
    let Ok(json) = serde_json::to_vec(map) else {
        return;
    };
    let path = refresh_store_path(config_dir);
    let tmp = path.with_extension("json.tmp");
    if tokio::fs::write(&tmp, json).await.is_ok() {
        let _ = tokio::fs::rename(&tmp, &path).await;
    }
}

pub struct AppState {
    pub(crate) api_key: String,
    pub(crate) env_config: docker::AgentEnvConfig,
    pub(crate) docker: bollard::Docker,
    pub(crate) auth_sessions: Mutex<HashMap<String, AuthSession>>,
    /// Refresh-token registry: family id → {live/prev jti, exp} (rotation + reuse
    /// detection, see `auth.rs`). Loaded from / persisted to the config dir so a
    /// vestad restart/self-update does NOT invalidate outstanding refresh tokens.
    pub(crate) refresh_live: Mutex<HashMap<String, RefreshFamily>>,
    agent_locks: Mutex<HashMap<String, Arc<tokio::sync::RwLock<()>>>>,
    pub(crate) tunnel_url: Mutex<Option<String>>,
    pub(crate) update_info: Mutex<Option<update_check::UpdateInfo>>,
    pub(crate) updating: AtomicBool,
    pub(crate) http_client: reqwest::Client,
    pub(crate) settings: RwLock<Settings>,
    pub(crate) mobile_app: mobile_app::MobileApp,
    pub(crate) dev_mode: bool,
    pub(crate) agent_status_cache: Arc<agent_status::AgentStatusCache>,
    /// The client-protocol aggregator's fan-out state: per-agent live edge, notifications
    /// projection, and tap write-half for send-message relay. Fed by the tap in `agent_status.rs`
    /// and read by the `/sync` handler.
    pub(crate) sync_hub: Arc<crate::sync::SyncHub>,
    /// Agents whose container is mid-rebuild; shared with the boot reconcile and the
    /// status poll so they report `Rebuilding` and mutating handlers refuse to race it.
    pub(crate) rebuilding: docker::RebuildTracker,
    pub(crate) https_port: u16,
    /// LAN exposure facts captured at startup (read-only; surfaced by /gateway/info).
    /// `expose_lan` mirrors the `--expose-lan` flag; `lan_url` is the advertised
    /// `https://<lan-ip>:<port>` (only set when exposed and an IP was resolvable).
    pub(crate) expose_lan: bool,
    pub(crate) lan_url: Option<String>,
}

/// Read-only serving facts fixed at startup (mode, port, LAN exposure), carried
/// into `AppState::new` as one unit and stored as individual fields.
pub(crate) struct GatewayFacts {
    pub(crate) dev_mode: bool,
    pub(crate) https_port: u16,
    pub(crate) expose_lan: bool,
    pub(crate) lan_url: Option<String>,
}

impl AppState {
    pub(crate) fn new(
        api_key: String,
        env_config: docker::AgentEnvConfig,
        docker: bollard::Docker,
        tunnel_url: Option<String>,
        facts: GatewayFacts,
    ) -> (Self, mobile_app::MobileAppWorker) {
        let GatewayFacts {
            dev_mode,
            https_port,
            expose_lan,
            lan_url,
        } = facts;
        let settings = load_settings();
        // Restore the refresh-token registry from disk (dropping expired families)
        // so a restart/self-update doesn't log everyone out. Read before `env_config`
        // is moved into the struct below.
        let refresh_live = load_refresh_live(&env_config.config_dir);
        let http_client = reqwest::Client::new();
        let (mobile_app, mobile_app_worker) =
            mobile_app::MobileApp::new(env_config.config_dir.clone(), http_client.clone());
        (
            Self {
                api_key,
                env_config,
                docker,
                auth_sessions: Mutex::new(HashMap::new()),
                refresh_live: Mutex::new(refresh_live),
                agent_locks: Mutex::new(HashMap::new()),
                tunnel_url: Mutex::new(tunnel_url),
                update_info: Mutex::new(None),
                updating: AtomicBool::new(false),
                http_client,
                settings: RwLock::new(settings),
                mobile_app,
                dev_mode,
                agent_status_cache: Arc::new(agent_status::AgentStatusCache::new()),
                sync_hub: Arc::new(crate::sync::SyncHub::new()),
                rebuilding: docker::RebuildTracker::default(),
                https_port,
                expose_lan,
                lan_url,
            },
            mobile_app_worker,
        )
    }

    pub(crate) async fn agent_lock(&self, name: &str) -> Arc<tokio::sync::RwLock<()>> {
        let mut locks = self.agent_locks.lock().await;
        locks
            .entry(name.to_string())
            .or_insert_with(|| Arc::new(tokio::sync::RwLock::new(())))
            .clone()
    }

    pub(crate) async fn clean_expired_sessions(&self) {
        let mut sessions = self.auth_sessions.lock().await;
        sessions.retain(|_, s| !s.is_expired());
    }
}

pub type SharedState = Arc<AppState>;

// --- Response helpers ---

pub fn ok_json() -> Json<serde_json::Value> {
    Json(serde_json::json!({"ok": true}))
}

pub fn err_response(status: StatusCode, msg: &str) -> (StatusCode, Json<serde_json::Value>) {
    if status.is_server_error() {
        tracing::error!(status = status.as_u16(), error = msg, "server error");
    }
    (status, Json(serde_json::json!({"error": msg})))
}

pub(crate) fn map_docker_err(e: docker::DockerError) -> (StatusCode, Json<serde_json::Value>) {
    use docker::DockerError::{
        AlreadyExists, BrokenState, BuildRequired, Failed, InvalidName, NotFound, NotRunning,
    };
    let (status, message) = match e {
        NotFound(message) => (StatusCode::NOT_FOUND, message),
        AlreadyExists(message) => (StatusCode::CONFLICT, message),
        NotRunning(message) => (StatusCode::SERVICE_UNAVAILABLE, message),
        BrokenState(message) | Failed(message) => (StatusCode::INTERNAL_SERVER_ERROR, message),
        InvalidName(message) | BuildRequired(message) => (StatusCode::BAD_REQUEST, message),
    };
    err_response(status, &message)
}
