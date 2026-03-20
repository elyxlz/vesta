use axum::{
    body::Body,
    extract::{Path, Query, State, WebSocketUpgrade},
    http::{HeaderMap, StatusCode},
    middleware::{self, Next},
    response::{
        sse::{Event, KeepAlive},
        IntoResponse, Response, Sse,
    },
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::docker;

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
    // 10 year validity
    params.not_after = rcgen::date_time_ymd(2036, 1, 1);

    let key_pair = rcgen::KeyPair::generate().unwrap();
    let cert = params.self_signed(&key_pair).unwrap();

    let cert_pem = cert.pem();
    let key_pem = key_pair.serialize_pem();

    // Compute SHA-256 fingerprint of the DER certificate
    let der_bytes = cert.der();
    let digest = {
        use std::io::Write;
        let mut hasher = Sha256::new();
        hasher.write_all(der_bytes).unwrap();
        hasher.finalize()
    };
    let fingerprint = format!(
        "sha256:{}",
        digest
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

// Simple SHA-256 for certificate fingerprint (no external dep)
struct Sha256 {
    data: Vec<u8>,
}
impl Sha256 {
    fn new() -> Self {
        Self { data: Vec::new() }
    }
    fn finalize(self) -> Vec<u8> {
        // Use openssl for hashing since we already depend on it at runtime
        let output = std::process::Command::new("openssl")
            .args(["dgst", "-sha256", "-binary"])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .and_then(|mut child| {
                use std::io::Write;
                child.stdin.take().unwrap().write_all(&self.data).ok();
                child.wait_with_output()
            })
            .expect("openssl sha256 failed");
        output.stdout
    }
}
impl std::io::Write for Sha256 {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.data.extend_from_slice(buf);
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
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

    let key: String = (0..32)
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
    auth_sessions: Mutex<HashMap<String, AuthSession>>,
    agent_locks: Mutex<HashMap<String, Arc<tokio::sync::RwLock<()>>>>,
}

impl AppState {
    fn new(api_key: String) -> Self {
        Self {
            api_key,
            auth_sessions: Mutex::new(HashMap::new()),
            agent_locks: Mutex::new(HashMap::new()),
        }
    }

    async fn agent_lock(&self, name: &str) -> Arc<tokio::sync::RwLock<()>> {
        let mut locks = self.agent_locks.lock().await;
        locks
            .entry(name.to_string())
            .or_insert_with(|| Arc::new(tokio::sync::RwLock::new(())))
            .clone()
    }
}

type SharedState = Arc<AppState>;

// --- Auth middleware ---

async fn auth_middleware(
    State(state): State<SharedState>,
    headers: HeaderMap,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    let path = request.uri().path();

    // /health requires no auth
    if path == "/health" {
        return next.run(request).await;
    }

    // Check Bearer header first, then query param ?token= (for WebSocket)
    let bearer_ok = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|token| token == state.api_key)
        .unwrap_or(false);

    let query_ok = if !bearer_ok {
        request
            .uri()
            .query()
            .and_then(|q| {
                q.split('&')
                    .find_map(|p| p.strip_prefix("token="))
            })
            .map(|t| t == state.api_key)
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

// --- Response helpers ---

fn ok_json() -> Json<serde_json::Value> {
    Json(serde_json::json!({"ok": true}))
}

fn err_response(status: StatusCode, msg: &str) -> (StatusCode, Json<serde_json::Value>) {
    (status, Json(serde_json::json!({"error": msg})))
}

fn map_err(e: String) -> (StatusCode, Json<serde_json::Value>) {
    let status = if e.contains("not found") {
        StatusCode::NOT_FOUND
    } else if e.contains("already exists") {
        StatusCode::CONFLICT
    } else if e.contains("not running") {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::INTERNAL_SERVER_ERROR
    };
    err_response(status, &e)
}

// --- Handlers ---

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"ok": true}))
}

async fn version() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "version": env!("CARGO_PKG_VERSION"),
        "api_compat": "0.2",
    }))
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
    build: Option<bool>,
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
    let build = body.build.unwrap_or(false);

    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let name =
        tokio::task::spawn_blocking(move || docker::create_agent(&name, build))
            .await
            .unwrap()
            .map_err(map_err)?;

    Ok((StatusCode::CREATED, Json(serde_json::json!({"name": name}))))
}

async fn agent_status_handler(
    Path(name): Path<String>,
) -> Result<Json<docker::StatusJson>, (StatusCode, Json<serde_json::Value>)> {
    let status = tokio::task::spawn_blocking(move || docker::get_status(&name))
        .await
        .unwrap()
        .map_err(map_err)?;
    Ok(Json(status))
}

async fn start_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::start_agent(&name))
        .await
        .unwrap()
        .map_err(map_err)?;
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
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::stop_agent(&name))
        .await
        .unwrap()
        .map_err(map_err)?;
    Ok(ok_json())
}

async fn restart_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::restart_agent(&name))
        .await
        .unwrap()
        .map_err(map_err)?;
    Ok(ok_json())
}

async fn destroy_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::destroy_agent(&name))
        .await
        .unwrap()
        .map_err(map_err)?;
    Ok(ok_json())
}

async fn rebuild_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    tokio::task::spawn_blocking(move || docker::rebuild_agent(&name))
        .await
        .unwrap()
        .map_err(map_err)?;
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
    tokio::task::spawn_blocking(move || docker::wait_ready(&name, timeout))
        .await
        .unwrap()
        .map_err(|e| err_response(StatusCode::SERVICE_UNAVAILABLE, &e))?;
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
    docker::validate_name(&name).map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;
    let cname = docker::container_name(&name);
    docker::ensure_exists(&cname).map_err(map_err)?;

    let (auth_url, code_verifier, auth_state) = docker::start_auth_flow();
    let session_id: String = (0..16)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect();

    let mut sessions = state.auth_sessions.lock().await;
    // Clean expired sessions (older than 10 minutes)
    let now = std::time::Instant::now();
    sessions.retain(|_, s| now.duration_since(s.created) < std::time::Duration::from_secs(600));

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

async fn complete_auth_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<AuthCodeBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;
    let cname = docker::container_name(&name);
    docker::ensure_exists(&cname).map_err(map_err)?;

    let session = {
        let mut sessions = state.auth_sessions.lock().await;
        sessions
            .remove(&body.session_id)
            .ok_or_else(|| err_response(StatusCode::BAD_REQUEST, "invalid or expired session"))?
    };

    let code = body.code.clone();
    let credentials = tokio::task::spawn_blocking(move || {
        docker::complete_auth_flow(&code, &session.code_verifier, &session.state)
    })
    .await
    .unwrap()
    .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;

    let cname_clone = cname.clone();
    tokio::task::spawn_blocking(move || docker::inject_credentials(&cname_clone, &credentials))
        .await
        .unwrap()
        .map_err(map_err)?;

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
    docker::validate_name(&name).map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;
    let cname = docker::container_name(&name);
    docker::ensure_exists(&cname).map_err(map_err)?;

    let credentials = body.token.to_string();
    tokio::task::spawn_blocking(move || docker::inject_credentials(&cname, &credentials))
        .await
        .unwrap()
        .map_err(map_err)?;

    Ok(ok_json())
}

// --- SSE Logs ---

async fn logs_handler(
    Path(name): Path<String>,
) -> Result<Sse<impl futures_core::Stream<Item = Result<Event, std::io::Error>>>, (StatusCode, Json<serde_json::Value>)>
{
    docker::validate_name(&name).map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;
    let cname = docker::container_name(&name);
    docker::ensure_running(&cname)
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;

    let stream = async_stream::stream! {
        let mut child = match tokio::process::Command::new("docker")
            .args(["exec", &cname, "tail", "-n", "500", "-f", docker::VESTA_LOG_PATH])
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

// --- WebSocket proxy ---

async fn ws_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Query(params): Query<HashMap<String, String>>,
    ws: WebSocketUpgrade,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    // Auth via query param
    let token = params
        .get("token")
        .ok_or_else(|| err_response(StatusCode::UNAUTHORIZED, "missing token parameter"))?;
    if token != &state.api_key {
        return Err(err_response(StatusCode::UNAUTHORIZED, "invalid token"));
    }

    docker::validate_name(&name).map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;
    let cname = docker::container_name(&name);
    docker::ensure_running(&cname).map_err(map_err)?;

    let port = docker::get_container_port(&cname);

    Ok(ws.on_upgrade(move |socket| ws_proxy(socket, port)))
}

async fn ws_proxy(client_ws: axum::extract::ws::WebSocket, agent_port: u16) {
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    let url = format!("ws://localhost:{}/ws", agent_port);
    let agent_ws = match tokio_tungstenite::connect_async(&url).await {
        Ok((ws, _)) => ws,
        Err(_) => return,
    };

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
}

// --- Backup/Restore ---

async fn backup_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.write().await;

    let name_clone = name.clone();
    let (backup_tag, was_running) =
        tokio::task::spawn_blocking(move || docker::backup_prepare(&name_clone))
            .await
            .unwrap()
            .map_err(map_err)?;

    // Stream docker save | gzip
    let tag = backup_tag.clone();
    let stream = async_stream::stream! {
        let mut docker_save = match tokio::process::Command::new("docker")
            .args(["save", &tag])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                yield Err(std::io::Error::other(e));
                return;
            }
        };

        let child_stdout = docker_save.stdout.take().unwrap();
        let mut gzip = match tokio::process::Command::new("gzip")
            .stdin(child_stdout.into_owned_fd().unwrap())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                yield Err(std::io::Error::other(e));
                return;
            }
        };

        let stdout = gzip.stdout.take().unwrap();
        let mut reader = tokio::io::BufReader::new(stdout);
        let mut buf = vec![0u8; 65536];

        loop {
            match tokio::io::AsyncReadExt::read(&mut reader, &mut buf).await {
                Ok(0) => break,
                Ok(n) => yield Ok(bytes::Bytes::copy_from_slice(&buf[..n])),
                Err(e) => {
                    yield Err(e);
                    break;
                }
            }
        }

        docker_save.wait().await.ok();
        gzip.wait().await.ok();
    };

    // Cleanup after response is sent
    let name_for_cleanup = name.clone();
    let tag_for_cleanup = backup_tag.clone();
    tokio::spawn(async move {
        // Give the stream a moment to fully flush
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        tokio::task::spawn_blocking(move || {
            docker::backup_cleanup(&name_for_cleanup, &tag_for_cleanup, was_running);
        })
        .await
        .ok();
    });

    let body = Body::from_stream(stream);
    Ok(Response::builder()
        .header("content-type", "application/gzip")
        .header(
            "content-disposition",
            format!("attachment; filename=\"{}.tar.gz\"", name),
        )
        .body(body)
        .unwrap())
}

#[derive(Deserialize)]
struct RestoreQuery {
    name: Option<String>,
    replace: Option<bool>,
}

async fn restore_handler(
    Query(query): Query<RestoreQuery>,
    body: axum::body::Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    // Write body to temp file, gunzip | docker load
    let tmp_dir = std::env::temp_dir().join(format!("vesta_restore_{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir)
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &format!("temp dir: {}", e)))?;
    let gz_path = tmp_dir.join("backup.tar.gz");
    std::fs::write(&gz_path, &body)
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &format!("write: {}", e)))?;

    let name_override = query.name.clone();
    let replace = query.replace.unwrap_or(false);

    let result = tokio::task::spawn_blocking(move || {
        // gunzip | docker load
        let file = std::fs::File::open(&gz_path)
            .map_err(|e| format!("failed to open backup: {}", e))?;
        let mut gunzip = std::process::Command::new("gunzip")
            .arg("-c")
            .stdin(file)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::inherit())
            .spawn()
            .map_err(|_| "failed to run gunzip".to_string())?;

        let load_output = std::process::Command::new("docker")
            .args(["load"])
            .stdin(gunzip.stdout.take().unwrap())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::inherit())
            .output()
            .map_err(|_| "failed to run docker load".to_string())?;

        let gunzip_status = gunzip.wait().map_err(|_| "gunzip failed".to_string())?;
        if !gunzip_status.success() || !load_output.status.success() {
            return Err("failed to load backup".to_string());
        }

        let load_stdout = String::from_utf8_lossy(&load_output.stdout);
        let loaded_image = load_stdout
            .lines()
            .find_map(|l| l.strip_prefix("Loaded image: "))
            .ok_or("could not determine loaded image")?
            .trim()
            .to_string();

        docker::restore_agent(&loaded_image, name_override.as_deref(), replace)
    })
    .await
    .unwrap()
    .map_err(map_err)?;

    // Cleanup temp
    let _ = std::fs::remove_dir_all(&tmp_dir);

    Ok(Json(serde_json::json!({"name": result})))
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

pub fn build_router(api_key: String) -> Router {
    let state = Arc::new(AppState::new(api_key));

    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/agents", get(list_agents_handler))
        .route("/agents", post(create_agent_handler))
        .route("/agents/start", post(start_all_handler))
        .route(
            "/agents/restore",
            post(restore_handler).layer(axum::extract::DefaultBodyLimit::max(4 * 1024 * 1024 * 1024)), // 4GB
        )
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
        .route("/agents/{name}/ws", get(ws_handler))
        .route("/agents/{name}/backup", post(backup_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth_middleware,
        ))
        .layer(
            tower_http::cors::CorsLayer::new()
                .allow_origin(tower_http::cors::Any)
                .allow_methods(tower_http::cors::Any)
                .allow_headers(tower_http::cors::Any),
        )
        .with_state(state)
}

// --- Server start ---

pub async fn run_server(port: u16, api_key: String, cert_pem: String, key_pem: String) {
    let app = build_router(api_key);

    let rustls_config = axum_server::tls_rustls::RustlsConfig::from_pem(
        cert_pem.into_bytes(),
        key_pem.into_bytes(),
    )
    .await
    .expect("failed to configure TLS");

    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], port));
    eprintln!("vestad listening on https://0.0.0.0:{}", port);

    axum_server::bind_rustls(addr, rustls_config)
        .serve(app.into_make_service())
        .await
        .expect("server failed");
}
