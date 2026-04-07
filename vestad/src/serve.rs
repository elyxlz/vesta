use axum::{
    body::Body,
    extract::{ConnectInfo, Path, Query, Request, State, WebSocketUpgrade},
    http::{HeaderMap, StatusCode},
    middleware::{self, Next},
    response::{
        sse::{Event, KeepAlive},
        IntoResponse, Response, Sse,
    },
    routing::{any, get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use tokio::sync::{Mutex, RwLock};

use crate::{docker, jwt, self_update, update_check};

const API_KEY_BYTES: usize = 32;
const PROXY_MAX_BODY_BYTES: usize = 10 * 1024 * 1024; // 10 MB

const RESERVED_SERVICE_NAMES: &[&str] = &["ws", "history", "services", "search"];
const AUTH_SESSION_TIMEOUT_SECS: u64 = 600;
const DEFAULT_LOG_TAIL_LINES: u64 = 500;
const AUTO_BACKUP_CHECK_INTERVAL_SECS: u64 = 3600;

// --- TLS cert generation ---

pub fn ensure_tls(config_dir: &std::path::Path) -> (String, String, String) {
    let tls_dir = config_dir.join("tls");
    let cert_path = tls_dir.join("cert.pem");
    let key_path = tls_dir.join("key.pem");
    let fingerprint_path = tls_dir.join("fingerprint");

    if cert_path.exists() && key_path.exists() && fingerprint_path.exists() {
        let cert_pem = std::fs::read_to_string(&cert_path).expect("failed to read cert.pem");
        let key_pem = std::fs::read_to_string(&key_path).expect("failed to read key.pem");
        let fingerprint =
            std::fs::read_to_string(&fingerprint_path).expect("failed to read fingerprint");
        return (cert_pem, key_pem, fingerprint.trim().to_string());
    }

    std::fs::create_dir_all(&tls_dir).expect("failed to create tls dir");

    let mut params = rcgen::CertificateParams::new(vec!["localhost".into()]).unwrap();
    params
        .subject_alt_names
        .push(rcgen::SanType::IpAddress(std::net::IpAddr::V4(
            std::net::Ipv4Addr::new(127, 0, 0, 1),
        )));
    // Add all local IP addresses as SANs for remote connections
    if let Ok(output) = std::process::Command::new("hostname").arg("-I").output() {
        let ips = String::from_utf8_lossy(&output.stdout);
        for ip_str in ips.split_whitespace() {
            if let Ok(ip) = ip_str.parse::<std::net::IpAddr>() {
                params.subject_alt_names.push(rcgen::SanType::IpAddress(ip));
            }
        }
    }
    // 10 year validity
    params.not_after = rcgen::date_time_ymd(2036, 1, 1);

    let key_pair = rcgen::KeyPair::generate().unwrap();
    let cert = params.self_signed(&key_pair).unwrap();

    let cert_pem = cert.pem();
    let key_pem = key_pair.serialize_pem();

    // Compute SHA-256 fingerprint of the DER certificate
    let der_bytes = cert.der();
    let digest = ring::digest::digest(&ring::digest::SHA256, der_bytes);
    let fingerprint = format!(
        "sha256:{}",
        digest
            .as_ref()
            .iter()
            .map(|b| format!("{:02X}", b))
            .collect::<Vec<_>>()
            .join(":")
    );

    std::fs::write(&cert_path, &cert_pem).expect("failed to write cert.pem");
    std::fs::write(&key_path, &key_pem).expect("failed to write key.pem");
    std::fs::write(&fingerprint_path, &fingerprint).expect("failed to write fingerprint");

    // chmod 600 on key and fingerprint
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&key_path, std::fs::Permissions::from_mode(0o600)).ok();
        std::fs::set_permissions(&fingerprint_path, std::fs::Permissions::from_mode(0o600)).ok();
    }

    (cert_pem, key_pem, fingerprint)
}

// --- API key generation ---

pub fn ensure_api_key(config_dir: &std::path::Path) -> String {
    let key_path = config_dir.join("api-key");
    if let Ok(key) = std::fs::read_to_string(&key_path) {
        let key = key.trim().to_string();
        if !key.is_empty() {
            return key;
        }
    }

    std::fs::create_dir_all(config_dir).expect("failed to create config dir");

    let key: String = (0..API_KEY_BYTES)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect();

    std::fs::write(&key_path, &key).expect("failed to write api-key");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&key_path, std::fs::Permissions::from_mode(0o600)).ok();
    }
    key
}

// --- App state ---

struct AuthSession {
    code_verifier: String,
    state: String,
    created: std::time::Instant,
}

pub struct AppState {
    api_key: String,
    vestad_port: u16,
    auth_sessions: Mutex<HashMap<String, AuthSession>>,
    agent_locks: Mutex<HashMap<String, Arc<tokio::sync::RwLock<()>>>>,
    tunnel_url: Mutex<Option<String>>,
    update_info: Mutex<Option<update_check::UpdateInfo>>,
    updating: AtomicBool,
    auto_backup_enabled: AtomicBool,
    backup_retention: Mutex<crate::types::RetentionPolicy>,
    http_client: reqwest::Client,
    service_registry: RwLock<HashMap<String, HashMap<String, u16>>>,
}

impl AppState {
    fn new(api_key: String, vestad_port: u16, tunnel_url: Option<String>) -> Self {
        let service_registry = load_service_registry();
        Self {
            api_key,
            vestad_port,
            auth_sessions: Mutex::new(HashMap::new()),
            agent_locks: Mutex::new(HashMap::new()),
            tunnel_url: Mutex::new(tunnel_url),
            update_info: Mutex::new(None),
            updating: AtomicBool::new(false),
            auto_backup_enabled: AtomicBool::new(true),
            backup_retention: Mutex::new(crate::types::RetentionPolicy {
                daily: docker::DEFAULT_RETENTION_DAILY,
                weekly: docker::DEFAULT_RETENTION_WEEKLY,
                monthly: docker::DEFAULT_RETENTION_MONTHLY,
            }),
            http_client: reqwest::Client::new(),
            service_registry: RwLock::new(service_registry),
        }
    }

    async fn agent_lock(&self, name: &str) -> Arc<tokio::sync::RwLock<()>> {
        let mut locks = self.agent_locks.lock().await;
        locks
            .entry(name.to_string())
            .or_insert_with(|| Arc::new(tokio::sync::RwLock::new(())))
            .clone()
    }

    async fn clean_expired_sessions(&self) {
        let mut sessions = self.auth_sessions.lock().await;
        let now = std::time::Instant::now();
        sessions.retain(|_, s| now.duration_since(s.created) < std::time::Duration::from_secs(AUTH_SESSION_TIMEOUT_SECS));
    }
}

type SharedState = Arc<AppState>;

// --- Auth middleware ---

/// Check if a path matches `/agents/{name}/dashboard/...` for a static asset (not the root).
fn is_dashboard_asset(path: &str) -> bool {
    let segments: Vec<&str> = path.trim_start_matches('/').splitn(4, '/').collect();
    segments.len() >= 4 && segments[0] == "agents" && segments[2] == "dashboard"
}

async fn auth_middleware(
    State(state): State<SharedState>,
    headers: HeaderMap,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    // Let CORS preflight through — the CorsLayer handles the response.
    if request.method() == axum::http::Method::OPTIONS {
        return next.run(request).await;
    }

    // Dashboard asset sub-resources (JS/CSS bundles) are loaded by the browser
    // after the initial authenticated HTML request. They can't carry tokens,
    // so we skip auth for them — they're just static build artifacts.
    if is_dashboard_asset(request.uri().path()) {
        return next.run(request).await;
    }

    // Check Bearer header first, then query param ?token= (for WebSocket)
    let bearer_ok = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|token| verify_token(token, &state.api_key))
        .unwrap_or(false);

    let query_ok = if !bearer_ok {
        request
            .uri()
            .query()
            .and_then(|q| {
                q.split('&')
                    .find_map(|p| p.strip_prefix("token="))
            })
            .map(|t| verify_token(t, &state.api_key))
            .unwrap_or(false)
    } else {
        false
    };

    if !bearer_ok && !query_ok {
        let path = request.uri().path().to_string();
        tracing::warn!(path = %path, "client auth failed");
        return (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "unauthorized"})),
        )
            .into_response();
    }

    next.run(request).await
}

/// Allow requests from localhost without auth; require auth from external sources.
async fn localhost_or_auth_middleware(
    State(state): State<SharedState>,
    connect_info: ConnectInfo<std::net::SocketAddr>,
    headers: HeaderMap,
    request: Request,
    next: Next,
) -> Response {
    if connect_info.0.ip().is_loopback() {
        return next.run(request).await;
    }

    let bearer_ok = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|token| verify_token(token, &state.api_key))
        .unwrap_or(false);

    let query_ok = if !bearer_ok {
        request
            .uri()
            .query()
            .and_then(|q| q.split('&').find_map(|p| p.strip_prefix("token=")))
            .map(|t| verify_token(t, &state.api_key))
            .unwrap_or(false)
    } else {
        false
    };

    if !bearer_ok && !query_ok {
        return (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "unauthorized"})),
        )
            .into_response();
    }

    next.run(request).await
}

/// Accept raw API key or JWT access token.
fn verify_token(token: &str, api_key: &str) -> bool {
    if token == api_key {
        return true;
    }
    if token.contains('.') {
        return jwt::validate_token(api_key, token, "access").is_ok();
    }
    false
}

// --- Session endpoints ---

#[derive(Deserialize)]
struct SessionRequest {
    api_key: String,
}

#[derive(Serialize)]
struct SessionResponse {
    access_token: String,
    refresh_token: String,
    expires_in: u64,
}

async fn create_session_handler(
    State(state): State<SharedState>,
    Json(body): Json<SessionRequest>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    if body.api_key != state.api_key {
        tracing::warn!("client session auth failed: invalid API key");
        return Err(err_response(StatusCode::UNAUTHORIZED, "invalid API key"));
    }

    tracing::info!("client connected (new session)");
    Ok(Json(SessionResponse {
        access_token: jwt::create_token(&state.api_key, "access", jwt::ACCESS_TOKEN_TTL),
        refresh_token: jwt::create_token(&state.api_key, "refresh", jwt::REFRESH_TOKEN_TTL),
        expires_in: jwt::ACCESS_TOKEN_TTL,
    }))
}

async fn refresh_session_handler(
    State(state): State<SharedState>,
    Json(body): Json<RefreshRequest>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    jwt::validate_token(&state.api_key, &body.refresh_token, "refresh")
        .map_err(|e| err_response(StatusCode::UNAUTHORIZED, &e.to_string()))?;

    Ok(Json(SessionResponse {
        access_token: jwt::create_token(&state.api_key, "access", jwt::ACCESS_TOKEN_TTL),
        refresh_token: jwt::create_token(&state.api_key, "refresh", jwt::REFRESH_TOKEN_TTL),
        expires_in: jwt::ACCESS_TOKEN_TTL,
    }))
}

#[derive(Deserialize)]
struct RefreshRequest {
    refresh_token: String,
}

// --- Response helpers ---

fn ok_json() -> Json<serde_json::Value> {
    Json(serde_json::json!({"ok": true}))
}

fn err_response(status: StatusCode, msg: &str) -> (StatusCode, Json<serde_json::Value>) {
    (status, Json(serde_json::json!({"error": msg})))
}

fn map_join_err(e: tokio::task::JoinError) -> (StatusCode, Json<serde_json::Value>) {
    err_response(StatusCode::INTERNAL_SERVER_ERROR, &format!("task failed: {e}"))
}

fn map_docker_err(e: docker::DockerError) -> (StatusCode, Json<serde_json::Value>) {
    use docker::DockerError::*;
    let status = match &e {
        NotFound(_) => StatusCode::NOT_FOUND,
        AlreadyExists(_) => StatusCode::CONFLICT,
        NotRunning(_) => StatusCode::SERVICE_UNAVAILABLE,
        BrokenState(_) => StatusCode::INTERNAL_SERVER_ERROR,
        InvalidName(_) | BuildRequired(_) => StatusCode::BAD_REQUEST,
        Failed(_) => StatusCode::INTERNAL_SERVER_ERROR,
    };
    err_response(status, &e.to_string())
}

// --- Handlers ---

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"ok": true}))
}

async fn version(State(state): State<SharedState>) -> Json<serde_json::Value> {
    let update = state.update_info.lock().await;
    let (latest, update_available) = match update.as_ref() {
        Some(info) => (
            Some(info.latest.clone()),
            Some(info.update_available),
        ),
        None => (None, None),
    };
    Json(serde_json::json!({
        "version": env!("CARGO_PKG_VERSION"),
        "api_compat": "0.2",
        "latest_version": latest,
        "update_available": update_available,
    }))
}

async fn self_update_handler(
    State(state): State<SharedState>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if state.updating.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return Err(err_response(StatusCode::CONFLICT, "update already in progress"));
    }
    tracing::info!("self-update requested via API");
    let result = tokio::task::spawn_blocking(self_update::perform_update)
        .await
        .unwrap();
    state.updating.store(false, std::sync::atomic::Ordering::SeqCst);
    match result {
        Ok(restarting) => Ok(Json(serde_json::json!({
            "ok": true,
            "restarting": restarting,
        }))),
        Err(e) => Err(err_response(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string())),
    }
}

async fn tunnel_handler(
    State(state): State<SharedState>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let url = state.tunnel_url.lock().await;
    match url.as_ref() {
        Some(tunnel_url) => Ok(Json(serde_json::json!({"tunnel_url": tunnel_url}))),
        None => Err(err_response(StatusCode::NOT_FOUND, "no tunnel configured")),
    }
}

async fn list_agents_handler() -> impl IntoResponse {
    let agents = tokio::task::spawn_blocking(docker::list_agents)
        .await
        .unwrap();
    Json(agents)
}

#[derive(Deserialize)]
struct CreateBody {
    name: Option<String>,
}

async fn create_agent_handler(
    State(state): State<SharedState>,
    Json(body): Json<CreateBody>,
) -> Result<impl IntoResponse, (StatusCode, Json<serde_json::Value>)> {
    let raw_name = body.name.unwrap_or_else(|| "default".to_string());
    let name = docker::normalize_name(&raw_name);
    if name.is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "invalid agent name"));
    }
    tracing::info!(name = %name, "creating agent");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let vestad_port = state.vestad_port;
    let name =
        tokio::task::spawn_blocking(move || docker::create_agent(&name, vestad_port))
            .await
            .unwrap()
            .map_err(map_docker_err)?;

    let start_name = name.clone();
    tokio::task::spawn_blocking(move || docker::start_agent(&start_name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    Ok((StatusCode::CREATED, Json(serde_json::json!({"name": name}))))
}

async fn agent_status_handler(
    Path(name): Path<String>,
) -> Result<Json<docker::StatusJson>, (StatusCode, Json<serde_json::Value>)> {
    let status = tokio::task::spawn_blocking(move || docker::get_status(&name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;
    Ok(Json(status))
}

async fn start_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "starting agent");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::start_agent(&name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;
    Ok(ok_json())
}

async fn start_all_handler(
    State(_state): State<SharedState>,
) -> impl IntoResponse {
    let results = tokio::task::spawn_blocking(docker::start_all_agents)
        .await
        .unwrap();

    let has_error = results.iter().any(|r| !r.ok);
    let status = if has_error {
        StatusCode::MULTI_STATUS
    } else {
        StatusCode::OK
    };

    (status, Json(serde_json::json!({"results": results})))
}

async fn stop_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "stopping agent");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let docker_name = name.clone();
    tokio::task::spawn_blocking(move || docker::stop_agent(&docker_name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;
    {
        let mut reg = state.service_registry.write().await;
        reg.remove(&name);
        save_service_registry(&reg);
    }
    Ok(ok_json())
}

async fn restart_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "restarting agent");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::restart_agent(&name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;
    Ok(ok_json())
}

async fn destroy_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "destroying agent");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let docker_name = name.clone();
    tokio::task::spawn_blocking(move || docker::destroy_agent(&docker_name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;
    {
        let mut reg = state.service_registry.write().await;
        reg.remove(&name);
        save_service_registry(&reg);
    }

    Ok(ok_json())
}

async fn rebuild_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "rebuilding agent");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let vestad_port = state.vestad_port;
    tokio::task::spawn_blocking(move || docker::rebuild_agent(&name, vestad_port))
        .await
        .unwrap()
        .map_err(map_docker_err)?;
    Ok(ok_json())
}

#[derive(Deserialize)]
struct WaitReadyQuery {
    timeout: Option<u64>,
}

async fn wait_ready_handler(
    Path(name): Path<String>,
    Query(query): Query<WaitReadyQuery>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let timeout = query.timeout.unwrap_or(30);
    docker::wait_ready_async(&name, timeout)
        .await
        .map_err(|e| err_response(StatusCode::SERVICE_UNAVAILABLE, &e.to_string()))?;
    Ok(ok_json())
}

// --- Auth endpoints ---

#[derive(Serialize)]
struct AuthFlowResponse {
    auth_url: String,
    session_id: String,
}

async fn start_auth_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<AuthFlowResponse>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);
    docker::ensure_exists(&cname).map_err(map_docker_err)?;

    let (auth_url, code_verifier, auth_state) = docker::start_auth_flow();
    let session_id: String = (0..16)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect();

    state.clean_expired_sessions().await;

    let mut sessions = state.auth_sessions.lock().await;
    let now = std::time::Instant::now();
    sessions.insert(
        session_id.clone(),
        AuthSession {
            code_verifier,
            state: auth_state,
            created: now,
        },
    );

    Ok(Json(AuthFlowResponse {
        auth_url,
        session_id,
    }))
}

#[derive(Deserialize)]
struct AuthCodeBody {
    session_id: String,
    code: String,
}

const AUTH_READY_TIMEOUT_SECS: u64 = 180;

async fn complete_auth_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<AuthCodeBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);
    docker::ensure_exists(&cname).map_err(map_docker_err)?;

    state.clean_expired_sessions().await;

    let session = {
        let mut sessions = state.auth_sessions.lock().await;
        sessions
            .remove(&body.session_id)
            .ok_or_else(|| err_response(StatusCode::BAD_REQUEST, "invalid or expired session"))?
    };

    let code = body.code;
    let credentials = tokio::task::spawn_blocking(move || {
        docker::complete_auth_flow(&code, &session.code_verifier, &session.state)
    })
    .await
    .unwrap()
    .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e.to_string()))?;

    tokio::task::spawn_blocking(move || docker::inject_credentials(&cname, &credentials))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    // Restart the agent so it picks up the new credentials, then wait for
    // first-start setup (skills, memory, greeting) to complete.
    let restart_name = name.clone();
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::restart_agent(&restart_name))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    docker::wait_ready_async(&name, AUTH_READY_TIMEOUT_SECS)
        .await
        .map_err(map_docker_err)?;

    Ok(ok_json())
}

#[derive(Deserialize)]
struct AuthTokenBody {
    token: serde_json::Value,
}

async fn inject_token_handler(
    Path(name): Path<String>,
    Json(body): Json<AuthTokenBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);
    docker::ensure_exists(&cname).map_err(map_docker_err)?;

    let credentials = body.token.to_string();
    tokio::task::spawn_blocking(move || docker::inject_credentials(&cname, &credentials))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    Ok(ok_json())
}

// --- SSE Logs ---

#[derive(Deserialize)]
struct LogsQuery {
    tail: Option<u64>,
}

async fn logs_handler(
    Path(name): Path<String>,
    Query(query): Query<LogsQuery>,
) -> Result<Sse<impl futures_core::Stream<Item = Result<Event, std::io::Error>>>, (StatusCode, Json<serde_json::Value>)>
{
    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);
    docker::ensure_running(&cname)
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e.to_string()))?;

    let tail_lines = query.tail.unwrap_or(DEFAULT_LOG_TAIL_LINES).to_string();
    let stream = async_stream::stream! {
        let mut child = match tokio::process::Command::new("docker")
            .args(["exec", &cname, "tail", "-n", &tail_lines, "-f", docker::VESTA_LOG_PATH])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                yield Ok(Event::default().data(format!("error: {}", e)));
                return;
            }
        };

        let stdout = child.stdout.take().unwrap();
        let mut reader = tokio::io::BufReader::new(stdout);
        let mut line = String::new();

        loop {
            line.clear();
            match tokio::io::AsyncBufReadExt::read_line(&mut reader, &mut line).await {
                Ok(0) => {
                    yield Ok(Event::default().event("agent_stopped").data(""));
                    break;
                }
                Ok(_) => {
                    yield Ok(Event::default().data(line.trim_end()));
                }
                Err(e) => {
                    yield Ok(Event::default().data(format!("error: {}", e)));
                    break;
                }
            }
        }

        child.kill().await.ok();
    };

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}

// --- WebSocket proxy (used by agent wildcard) ---

async fn ws_proxy(client_ws: axum::extract::ws::WebSocket, agent_port: u16, path: &str) {
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    let url = format!("ws://localhost:{}{}", agent_port, path);
    let agent_ws = match tokio_tungstenite::connect_async(&url).await {
        Ok((ws, _)) => ws,
        Err(e) => {
            tracing::warn!(url = %url, error = %e, "agent websocket not reachable");
            let mut client_ws = client_ws;
            let _ = client_ws
                .send(AxumMsg::Close(Some(axum::extract::ws::CloseFrame {
                    code: 1011,
                    reason: format!("agent not reachable: {e}").into(),
                })))
                .await;
            return;
        }
    };

    tracing::info!(port = agent_port, "client websocket connected");

    let (mut client_tx, mut client_rx) = client_ws.split();
    let (mut agent_tx, mut agent_rx) = agent_ws.split();

    let client_to_agent = async {
        while let Some(Ok(msg)) = client_rx.next().await {
            let tung_msg = match msg {
                AxumMsg::Text(t) => TungMsg::Text(t.as_str().into()),
                AxumMsg::Binary(b) => TungMsg::Binary(bytes::Bytes::from(b.to_vec())),
                AxumMsg::Ping(p) => TungMsg::Ping(bytes::Bytes::from(p.to_vec())),
                AxumMsg::Pong(p) => TungMsg::Pong(bytes::Bytes::from(p.to_vec())),
                AxumMsg::Close(_) => break,
            };
            if agent_tx.send(tung_msg).await.is_err() {
                break;
            }
        }
    };

    let agent_to_client = async {
        while let Some(Ok(msg)) = agent_rx.next().await {
            let axum_msg = match msg {
                TungMsg::Text(t) => AxumMsg::Text(t.as_str().into()),
                TungMsg::Binary(b) => AxumMsg::Binary(bytes::Bytes::from(b.to_vec())),
                TungMsg::Ping(p) => AxumMsg::Ping(bytes::Bytes::from(p.to_vec())),
                TungMsg::Pong(p) => AxumMsg::Pong(bytes::Bytes::from(p.to_vec())),
                TungMsg::Close(_) => break,
                _ => continue,
            };
            if client_tx.send(axum_msg).await.is_err() {
                break;
            }
        }
    };

    tokio::select! {
        _ = client_to_agent => {},
        _ = agent_to_client => {},
    }

    tracing::info!(port = agent_port, "client websocket disconnected");
}

// --- Service registry ---

fn services_file() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    std::path::PathBuf::from(home).join(".config/vesta/vestad/services.json")
}

fn load_service_registry() -> HashMap<String, HashMap<String, u16>> {
    let path = services_file();
    match std::fs::read_to_string(&path) {
        Ok(data) => match serde_json::from_str(&data) {
            Ok(registry) => registry,
            Err(err) => {
                tracing::warn!(path = %path.display(), error = %err, "corrupt services.json, starting empty");
                HashMap::new()
            }
        },
        Err(_) => HashMap::new(),
    }
}

fn save_service_registry(registry: &HashMap<String, HashMap<String, u16>>) {
    let path = services_file();
    if let Some(parent) = path.parent() {
        if let Err(err) = std::fs::create_dir_all(parent) {
            tracing::warn!(error = %err, "failed to create services dir");
            return;
        }
    }
    let data = match serde_json::to_string_pretty(registry) {
        Ok(data) => data,
        Err(err) => {
            tracing::warn!(error = %err, "failed to serialize service registry");
            return;
        }
    };
    let tmp = path.with_extension("json.tmp");
    if let Err(err) = std::fs::write(&tmp, &data) {
        tracing::warn!(error = %err, "failed to write services.json.tmp");
        return;
    }
    if let Err(err) = std::fs::rename(&tmp, &path) {
        tracing::warn!(error = %err, "failed to rename services.json.tmp");
    }
}

async fn resolve_service_port(
    state: &AppState,
    agent_name: &str,
    service_name: &str,
) -> Option<u16> {
    let registry = state.service_registry.read().await;
    registry.get(agent_name)?.get(service_name).copied()
}

const SERVICE_PORT_MIN: u16 = 49152;
const SERVICE_PORT_MAX: u16 = 65535;

#[derive(Deserialize)]
struct RegisterServiceBody {
    name: String,
}

/// Collect all ports in use across all agents in the service registry.
fn all_registered_ports(registry: &HashMap<String, HashMap<String, u16>>) -> Vec<u16> {
    registry.values().flat_map(|services| services.values().copied()).collect()
}

/// Find a free port not used by any registered service.
fn allocate_service_port(registry: &HashMap<String, HashMap<String, u16>>) -> Option<u16> {
    let used = all_registered_ports(registry);
    (SERVICE_PORT_MIN..=SERVICE_PORT_MAX).find(|p| !used.contains(p))
}

async fn register_service_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<RegisterServiceBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let service_name = body.name.trim().to_string();

    if service_name.is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "name is required"));
    }
    if RESERVED_SERVICE_NAMES.contains(&service_name.as_str()) {
        return Err(err_response(StatusCode::BAD_REQUEST, &format!("reserved service name: {}", service_name)));
    }

    let docker_name = docker::container_name(&name);
    let exists = tokio::task::spawn_blocking(move || docker::container_status(&docker_name) != docker::ContainerStatus::NotFound)
        .await
        .unwrap_or(false);
    if !exists {
        return Err(err_response(StatusCode::NOT_FOUND, &format!("agent '{}' not found", name)));
    }

    let mut registry = state.service_registry.write().await;

    // Reuse existing port if already registered, otherwise allocate a new one
    let port = if let Some(existing) = registry.get(&name).and_then(|s| s.get(&service_name)).copied() {
        existing
    } else {
        allocate_service_port(&registry)
            .ok_or_else(|| err_response(StatusCode::SERVICE_UNAVAILABLE, "no free ports available"))?
    };

    registry.entry(name.clone()).or_default().insert(service_name.clone(), port);
    save_service_registry(&registry);
    tracing::info!(agent = %name, service = %service_name, port, "service registered");
    Ok(Json(serde_json::json!({"ok": true, "port": port})))
}

async fn unregister_service_handler(
    State(state): State<SharedState>,
    Path((name, service_name)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let mut registry = state.service_registry.write().await;
    if let Some(agent_services) = registry.get_mut(&name) {
        agent_services.remove(&service_name);
        if agent_services.is_empty() {
            registry.remove(&name);
        }
    }
    save_service_registry(&registry);
    tracing::info!(agent = %name, service = %service_name, "service unregistered");
    Ok(ok_json())
}

async fn list_services_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Json<serde_json::Value> {
    let registry = state.service_registry.read().await;
    let services = registry.get(&name).cloned().unwrap_or_default();
    Json(serde_json::json!({"services": services}))
}

// --- Agent wildcard proxy (HTTP + WS) for /agents/{name}/* ---

async fn agent_proxy_handler(
    State(state): State<SharedState>,
    Path((name, path)): Path<(String, String)>,
    request: Request,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    use axum::extract::FromRequestParts;

    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);

    let lock = state.agent_lock(&name).await;
    let guard = lock.read_owned().await;

    let cname_clone = cname.clone();
    tokio::task::spawn_blocking(move || docker::ensure_running(&cname_clone))
        .await
        .map_err(map_join_err)?
        .map_err(map_docker_err)?;
    let cname_clone = cname.clone();
    let agent_port = tokio::task::spawn_blocking(move || docker::get_container_port(&cname_clone))
        .await
        .map_err(map_join_err)?;

    // Check if the first path segment matches a registered service.
    // If so, route directly to that service's port with the prefix stripped.
    let first_segment = path.split('/').next().unwrap_or("");
    let (target_port, stripped_path) = if !first_segment.is_empty() {
        if let Some(service_port) = resolve_service_port(&state, &name, first_segment).await {
            let rest = &path[first_segment.len()..];
            let rest = if rest.is_empty() { "/" } else { rest };
            (service_port, rest.to_string())
        } else {
            (agent_port, format!("/{}", path))
        }
    } else {
        (agent_port, format!("/{}", path))
    };

    // Append query string.
    let mut target_path = stripped_path;
    if let Some(q) = request.uri().query() {
        target_path.push('?');
        target_path.push_str(q);
    }

    let is_ws_upgrade = request
        .headers()
        .get("upgrade")
        .map(|v| v.as_bytes().eq_ignore_ascii_case(b"websocket"))
        .unwrap_or(false);

    if is_ws_upgrade {
        let (mut parts, _body) = request.into_parts();
        let ws = match WebSocketUpgrade::from_request_parts(&mut parts, &state).await {
            Ok(ws) => ws,
            Err(e) => {
                return Err(err_response(
                    StatusCode::BAD_REQUEST,
                    &format!("invalid ws upgrade: {}", e),
                ));
            }
        };
        Ok(ws.on_upgrade(move |socket| async move {
            drop(guard);
            ws_proxy(socket, target_port, &target_path).await;
        }))
    } else {
        drop(guard);
        forward_http_to_container(&state.http_client, target_port, &target_path, request).await
    }
}

async fn forward_http_to_container(
    client: &reqwest::Client,
    port: u16,
    target_path: &str,
    request: Request,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    let (parts, body) = request.into_parts();
    let url = format!("http://localhost:{}{}", port, target_path);

    let method = reqwest::Method::from_bytes(parts.method.as_str().as_bytes())
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &format!("bad method: {}", e)))?;

    let body_bytes = axum::body::to_bytes(body, PROXY_MAX_BODY_BYTES)
        .await
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &format!("read body: {}", e)))?;

    let mut req_builder = client.request(method, &url);
    for (name, value) in parts.headers.iter() {
        // Skip hop-by-hop headers — reqwest sets host/transfer-encoding itself.
        let n = name.as_str().to_ascii_lowercase();
        if matches!(n.as_str(), "host" | "connection" | "transfer-encoding" | "content-length") {
            continue;
        }
        req_builder = req_builder.header(name.as_str(), value.as_bytes());
    }
    if !body_bytes.is_empty() {
        req_builder = req_builder.body(body_bytes.to_vec());
    }

    let upstream = req_builder.send().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("container unreachable: {}", e),
        )
    })?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::BAD_GATEWAY);
    let mut builder = Response::builder().status(status);
    for (name, value) in upstream.headers().iter() {
        let n = name.as_str().to_ascii_lowercase();
        if matches!(n.as_str(), "transfer-encoding" | "connection" | "content-length") {
            continue;
        }
        builder = builder.header(name.as_str(), value.as_bytes());
    }

    let stream = upstream.bytes_stream();
    let body = Body::from_stream(stream);
    builder
        .body(body)
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &format!("build response: {}", e)))
}

// --- Backup/Restore ---

async fn create_backup_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<crate::types::BackupInfo>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(agent = %name, "creating manual backup");
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let name_clone = name.clone();
    let backup = tokio::task::spawn_blocking(move || {
        docker::create_backup(&name_clone, crate::types::BackupType::Manual)
    })
    .await
    .unwrap()
    .map_err(map_docker_err)?;

    tracing::info!(agent = %name, backup_id = %backup.id, size = backup.size, "backup created");
    Ok(Json(backup))
}

async fn list_backups_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<Vec<crate::types::BackupInfo>>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.read().await;

    let name_clone = name.clone();
    let backups = tokio::task::spawn_blocking(move || docker::list_backups(&name_clone))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    Ok(Json(backups))
}

#[derive(Deserialize)]
struct RestoreBackupPath {
    name: String,
    backup_id: String,
}

async fn restore_backup_handler(
    State(state): State<SharedState>,
    Path(path): Path<RestoreBackupPath>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&path.name).await;
    let _guard = lock.write().await;

    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "restoring backup");
    let name = path.name.clone();
    let backup_id = path.backup_id.clone();
    let vestad_port = state.vestad_port;
    tokio::task::spawn_blocking(move || docker::restore_backup(&name, &backup_id, vestad_port))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "backup restored");
    Ok(Json(serde_json::json!({"ok": true})))
}

#[derive(Deserialize)]
struct DeleteBackupPath {
    name: String,
    backup_id: String,
}

async fn delete_backup_handler(
    State(state): State<SharedState>,
    Path(path): Path<DeleteBackupPath>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&path.name).await;
    let _guard = lock.write().await;

    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "deleting backup");
    let backup_id = path.backup_id.clone();
    tokio::task::spawn_blocking(move || docker::delete_backup(&backup_id))
        .await
        .unwrap()
        .map_err(map_docker_err)?;

    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "backup deleted");
    Ok(Json(serde_json::json!({"ok": true})))
}

// --- Auto-backup settings ---

async fn get_auto_backup_handler(
    State(state): State<SharedState>,
) -> Json<serde_json::Value> {
    let enabled = state.auto_backup_enabled.load(Ordering::Relaxed);
    let retention = *state.backup_retention.lock().await;
    Json(serde_json::json!({
        "enabled": enabled,
        "retention": retention,
    }))
}

async fn set_auto_backup_handler(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if let Some(enabled) = body["enabled"].as_bool() {
        state.auto_backup_enabled.store(enabled, Ordering::Relaxed);
        tracing::info!(enabled, "auto-backup toggled");
    }

    let mut retention = state.backup_retention.lock().await;
    if let Some(ret) = body.get("retention") {
        if let Some(d) = ret["daily"].as_u64() {
            retention.daily = d as usize;
        }
        if let Some(w) = ret["weekly"].as_u64() {
            retention.weekly = w as usize;
        }
        if let Some(m) = ret["monthly"].as_u64() {
            retention.monthly = m as usize;
        }
        tracing::info!(daily = retention.daily, weekly = retention.weekly, monthly = retention.monthly, "backup retention updated");
    }

    let enabled = state.auto_backup_enabled.load(Ordering::Relaxed);
    Ok(Json(serde_json::json!({
        "enabled": enabled,
        "retention": *retention,
    })))
}

// --- Port file ---

pub fn write_port_file(config_dir: &std::path::Path, port: u16) {
    let port_path = config_dir.join("port");
    std::fs::write(&port_path, port.to_string()).ok();
}

// --- PID file ---

pub fn acquire_pid_lock(config_dir: &std::path::Path) -> Result<std::fs::File, String> {
    let pid_path = config_dir.join("vestad.pid");
    std::fs::create_dir_all(config_dir)
        .map_err(|e| format!("failed to create config dir: {}", e))?;

    let file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&pid_path)
        .map_err(|e| format!("failed to open pid file: {}", e))?;

    #[cfg(unix)]
    {
        use std::io::Write;
        use std::os::unix::io::AsRawFd;
        let fd = file.as_raw_fd();
        let ret = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
        if ret != 0 {
            return Err("vestad already running".into());
        }
        let mut f = &file;
        write!(f, "{}", std::process::id()).ok();
    }

    Ok(file)
}


// --- Router ---

pub fn build_router(state: SharedState) -> Router {

    let public = Router::new()
        .route("/health", get(health))
        .route("/auth/session", post(create_session_handler))
        .route("/auth/refresh", post(refresh_session_handler));

    let protected = Router::new()
        .route("/version", get(version))
        .route("/self-update", post(self_update_handler))
        .route("/tunnel", get(tunnel_handler))
        .route("/agents", get(list_agents_handler))
        .route("/agents", post(create_agent_handler))
        .route("/agents/start", post(start_all_handler))
        .route("/agents/{name}", get(agent_status_handler))
        .route("/agents/{name}/start", post(start_agent_handler))
        .route("/agents/{name}/stop", post(stop_agent_handler))
        .route("/agents/{name}/restart", post(restart_agent_handler))
        .route("/agents/{name}/destroy", post(destroy_agent_handler))
        .route("/agents/{name}/rebuild", post(rebuild_agent_handler))
        .route("/agents/{name}/wait-ready", get(wait_ready_handler))
        .route("/agents/{name}/auth", post(start_auth_handler))
        .route("/agents/{name}/auth/code", post(complete_auth_handler))
        .route("/agents/{name}/auth/token", post(inject_token_handler))
        .route("/agents/{name}/logs", get(logs_handler))
        .route("/agents/{name}/backups", post(create_backup_handler))
        .route("/agents/{name}/backups", get(list_backups_handler))
        .route("/agents/{name}/backups/{backup_id}/restore", post(restore_backup_handler))
        .route("/agents/{name}/backups/{backup_id}", axum::routing::delete(delete_backup_handler))
        .route("/settings/auto-backup", get(get_auto_backup_handler))
        .route("/settings/auto-backup", axum::routing::put(set_auto_backup_handler))
        .route("/agents/{name}/{*path}", any(agent_proxy_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth_middleware,
        ));

    // Service registry: localhost (agent containers) can access without auth,
    // external requests (app frontend) require auth
    let services = Router::new()
        .route("/agents/{name}/services", post(register_service_handler))
        .route("/agents/{name}/services", get(list_services_handler))
        .route("/agents/{name}/services/{service}", axum::routing::delete(unregister_service_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            localhost_or_auth_middleware,
        ))
        .with_state(state.clone());

    Router::new()
        .merge(public)
        .merge(services)
        .merge(protected)
        .layer(
            tower_http::cors::CorsLayer::new()
                .allow_origin(tower_http::cors::Any)
                .allow_methods(tower_http::cors::Any)
                .allow_headers(tower_http::cors::Any),
        )
        .layer(tower_http::trace::TraceLayer::new_for_http())
        .with_state(state)
}

// --- Server start ---

// --- Auto-backup background task ---

fn spawn_auto_backup_task(state: SharedState) {
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(AUTO_BACKUP_CHECK_INTERVAL_SECS)).await;

            if !state.auto_backup_enabled.load(Ordering::Relaxed) {
                tracing::debug!("auto-backup: disabled, skipping cycle");
                continue;
            }

            let agents = tokio::task::spawn_blocking(docker::list_agent_names)
                .await
                .unwrap_or_default();

            if agents.is_empty() {
                tracing::debug!("auto-backup: no agents found, skipping cycle");
                continue;
            }

            tracing::info!(agent_count = agents.len(), "auto-backup: starting cycle");

            let now_epoch = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let today_date = &docker::now_timestamp()[..8];
            let seven_days_ago = docker::now_timestamp_from_epoch(now_epoch - 7 * 86400);
            let thirty_days_ago = docker::now_timestamp_from_epoch(now_epoch - 30 * 86400);

            let retention = *state.backup_retention.lock().await;

            for name in &agents {
                let lock = state.agent_lock(name).await;
                let _guard = lock.write().await;

                let name_clone = name.clone();
                let today = today_date.to_string();
                let week_ago = seven_days_ago.clone();
                let month_ago = thirty_days_ago.clone();
                let ret = retention;

                let result = tokio::task::spawn_blocking(move || -> Result<(), docker::DockerError> {
                    if let Some(age) = docker::container_age_secs(&name_clone) {
                        if age < docker::MIN_AGE_FOR_BACKUP_SECS {
                            tracing::debug!(agent = %name_clone, age_hours = age / 3600, "auto-backup: skipping young agent");
                            return Ok(());
                        }
                    }

                    let mut backups = docker::list_backups(&name_clone)?;

                    let has_daily_today = backups.iter().any(|b| {
                        b.backup_type == crate::types::BackupType::Daily
                            && b.created_at.starts_with(&today)
                    });

                    if !has_daily_today {
                        tracing::info!(agent = %name_clone, backup_type = "daily", "auto-backup: creating backup");
                        let new = docker::create_backup(&name_clone, crate::types::BackupType::Daily)?;
                        backups.insert(0, new);
                    }

                    let has_recent_weekly = backups.iter().any(|b| {
                        b.backup_type == crate::types::BackupType::Weekly && b.created_at >= week_ago
                    });
                    if !has_recent_weekly {
                        tracing::info!(agent = %name_clone, backup_type = "weekly", "auto-backup: creating backup");
                        let new = docker::create_backup(&name_clone, crate::types::BackupType::Weekly)?;
                        backups.insert(0, new);
                    }

                    let has_recent_monthly = backups.iter().any(|b| {
                        b.backup_type == crate::types::BackupType::Monthly && b.created_at >= month_ago
                    });
                    if !has_recent_monthly {
                        tracing::info!(agent = %name_clone, backup_type = "monthly", "auto-backup: creating backup");
                        let new = docker::create_backup(&name_clone, crate::types::BackupType::Monthly)?;
                        backups.insert(0, new);
                    }

                    docker::cleanup_backups(&backups, &ret);
                    Ok(())
                })
                .await
                .unwrap_or_else(|e| Err(docker::DockerError::Failed(e.to_string())));

                if let Err(e) = result {
                    tracing::error!(agent = %name, error = %e, "auto-backup: failed");
                }
            }

            tracing::info!(agent_count = agents.len(), "auto-backup: cycle complete");
        }
    });
}

// --- Update-check background task ---

fn spawn_update_check_task(state: SharedState) {
    tokio::spawn(async move {
        let mut last_attempted: Option<String> = None;
        loop {
            let info_result = tokio::task::spawn_blocking(update_check::check_once).await;
            match info_result {
                Ok(Ok(info)) => {
                    let mut slot = state.update_info.lock().await;
                    *slot = Some(info.clone());
                    drop(slot);

                    if info.update_available
                        && last_attempted.as_ref() != Some(&info.latest)
                        && !state.updating.swap(true, std::sync::atomic::Ordering::SeqCst)
                    {
                        tracing::info!(
                            "update available: v{} -> v{}, auto-updating...",
                            info.current, info.latest
                        );
                        last_attempted = Some(info.latest.clone());

                        match tokio::task::spawn_blocking(self_update::perform_update).await {
                            Ok(Ok(true)) => {
                                tracing::info!("auto-update: restarting via systemd");
                                return;
                            }
                            Ok(Ok(false)) => {
                                tracing::info!("auto-update: binary replaced, awaiting restart");
                            }
                            Ok(Err(e)) => tracing::error!("auto-update failed: {}", e),
                            Err(e) => tracing::error!("auto-update task panicked: {}", e),
                        }
                        state.updating.store(false, std::sync::atomic::Ordering::SeqCst);
                    }
                }
                Ok(Err(e)) => tracing::warn!("update check failed: {}", e),
                Err(e) => tracing::error!("update check task failed: {}", e),
            }
            tokio::time::sleep(tokio::time::Duration::from_secs(update_check::CHECK_INTERVAL_SECS)).await;
        }
    });
}

// --- Server start ---

pub async fn run_server(port: u16, api_key: String, cert_pem: String, key_pem: String, tunnel_url: Option<String>) {
    let state = Arc::new(AppState::new(api_key, port, tunnel_url));
    let app = build_router(state.clone());
    spawn_auto_backup_task(state.clone());
    spawn_update_check_task(state);

    tracing::info!(port, "server listening");

    let rustls_config = axum_server::tls_rustls::RustlsConfig::from_pem(
        cert_pem.into_bytes(),
        key_pem.into_bytes(),
    )
    .await
    .expect("failed to configure TLS");

    // HTTPS on 0.0.0.0 for remote access
    let https_addr = std::net::SocketAddr::from(([0, 0, 0, 0], port));

    // HTTP on 127.0.0.1 for local access (avoids self-signed cert issues)
    let http_port = port + 1;
    let http_addr = std::net::SocketAddr::from(([127, 0, 0, 1], http_port));

    tracing::info!(http_port, "http server listening on localhost");

    let http_app = app.clone();
    let http_handle = tokio::spawn(async move {
        let listener = tokio::net::TcpListener::bind(http_addr)
            .await
            .expect("failed to bind http listener");
        axum::serve(listener, http_app.into_make_service_with_connect_info::<std::net::SocketAddr>())
            .await
            .expect("http server failed");
    });

    let https_handle = tokio::spawn(async move {
        axum_server::bind_rustls(https_addr, rustls_config)
            .serve(app.into_make_service_with_connect_info::<std::net::SocketAddr>())
            .await
            .expect("https server failed");
    });

    tokio::select! {
        r = http_handle => r.expect("http task panicked"),
        r = https_handle => r.expect("https task panicked"),
    }
}
