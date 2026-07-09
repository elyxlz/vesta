use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    middleware,
    response::{
        sse::{Event, KeepAlive},
        IntoResponse, Sse,
    },
    routing::{any, get, post, put},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

use crate::settings::{load_settings, save_settings, AgentBackupOverride, BackupGlobalSettings, ServiceEntry, Settings, UserDesired};
use crate::state::{err_response, map_docker_err, ok_json, AppState, SharedState};
use crate::{agent_provider, agent_proxy, agent_status, auth, backup, control_ws, docker, self_update, systemd, update_check};

const GATEWAY_RESTART_DELAY_MS: u64 = 200;

// Upper bound on a single control/JSON request (docker/restic handlers already carry their own
// inner timeouts; this caps the HTTP layer so a stalled handler cannot hold a connection open
// forever). Deliberately NOT applied to the WS-upgrade route or the long-lived SSE/proxy
// streams (logs tail -f, backup create/restore progress, agent proxy), which must stay open.
const CONTROL_REQUEST_TIMEOUT_SECS: u64 = 120;

// Agent create and rebuild build/pull the image (minutes on a cold cache), which the 120s control
// deadline would 408 mid-progress. A generous deadline that still bounds a truly-hung build.
const LONGRUN_REQUEST_TIMEOUT_SECS: u64 = 1800;

const API_KEY_BYTES: usize = 32;

const RESERVED_SERVICE_NAMES: &[&str] = &[
    "start", "stop", "restart", "destroy", "rebuild",
    "auth", "logs", "tree", "file", "backups", "settings", "services",
];
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

/// Acquire the per-agent serialization lock as an owned write guard — the single
/// owner of the `agent_lock(name).write_owned()` idiom every mutating agent
/// handler repeats. Owned so it can be held across the rest of an `async move`
/// (e.g. the spawned backup/restore pipelines) without borrowing `state`.
async fn agent_write_guard(state: &AppState, name: &str) -> tokio::sync::OwnedRwLockWriteGuard<()> {
    state.agent_lock(name).await.write_owned().await
}

/// Run a container-mutating operation on a detached task and await its single result over a oneshot
/// channel. Load-bearing invariant for a self-restart: the request's client is the agent inside the
/// very container the operation stops, so the loopback connection drops the instant the container
/// goes down — and an inline `.await` would be cancelled mid-recreate, stranding the agent stopped.
/// Spawning runs the op to completion regardless of the client; the request only observes its result
/// (so a still-connected app caller still gets a truthful response). JSON analogue of the SSE
/// `spawn_pipeline_sse` used by backup/restore, which fixed this same drop-cancellation class.
async fn spawn_detached<Fut>(op: Fut) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)>
where
    Fut: std::future::Future<Output = Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)>> + Send + 'static,
{
    let (tx, rx) = tokio::sync::oneshot::channel();
    tokio::spawn(async move {
        let _ = tx.send(op.await);
    });
    rx.await
        .unwrap_or_else(|_| Err(err_response(StatusCode::INTERNAL_SERVER_ERROR, "restart task panicked")))
}

// --- Handlers ---

async fn health() -> Json<serde_json::Value> {
    let user = std::env::var("USER")
        .or_else(|_| std::env::var("LOGNAME"))
        .unwrap_or_else(|_| "unknown".into());
    Json(serde_json::json!({"ok": true, "user": user}))
}

// Unauthenticated: lets apps/web tell a hosted (vesta.run) VM from a self-hosted
// one, since both get `*.vesta.run` tunnels and the URL alone can't distinguish.
// Managed boxes are gated by VESTA_CLOUD_MANAGED (legacy VESTA_MANAGED still
// honored) via the control plane's cloud-init; the app uses this single bit to
// surface the hosted account/billing page.
async fn info() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "managed": crate::is_cloud_managed() }))
}

/// `POST /agents/{name}/account-token` — mint a short-lived server-identity token
/// for the on-box agent (issue #20).
///
/// Agent-token authenticated (the agent proves itself with its `X-Agent-Token`);
/// vestad then signs `{ sub: VESTA_CLOUD_SERVER_ID, typ: "server-identity" }` with its
/// `api_key` and hands it back. The agent carries this to the control plane's
/// `/api/account/*` to read its plan or open a billing portal. vestad makes NO
/// network call — it only signs locally; the agent does the talking. The
/// `api_key` never enters the agent container, only this 10-minute token does.
async fn account_token_handler(State(state): State<SharedState>) -> axum::response::Response {
    if !crate::is_cloud_managed() {
        return err_response(StatusCode::NOT_FOUND, "not a cloud-managed server").into_response();
    }
    let Ok(server_id) = std::env::var("VESTA_CLOUD_SERVER_ID") else {
        // Managed but VESTA_CLOUD_SERVER_ID not seeded — nothing to mint.
        return err_response(StatusCode::NOT_FOUND, "no server identity available").into_response();
    };
    let token = crate::jwt::create_server_identity_token(&state.api_key, &server_id);
    Json(serde_json::json!({
        "token": token,
        "expires_in": crate::jwt::SERVER_IDENTITY_TTL,
    }))
    .into_response()
}

/// `GET /agents/{name}/workspace.bundle` — the host's workspace bundle (branch + agent-v*
/// tags), fetched by the box's fetch-workspace.sh during attach/sync. Agent-token
/// authenticated; the middleware scopes the token to `{name}`, so a box can only pull
/// through its own identity (the content is host-global either way).
async fn workspace_bundle_handler(State(state): State<SharedState>) -> axum::response::Response {
    workspace_bundle_response(&state.env_config.config_dir).await
}

async fn workspace_bundle_response(config_dir: &std::path::Path) -> axum::response::Response {
    let path = crate::workspace::bundle_path(config_dir);
    match tokio::fs::read(&path).await {
        Ok(bytes) => ([(axum::http::header::CONTENT_TYPE, "application/octet-stream")], bytes).into_response(),
        Err(_) => err_response(StatusCode::NOT_FOUND, "workspace bundle not built yet").into_response(),
    }
}

async fn version(State(state): State<SharedState>) -> Json<serde_json::Value> {
    Json(version_json(&state).await)
}

// Force an immediate GitHub release check (instead of waiting for the periodic
// background task) and return the refreshed version info.
async fn version_check(State(state): State<SharedState>) -> Json<serde_json::Value> {
    let channel = effective_channel(&state).await;
    match tokio::task::spawn_blocking(move || update_check::check_once(channel)).await {
        Ok(Ok(info)) => {
            let mut slot = state.update_info.lock().await;
            *slot = Some(info);
        }
        Ok(Err(e)) => tracing::warn!("manual update check failed: {}", e),
        Err(e) => tracing::error!("manual update check task failed: {}", e),
    }
    Json(version_json(&state).await)
}

async fn version_json(state: &SharedState) -> serde_json::Value {
    let update = state.update_info.lock().await;
    let latest = update.as_ref().map(|info| info.latest.clone());
    let update_available = update.as_ref().map(|info| info.update_available);
    let auto_update = state.settings.read().await.auto_update;
    serde_json::json!({
        "version": env!("CARGO_PKG_VERSION"),
        "api_compat": "0.2",
        "latest_version": latest,
        "update_available": update_available,
        "dev_mode": state.dev_mode,
        "channel": effective_channel(state).await.as_str(),
        "auto_update": auto_update,
    })
}

/// The channel vestad is currently following, honoring the `VESTA_CHANNEL` env
/// override over the persisted setting.
async fn effective_channel(state: &SharedState) -> crate::channel::Channel {
    crate::channel::Channel::resolve(&state.settings.read().await.channel)
}

#[derive(Deserialize)]
struct GatewayLogsQuery {
    tail: Option<u64>,
    #[serde(default)]
    follow: bool,
}

async fn gateway_logs_handler(
    Query(query): Query<GatewayLogsQuery>,
) -> Result<Sse<impl futures_core::Stream<Item = Result<Event, std::io::Error>>>, (StatusCode, Json<serde_json::Value>)> {
    let tail = query.tail.unwrap_or(DEFAULT_LOG_TAIL_LINES) as usize;

    let log_dir = crate::paths::config_dir_or_relative();
    let log_file = crate::self_log::latest_log_file(&log_dir)
        .ok_or_else(|| err_response(StatusCode::NOT_FOUND, "no gateway logs available yet"))?;

    let mut child = crate::self_log::spawn_log_tail(&log_file, tail, query.follow)
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e))?;

    let stdout = child.stdout.take().ok_or_else(|| {
        err_response(StatusCode::INTERNAL_SERVER_ERROR, "log tail stdout not captured")
    })?;

    let stream = async_stream::stream! {
        use tokio::io::AsyncBufReadExt;
        let reader = tokio::io::BufReader::new(stdout);
        let mut lines = reader.lines();
        loop {
            match lines.next_line().await {
                Ok(Some(line)) => yield Ok(Event::default().data(line)),
                Ok(None) => break,
                Err(e) => {
                    yield Ok(Event::default().data(format!("error: {}", e)));
                    break;
                }
            }
        }
        let _ = child.wait().await;
        yield Ok(Event::default().event("gateway_stopped").data(""));
    };

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}

async fn restart_gateway_handler() -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !systemd::is_active() {
        return Err(err_response(
            StatusCode::PRECONDITION_FAILED,
            "vestad is not running under systemd — cannot self-restart",
        ));
    }
    tracing::info!("gateway restart requested via API");
    // Delay so the HTTP response can flush before systemctl kills this process.
    tokio::spawn(async {
        tokio::time::sleep(tokio::time::Duration::from_millis(GATEWAY_RESTART_DELAY_MS)).await;
        match tokio::task::spawn_blocking(systemd::restart).await {
            Ok(Ok(())) => {}
            Ok(Err(e)) => tracing::error!(error = %e, "gateway restart failed"),
            Err(e) => tracing::error!(error = %e, "gateway restart task panicked"),
        }
    });
    Ok(Json(serde_json::json!({"ok": true, "restarting": true})))
}

async fn gateway_update_handler(
    State(state): State<SharedState>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if state.dev_mode {
        return Err(err_response(StatusCode::BAD_REQUEST, "self-update disabled in dev mode"));
    }
    if state.updating.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return Err(err_response(StatusCode::CONFLICT, "update already in progress"));
    }
    let channel = effective_channel(&state).await;
    tracing::info!(channel = channel.as_str(), "gateway update requested via API");
    let result = tokio::task::spawn_blocking(move || self_update::perform_update(channel))
        .await
        .unwrap();
    state.updating.store(false, std::sync::atomic::Ordering::SeqCst);
    match result {
        Ok(outcome) => Ok(Json(serde_json::json!({
            "ok": true,
            "updated": outcome.updated,
            "restarting": outcome.restarted,
            "current": outcome.current,
            "latest": outcome.latest,
        }))),
        Err(e) => Err(err_response(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string())),
    }
}

async fn list_agents_handler(
    State(state): State<SharedState>,
) -> impl IntoResponse {
    let agents = docker::list_agents(&state.docker, &state.http_client, &state.env_config.agents_dir).await;
    Json(agents)
}

#[derive(Deserialize)]
struct CreateBody {
    name: Option<String>,
    manage_agent_code: Option<bool>,
}

async fn create_agent_handler(
    State(state): State<SharedState>,
    Json(body): Json<CreateBody>,
) -> Result<impl IntoResponse, (StatusCode, Json<serde_json::Value>)> {
    let raw_name = body.name.clone().unwrap_or_else(|| "default".to_string());
    let name = docker::normalize_name(&raw_name);
    if name.is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "invalid agent name"));
    }
    let manage_core_code = body.manage_agent_code.unwrap_or(true);
    tracing::info!(name = %name, manage_core_code, "creating agent");

    let _guard = agent_write_guard(&state, &name).await;

    if !manage_core_code {
        let mut settings = state.settings.write().await;
        settings.agents.entry(name.clone()).or_default().manage_agent_code = false;
        save_settings(&settings);
    }

    // Create + start an empty agent. Credentials and preferences arrive via a separate
    // PUT /agents/{name}/config once the agent is up — the agent owns its own credential
    // files now, vestad only orchestrates. `create_agent` reports coarse phases into shared
    // state so GET /agents/{name}/build-phase can drive honest onboarding status while this
    // synchronous call is in flight.
    let phases = state.clone();
    let progress_name = name.clone();
    let progress = docker::BuildProgress::new(Arc::new(move |phase| {
        phases.set_build_phase(&progress_name, phase);
    }));

    let result = create_and_start(&state, &name, manage_core_code, &progress).await;
    state.clear_build_phase(&name);
    let name = result?;

    Ok((StatusCode::CREATED, Json(serde_json::json!({"name": name}))))
}

/// Run the create then the start, reporting `Starting` between them. Split out so
/// the caller can clear the build-phase entry on either outcome before returning.
async fn create_and_start(
    state: &SharedState,
    name: &str,
    manage_core_code: bool,
    progress: &docker::BuildProgress,
) -> Result<String, (StatusCode, Json<serde_json::Value>)> {
    let name = docker::create_agent(&state.docker, name, &state.env_config, manage_core_code, progress)
        .await
        .map_err(map_docker_err)?;

    progress.set(docker::BuildPhase::Starting);
    docker::start_agent(&state.docker, &name)
        .await
        .map_err(map_docker_err)?;

    Ok(name)
}

async fn build_phase_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Json<serde_json::Value> {
    let phase = state.build_phase(&docker::normalize_name(&name));
    Json(serde_json::json!({ "phase": phase }))
}

async fn agent_status_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<docker::StatusJson>, (StatusCode, Json<serde_json::Value>)> {
    let status = docker::get_status(&state.docker, &state.http_client, &name, &state.env_config.agents_dir)
        .await
        .map_err(map_docker_err)?;
    Ok(Json(status))
}

async fn start_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "starting agent");
    let _guard = agent_write_guard(&state, &name).await;

    {
        let mut settings = state.settings.write().await;
        settings.agents.entry(name.clone()).or_default().user_desired = UserDesired::Running;
        save_settings(&settings);
    }
    docker::start_agent(&state.docker, &name)
        .await
        .map_err(map_docker_err)?;
    Ok(ok_json())
}

async fn start_all_handler(
    State(state): State<SharedState>,
) -> impl IntoResponse {
    let results = docker::start_all_agents(&state.docker).await;

    // Starting all agents is an explicit "everything should run" — record it so boot-start agrees
    // (otherwise an agent the user had stopped comes up now but goes back down on the next reboot).
    {
        let mut settings = state.settings.write().await;
        for result in &results {
            settings.agents.entry(result.name.clone()).or_default().user_desired = UserDesired::Running;
        }
        save_settings(&settings);
    }

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
    let _guard = agent_write_guard(&state, &name).await;

    {
        let mut settings = state.settings.write().await;
        settings.agents.entry(name.clone()).or_default().user_desired = UserDesired::Stopped;
        settings.services.remove(&name);
        save_settings(&settings);
    }
    docker::stop_agent(&state.docker, &name)
        .await
        .map_err(map_docker_err)?;
    Ok(ok_json())
}

#[derive(Deserialize, Default)]
struct RestartBody {
    /// Optional human reason the agent surfaces on its next boot ("manual: switching to ...").
    #[serde(default)]
    reason: Option<String>,
}

/// Lenient body parse for POST /restart: the endpoint predates the body, so bodyless requests
/// (the CLI, the agent's self-restart, curl with a stray JSON Content-Type) must keep working.
/// An Option<Json<...>> extractor would 400 an empty body sent with a JSON header and 415 any
/// other Content-Type; raw bytes sidestep the header entirely.
fn parse_restart_reason(body: &[u8]) -> Result<Option<String>, String> {
    if body.is_empty() {
        return Ok(None);
    }
    serde_json::from_slice::<RestartBody>(body)
        .map(|restart_body| restart_body.reason)
        .map_err(|e| format!("invalid restart body: {e}"))
}

async fn restart_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    body: axum::body::Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "restarting agent");
    let reason = parse_restart_reason(&body).map_err(|msg| err_response(StatusCode::BAD_REQUEST, &msg))?;
    // Detached from this request's connection: a self-restart's client is the agent inside the very
    // container this stops, so the loopback drops the instant rebuild_agent stops it. An inline await
    // would be cancelled before the recreate finishes, leaving the agent down (see spawn_detached).
    spawn_detached(async move {
        let _guard = agent_write_guard(&state, &name).await;

        // A restart implies the agent should be running — record it so boot-start agrees with intent.
        {
            let mut settings = state.settings.write().await;
            settings.agents.entry(name.clone()).or_default().user_desired = UserDesired::Running;
            save_settings(&settings);
        }
        let user_mounts = {
            let settings = state.settings.read().await;
            settings.agent_mounts(&name)
        };
        docker::restart_agent(&state.docker, &name, &state.env_config, &user_mounts, reason)
            .await
            .map_err(map_docker_err)?;
        Ok(ok_json())
    })
    .await
}

async fn destroy_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "destroying agent");
    let _guard = agent_write_guard(&state, &name).await;

    docker::destroy_agent(&state.docker, &name, &state.env_config.agents_dir)
        .await
        .map_err(map_docker_err)?;
    {
        let mut settings = state.settings.write().await;
        settings.services.remove(&name);
        settings.agents.remove(&name);
        save_settings(&settings);
    }

    Ok(ok_json())
}

async fn rebuild_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "rebuilding agent");
    let _guard = agent_write_guard(&state, &name).await;

    let user_mounts = {
        let settings = state.settings.read().await;
        settings.agent_mounts(&name)
    };
    docker::rebuild_agent(&state.docker, &name, &state.env_config, &user_mounts)
        .await
        .map_err(map_docker_err)?;
    // A rebuild ends by starting the agent, so record it as desired-running for boot-start.
    {
        let mut settings = state.settings.write().await;
        settings.agents.entry(name.clone()).or_default().user_desired = UserDesired::Running;
        save_settings(&settings);
    }
    docker::start_agent(&state.docker, &name)
        .await
        .map_err(map_docker_err)?;
    Ok(ok_json())
}

#[derive(Deserialize)]
struct RenameBody {
    new_name: String,
}

async fn rename_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<RenameBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let new_name = docker::normalize_name(&body.new_name);
    if new_name.is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "invalid new agent name"));
    }
    if new_name == name {
        return Err(err_response(StatusCode::BAD_REQUEST, "new name must differ from old name"));
    }
    tracing::info!(old = %name, new = %new_name, "renaming agent");

    // Lock both names in lex order to avoid deadlock between concurrent renames.
    let (first, second) = if name < new_name { (&name, &new_name) } else { (&new_name, &name) };
    let lock_first = state.agent_lock(first).await;
    let lock_second = state.agent_lock(second).await;
    let _g1 = lock_first.write().await;
    let _g2 = lock_second.write().await;

    let user_mounts = {
        let settings = state.settings.read().await;
        settings.agent_mounts(&name)
    };
    docker::rename_agent(&state.docker, &name, &new_name, &state.env_config, &user_mounts)
        .await
        .map_err(map_docker_err)?;

    {
        let mut settings = state.settings.write().await;
        if let Some(v) = settings.agents.remove(&name) {
            settings.agents.insert(new_name.clone(), v);
        }
        if let Some(v) = settings.services.remove(&name) {
            settings.services.insert(new_name.clone(), v);
        }
        if let Some(v) = settings.backup.agents.remove(&name) {
            settings.backup.agents.insert(new_name.clone(), v);
        }
        save_settings(&settings);
    }

    if let Err(e) = drop_rename_notification(&state.docker, &new_name, &name).await {
        tracing::warn!(old = %name, new = %new_name, error = %e, "failed to drop rename notification");
    }

    docker::start_agent(&state.docker, &new_name)
        .await
        .map_err(map_docker_err)?;

    Ok(Json(serde_json::json!({"name": new_name})))
}

/// Build the rename notification payload. Pure (no IO) so its shape can be
/// asserted without spinning up a container.
fn rename_notification_payload(old_name: &str, new_name: &str, epoch_secs: u64) -> Result<serde_json::Value, String> {
    let timestamp = time::OffsetDateTime::from_unix_timestamp(epoch_secs as i64)
        .map_err(|e| format!("epoch out of range: {e}"))?
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|e| format!("format timestamp: {e}"))?;
    Ok(serde_json::json!({
        "timestamp": timestamp,
        "source": "vestad",
        "type": "rename",
        "interrupt": true,
        "old_name": old_name,
        "new_name": new_name,
        "message": format!(
            "you have been renamed from '{old_name}' to '{new_name}'. \
             AGENT_NAME is now '{new_name}'. update your MEMORY.md and anything else \
             that references your old name."
        ),
    }))
}

/// Drop a high-priority notification into the renamed agent so it self-updates
/// MEMORY.md and any prompts that reference the old name. Best-effort: failure
/// to write the notification doesn't block the rename. Returns the notification
/// file name written into the container.
pub(crate) async fn drop_rename_notification(
    docker: &bollard::Docker,
    new_name: &str,
    old_name: &str,
) -> Result<String, String> {
    let cname = docker::container_name(new_name);
    let epoch = crate::time_utils::now_epoch_secs();
    let payload = rename_notification_payload(old_name, new_name, epoch)?;
    let bytes = serde_json::to_vec(&payload).map_err(|e| format!("serialize notification: {e}"))?;
    let file_name = format!("rename-{epoch}.json");
    docker::upload_to_container(docker, &cname, "/root/agent/notifications", &file_name, &bytes)
        .await
        .map_err(|e| e.to_string())?;
    Ok(file_name)
}

/// Which write to forward to the agent's own HTTP API. Dispatched inside `write_to_agent` so the
/// borrowing `AgentProvider` never crosses a closure boundary.
enum AgentWrite {
    /// The agent's `PUT /config` — a sparse preferences diff.
    Config(serde_json::Value),
    /// The agent's `PUT /provider` — sign in / switch provider.
    Provider(serde_json::Value),
    /// The agent's `PATCH /provider` — change model / context / thinking.
    PatchProvider(serde_json::Value),
    /// The agent's `DELETE /provider` — clear credentials (sign out).
    ClearProvider,
}

/// Forward a write to the agent's own HTTP API. Writes only set desired state — they do NOT restart;
/// the caller applies them with one `POST /agents/{name}/restart` after its writes (so provisioning
/// is several writes + a single restart, with nothing racing a restarting agent). Ensures the agent
/// exists, takes the per-agent write lock, and auto-starts a stopped agent so it can receive the
/// proxied call. The agent owns the file writes, format, and validation; a forward failure is BAD_GATEWAY.
async fn write_to_agent(
    state: &SharedState,
    name: &str,
    write: AgentWrite,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(name).map_err(map_docker_err)?;
    let cname = docker::container_name(name);
    docker::ensure_exists(&state.docker, &cname).await.map_err(map_docker_err)?;

    let _guard = agent_write_guard(state, name).await;

    // Agent must be running to receive the proxy call; auto-start stopped agents.
    if docker::container_status(&state.docker, &cname).await != docker::ContainerStatus::Running {
        docker::start_agent(&state.docker, name).await.map_err(map_docker_err)?;
    }

    let provider = agent_provider::AgentProvider::new(&state.http_client, &state.env_config.agents_dir, name);
    let forwarded = match write {
        AgentWrite::Config(body) => provider.put_config(&body).await,
        AgentWrite::Provider(body) => provider.put_provider(&body).await,
        AgentWrite::PatchProvider(body) => provider.patch_provider(&body).await,
        AgentWrite::ClearProvider => provider.delete_provider().await,
    };
    forwarded.map_err(|e| err_response(StatusCode::BAD_GATEWAY, &e))?;
    Ok(Json(serde_json::json!({"ok": true, "restart_required": true})))
}

/// Relay the agent's `GET /config` (prefs; the agent owns it, vestad proxies it to the app).
async fn get_config_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let provider = agent_provider::AgentProvider::new(&state.http_client, &state.env_config.agents_dir, &name);
    provider
        .get_config()
        .await
        .map(Json)
        .map_err(|e| err_response(StatusCode::BAD_GATEWAY, &e))
}

/// Forward a preferences diff to the agent's `PUT /config`. Write only — caller restarts to apply.
async fn set_config_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    write_to_agent(&state, &name, AgentWrite::Config(body)).await
}

/// Relay the agent's `GET /provider` (active provider + derived auth state; vestad proxies it).
async fn get_provider_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let provider = agent_provider::AgentProvider::new(&state.http_client, &state.env_config.agents_dir, &name);
    provider
        .get_provider()
        .await
        .map(Json)
        .map_err(|e| err_response(StatusCode::BAD_GATEWAY, &e))
}

/// Sign in / switch: forward the provider body to the agent's `PUT /provider`. Write only — caller restarts.
async fn set_provider_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    write_to_agent(&state, &name, AgentWrite::Provider(body)).await
}

/// Change model / context / thinking: forward to the agent's `PATCH /provider`. Write only — caller restarts.
async fn patch_provider_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    write_to_agent(&state, &name, AgentWrite::PatchProvider(body)).await
}

/// Sign out: forward to the agent's `DELETE /provider`. Write only — caller restarts to apply.
async fn clear_provider_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    write_to_agent(&state, &name, AgentWrite::ClearProvider).await
}

// --- SSE Logs ---

#[derive(Deserialize)]
struct LogsQuery {
    tail: Option<u64>,
}

async fn logs_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Query(query): Query<LogsQuery>,
) -> Result<Sse<impl futures_core::Stream<Item = Result<Event, std::io::Error>>>, (StatusCode, Json<serde_json::Value>)>
{
    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);
    let status = docker::container_status(&state.docker, &cname).await;
    if status == docker::ContainerStatus::NotFound {
        return Err(err_response(StatusCode::BAD_REQUEST, &format!("agent '{}' not found", name)));
    }

    let tail_lines = query.tail.unwrap_or(DEFAULT_LOG_TAIL_LINES) as usize;
    let docker = state.docker.clone();
    let stream = async_stream::stream! {
        if status != docker::ContainerStatus::Running {
            match docker::download_from_container(&docker, &cname, docker::VESTA_LOG_PATH).await {
                Some(content) => {
                    let lines: Vec<&str> = content.lines().collect();
                    let start = lines.len().saturating_sub(tail_lines);
                    for line in &lines[start..] {
                        yield Ok(Event::default().data(*line));
                    }
                }
                None => {
                    yield Ok(Event::default().data("(no logs available)"));
                }
            }
            yield Ok(Event::default().event("agent_stopped").data(""));
            return;
        }

        let tail_arg = tail_lines.to_string();
        let exec = match docker.create_exec(&cname, bollard::exec::CreateExecOptions {
            cmd: Some(vec!["tail".to_string(), "-n".to_string(), tail_arg, "-f".to_string(), docker::VESTA_LOG_PATH.to_string()]),
            attach_stdout: Some(true),
            attach_stderr: Some(false),
            ..Default::default()
        }).await {
            Ok(e) => e,
            Err(e) => {
                yield Ok(Event::default().data(format!("error: {}", e)));
                return;
            }
        };

        let mut output = match docker.start_exec(&exec.id, None).await {
            Ok(bollard::exec::StartExecResults::Attached { output, .. }) => output,
            Ok(_) => {
                yield Ok(Event::default().data("error: exec started in detached mode"));
                return;
            }
            Err(e) => {
                yield Ok(Event::default().data(format!("error: {}", e)));
                return;
            }
        };

        use futures_util::StreamExt;
        let mut partial_line = String::new();
        while let Some(chunk) = output.next().await {
            match chunk {
                Ok(log_output) => {
                    let text = log_output.to_string();
                    partial_line.push_str(&text);
                    while let Some(newline_pos) = partial_line.find('\n') {
                        let line = partial_line[..newline_pos].trim_end().to_string();
                        partial_line = partial_line[newline_pos + 1..].to_string();
                        yield Ok(Event::default().data(line));
                    }
                }
                Err(e) => {
                    yield Ok(Event::default().data(format!("error: {}", e)));
                    break;
                }
            }
        }
        if !partial_line.trim().is_empty() {
            yield Ok(Event::default().data(partial_line.trim_end()));
        }
        yield Ok(Event::default().event("agent_stopped").data(""));
    };

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}


// --- File tree ---

#[derive(Serialize)]
struct TreeEntry {
    path: String,
    is_dir: bool,
    mode: u32,
}

async fn tree_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);
    docker::ensure_running(&state.docker, &cname).await
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e.to_string()))?;

    let find = vec![
        "find".into(), "/root".into(),
        "-not".into(), "-path".into(), "*/.venv/*".into(),
        "-not".into(), "-path".into(), "*/__pycache__/*".into(),
        "-not".into(), "-path".into(), "*/.cache/*".into(),
        "-not".into(), "-path".into(), "*/node_modules/*".into(),
        "-printf".into(), "%y\t%m\t%p\n".into(),
    ];
    let result = docker_exec_capture(&state.docker, &cname, find, None)
        .await
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e))?;
    let buffer = String::from_utf8_lossy(&result.stdout);

    let mut entries: Vec<TreeEntry> = Vec::new();
    for line in buffer.lines() {
        let line = line.trim_end();
        if line.is_empty() { continue; }
        let parts: Vec<&str> = line.splitn(3, '\t').collect();
        if parts.len() != 3 { continue; }
        let is_dir = parts[0] == "d";
        let mode = u32::from_str_radix(parts[1], 8).unwrap_or(0o644);
        entries.push(TreeEntry { path: parts[2].to_string(), is_dir, mode });
    }
    entries.sort_by(|a, b| a.path.cmp(&b.path));

    let paths: Vec<String> = entries.iter().map(|e| e.path.clone()).collect();
    Ok(Json(serde_json::json!({ "tree": paths, "entries": entries })))
}

// --- File read / write ---

const FILE_SIZE_LIMIT: u64 = 2 * 1024 * 1024; // 2 MiB

const SENSITIVE_PATHS: &[&str] = &[
    "/root/agent/data/events.db",
    "/root/agent/data/session_id",
    "/root/.claude/.credentials.json",
    "/run/vestad-env",
];

fn validate_file_path(p: &str) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    if !p.starts_with("/root/")
        || p.contains("/../")
        || p.contains('\0')
        || p.ends_with("/..")
        || p == "/root"
    {
        return Err(err_response(StatusCode::BAD_REQUEST, "invalid path"));
    }
    Ok(())
}

fn is_readonly_path(p: &str) -> bool {
    for &prefix in docker::MOUNT_DESTS {
        if p == prefix || p.starts_with(&format!("{prefix}/")) {
            return true;
        }
    }
    SENSITIVE_PATHS.contains(&p)
}

fn shell_escape(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

struct ExecResult {
    stdout: Vec<u8>,
    stderr: String,
    exit_code: i64,
}

async fn docker_exec_capture(
    docker: &bollard::Docker,
    cname: &str,
    cmd: Vec<String>,
    stdin: Option<Vec<u8>>,
) -> Result<ExecResult, String> {
    let attach_stdin = stdin.is_some();
    let exec = docker.create_exec(cname, bollard::exec::CreateExecOptions {
        cmd: Some(cmd),
        attach_stdout: Some(true),
        attach_stderr: Some(true),
        attach_stdin: Some(attach_stdin),
        ..Default::default()
    }).await.map_err(|e| e.to_string())?;

    let result = docker.start_exec(&exec.id, None).await.map_err(|e| e.to_string())?;

    let mut stdout: Vec<u8> = Vec::new();
    let mut stderr = String::new();

    if let bollard::exec::StartExecResults::Attached { mut output, mut input } = result {
        if let Some(data) = stdin {
            use tokio::io::AsyncWriteExt;
            input.write_all(&data).await.map_err(|e| e.to_string())?;
            input.shutdown().await.map_err(|e| e.to_string())?;
        }
        drop(input);

        use futures_util::StreamExt;
        while let Some(chunk) = output.next().await {
            match chunk.map_err(|e| e.to_string())? {
                bollard::container::LogOutput::StdOut { message } => stdout.extend_from_slice(&message),
                bollard::container::LogOutput::StdErr { message } => stderr.push_str(&String::from_utf8_lossy(&message)),
                _ => {}
            }
        }
    }

    let inspect = docker.inspect_exec(&exec.id).await.map_err(|e| e.to_string())?;
    let exit_code = inspect.exit_code.unwrap_or(-1);
    Ok(ExecResult { stdout, stderr, exit_code })
}

#[derive(Deserialize)]
struct ReadFileQuery { path: String }

async fn read_file_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Query(q): Query<ReadFileQuery>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    validate_file_path(&q.path)?;

    if SENSITIVE_PATHS.contains(&q.path.as_str()) {
        return Err(err_response(StatusCode::FORBIDDEN, "file is not readable"));
    }

    let cname = docker::container_name(&name);
    docker::ensure_running(&state.docker, &cname).await
        .map_err(|e| err_response(StatusCode::SERVICE_UNAVAILABLE, &e.to_string()))?;

    // The constitution is bind-mounted read-only inside the container (the agent reads but
    // cannot edit it), so the file API serves it from the host file and reports it editable —
    // user writes route to the host (see write_file_handler), keeping the agent unable to edit.
    if q.path == docker::CONSTITUTION_MOUNT_DEST {
        let content = docker::read_constitution(&state.env_config.agents_dir, &name)
            .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string()))?;
        let size = content.len() as u64;
        return Ok(Json(serde_json::json!({
            "path": q.path,
            "content": content,
            "encoding": "utf-8",
            "readonly": false,
            "mode": 0o644,
            "size": size,
            "is_dir": false,
        })));
    }

    // Refuse symlinks anywhere in the path. Without this, an agent-controlled
    // symlink under /root/agent (e.g. /root/agent/data/leak -> /etc/shadow)
    // would slip past validate_file_path's string checks and expose the target.
    let stat_cmd = format!(
        "real=$(realpath -e -- {p} 2>/dev/null) && [ \"$real\" = {p} ] && stat -c '%a %s %F' {p}",
        p = shell_escape(&q.path)
    );
    let stat = docker_exec_capture(
        &state.docker, &cname,
        vec!["sh".into(), "-c".into(), stat_cmd], None,
    ).await.map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e))?;

    if stat.exit_code != 0 {
        let detail = stat.stderr.trim();
        if detail.is_empty() {
            return Err(err_response(StatusCode::NOT_FOUND, "file not found or resolves through a symlink"));
        }
        return Err(err_response(StatusCode::NOT_FOUND, &format!("stat failed: {detail}")));
    }

    let stat_line = String::from_utf8_lossy(&stat.stdout);
    let stat_line = stat_line.trim();
    let mut iter = stat_line.splitn(3, ' ');
    let mode_str = iter.next().unwrap_or("0");
    let size_str = iter.next().unwrap_or("0");
    let kind = iter.next().unwrap_or("");
    let mode = u32::from_str_radix(mode_str, 8).unwrap_or(0);
    let size: u64 = size_str.parse().unwrap_or(0);
    let is_dir = kind.contains("directory");

    if is_dir {
        return Err(err_response(StatusCode::BAD_REQUEST, "path is a directory"));
    }
    if size > FILE_SIZE_LIMIT {
        return Err((StatusCode::PAYLOAD_TOO_LARGE, Json(serde_json::json!({
            "error": "file too large",
            "size": size,
            "limit": FILE_SIZE_LIMIT,
        }))));
    }

    let cat_cmd = format!("cat {}", shell_escape(&q.path));
    let cat = docker_exec_capture(
        &state.docker, &cname,
        vec!["sh".into(), "-c".into(), cat_cmd], None,
    ).await.map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e))?;

    if cat.exit_code != 0 {
        return Err(err_response(StatusCode::INTERNAL_SERVER_ERROR, &format!("read failed: {}", cat.stderr.trim())));
    }

    let readonly = is_readonly_path(&q.path) || (mode & 0o200) == 0;
    let (content, encoding) = match std::str::from_utf8(&cat.stdout) {
        Ok(s) => (s.to_string(), "utf-8"),
        Err(_) => {
            use base64::Engine;
            (base64::engine::general_purpose::STANDARD.encode(&cat.stdout), "base64")
        }
    };

    Ok(Json(serde_json::json!({
        "path": q.path,
        "content": content,
        "encoding": encoding,
        "readonly": readonly,
        "mode": mode,
        "size": size,
        "is_dir": false,
    })))
}

#[derive(Deserialize)]
struct WriteFileBody { path: String, content: String }

async fn write_file_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<WriteFileBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    validate_file_path(&body.path)?;

    let cname = docker::container_name(&name);
    docker::ensure_running(&state.docker, &cname).await
        .map_err(|e| err_response(StatusCode::SERVICE_UNAVAILABLE, &e.to_string()))?;

    // The constitution is bind-mounted read-only (the agent cannot edit it), so a user edit
    // from the file API writes the host file in place — the same single writer the dedicated
    // constitution endpoint uses. This keeps the agent unable to edit while the user can.
    if body.path == docker::CONSTITUTION_MOUNT_DEST {
        let _guard = agent_write_guard(&state, &name).await;
        docker::write_constitution(&state.env_config.agents_dir, &name, &body.content)
            .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string()))?;
        return Ok(ok_json());
    }

    if is_readonly_path(&body.path) {
        return Err(err_response(StatusCode::FORBIDDEN, "file is read-only"));
    }

    // Same anti-symlink guard as read_file_handler: realpath must equal the
    // requested path. New-file writes (path does not yet exist) are rejected
    // here, which is fine — the FilesTab only writes through previously-read
    // files.
    let write_cmd = format!(
        "real=$(realpath -e -- {p} 2>/dev/null) && [ \"$real\" = {p} ] && \
         tmp=$(mktemp /tmp/.vesta-edit.XXXXXX) && cat > \"$tmp\" && mv -f \"$tmp\" {p}",
        p = shell_escape(&body.path)
    );

    let result = docker_exec_capture(
        &state.docker, &cname,
        vec!["sh".into(), "-c".into(), write_cmd],
        Some(body.content.into_bytes()),
    ).await.map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e))?;

    if result.exit_code != 0 {
        let err = result.stderr.trim();
        if err.contains("Read-only file system") {
            return Err(err_response(StatusCode::FORBIDDEN, "file is on a read-only filesystem"));
        }
        return Err(err_response(StatusCode::INTERNAL_SERVER_ERROR, &format!("write failed: {err}")));
    }

    Ok(ok_json())
}

#[cfg(test)]
mod file_path_tests {
    use super::*;

    #[test]
    fn validate_file_path_accepts_inside_root_rejects_escape() {
        let cases = [
            ("/root/agent/data/foo", true),
            ("/root/agent/prompts/x.md", true),
            ("/etc/passwd", false),
            ("/run/vestad-env", false),
            ("/root", false),
            ("/root/../etc/passwd", false),
            ("/root/agent/..", false),
            ("/root/agent/../../etc", false),
            ("/root/foo\0bar", false),
        ];
        for (path, ok) in cases {
            assert_eq!(validate_file_path(path).is_ok(), ok, "path: {path:?}");
        }
    }

    #[test]
    fn is_readonly_path_protects_bind_mounts_and_sensitive_files() {
        let cases = [
            ("/root/agent/core/main.py", true),
            ("/root/agent/core", true),
            // Engine metadata moved into core/ — the old root-level paths are no longer mounts.
            ("/root/agent/core/pyproject.toml", true),
            ("/root/agent/pyproject.toml", false),
            ("/root/agent/uv.lock", false),
            ("/run/vestad-env", true),
            ("/root/agent/data/events.db", true),
            ("/root/agent/data/session_id", true),
            ("/root/.claude/.credentials.json", true),
            ("/root/agent/data/foo.json", false),
            ("/root/agent/prompts/x.md", false),
            ("/root/.claude/settings.json", false),
        ];
        for (path, readonly) in cases {
            assert_eq!(is_readonly_path(path), readonly, "path: {path:?}");
        }
    }
}

const SERVICE_PORT_MIN: u16 = 49152;
const SERVICE_PORT_MAX: u16 = 65535;

#[derive(Deserialize)]
struct RegisterServiceBody {
    name: String,
    #[serde(default)]
    public: bool,
}

/// Collect all ports in use across all agents in the service registry.
fn all_registered_ports(registry: &HashMap<String, HashMap<String, ServiceEntry>>) -> Vec<u16> {
    registry.values().flat_map(|services| services.values().map(|e| e.port)).collect()
}

/// Upper bound of the kernel's ephemeral source-port range
/// (`net.ipv4.ip_local_port_range`). Service ports are allocated above this so
/// the kernel never reuses a just-allocated service port as a transient
/// outbound source port (which would make a later bind() of that port fail).
fn ephemeral_port_high() -> u16 {
    std::fs::read_to_string("/proc/sys/net/ipv4/ip_local_port_range")
        .ok()
        .and_then(|s| s.split_whitespace().nth(1).and_then(|h| h.parse::<u16>().ok()))
        .unwrap_or(60999)
}

fn no_free_ports_err() -> (StatusCode, Json<serde_json::Value>) {
    err_response(
        StatusCode::SERVICE_UNAVAILABLE,
        "no free ports available in range 49152-65535 — too many services registered, or all ports are in use",
    )
}

/// Find a free port not used by any registered service or other process.
///
/// Callers bind the returned port themselves, only later. The previous
/// implementation asked the OS for a port via `bind(0)`, which hands back an
/// *ephemeral* port; between allocation and the caller binding it, the kernel
/// could reuse that same port as the source port of an outbound connection,
/// producing a spurious `EADDRINUSE` (the port looks free to a LISTEN scan but
/// bind() fails). To avoid that race we scan deterministically and prefer ports
/// *above* the ephemeral range, which the kernel will not hand out as source
/// ports.
fn allocate_service_port(registry: &HashMap<String, HashMap<String, ServiceEntry>>) -> Option<u16> {
    let used = all_registered_ports(registry);
    let scan = |lo: u16| {
        (lo..=SERVICE_PORT_MAX)
            .find(|p| !used.contains(p) && std::net::TcpListener::bind(("127.0.0.1", *p)).is_ok())
    };
    // Preferred: above the ephemeral range, where the port can't be reused as a
    // transient outbound source port between allocation and the caller binding it.
    let safe_min = ephemeral_port_high().saturating_add(1).max(SERVICE_PORT_MIN);
    // Fallback: the full service range (may still race, but better than failing
    // to allocate when the safe band is exhausted).
    scan(safe_min).or_else(|| scan(SERVICE_PORT_MIN))
}

/// Bindable = reusable. A port that merely has a listener isn't enough:
/// callers always bind the returned port themselves, so a squatter would
/// trap them in a crash loop. See #371 and #433.
async fn is_cached_port_reusable(port: u16) -> bool {
    tokio::net::TcpListener::bind(("127.0.0.1", port)).await.is_ok()
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
        return Err(err_response(StatusCode::BAD_REQUEST, &format!(
            "'{}' is a reserved name (conflicts with vestad routes: {}) — pick a different service name",
            service_name, RESERVED_SERVICE_NAMES.join(", ")
        )));
    }

    let docker_name = docker::container_name(&name);
    let exists = docker::container_status(&state.docker, &docker_name).await != docker::ContainerStatus::NotFound;
    if !exists {
        return Err(err_response(StatusCode::NOT_FOUND, &format!("agent '{}' not found — is the container running? check with: docker ps | grep vesta", name)));
    }

    let mut settings = state.settings.write().await;

    let cached_port = settings.services.get(&name).and_then(|s| s.get(&service_name)).map(|e| e.port);
    let port = match cached_port {
        Some(p) if is_cached_port_reusable(p).await => p,
        Some(p) => {
            tracing::warn!(agent = %name, service = %service_name, stale_port = p, "cached service port is not bindable, allocating a fresh one");
            allocate_service_port(&settings.services).ok_or_else(no_free_ports_err)?
        }
        None => allocate_service_port(&settings.services).ok_or_else(no_free_ports_err)?,
    };

    let entry = ServiceEntry { port, public: body.public };
    settings.services.entry(name.clone()).or_default().insert(service_name.clone(), entry);
    save_settings(&settings);
    state.agent_status_cache.update_services(&settings.services);
    tracing::info!(agent = %name, service = %service_name, port, public = body.public, "service registered");
    Ok(Json(serde_json::json!({"ok": true, "port": port, "public": body.public})))
}

async fn unregister_service_handler(
    State(state): State<SharedState>,
    Path((name, service_name)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let mut settings = state.settings.write().await;
    if let Some(agent_services) = settings.services.get_mut(&name) {
        agent_services.remove(&service_name);
        if agent_services.is_empty() {
            settings.services.remove(&name);
        }
    }
    save_settings(&settings);
    state.agent_status_cache.update_services(&settings.services);
    tracing::info!(agent = %name, service = %service_name, "service unregistered");
    Ok(ok_json())
}

async fn list_services_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Json<serde_json::Value> {
    let settings = state.settings.read().await;
    let services = settings.services.get(&name).cloned().unwrap_or_default();
    Json(serde_json::json!({"services": services}))
}

// --- Backup/Restore ---

/// Build the SSE `error` event a backup/restore stream emits when its pipeline fails,
/// carrying the same `{status, error}` shape clients parse from both endpoints.
fn sse_error_event(e: docker::DockerError) -> Event {
    let (status, body) = map_docker_err(e);
    let err = serde_json::json!({"status": status.as_u16(), "error": body.0});
    Event::default().event("error").data(err.to_string())
}

/// Run a destructive backup/restore pipeline on a spawned task and surface its single
/// terminal result as the `done`/`error` SSE both endpoints share. Spawning (rather than
/// awaiting inline in the stream body) is the load-bearing invariant: if the SSE client
/// disconnects mid-pipeline, hyper drops the stream future, but the spawned task keeps
/// running to completion so a half-applied destructive step can't strand the agent. On
/// success the pipeline returns the `done` event's data payload.
fn spawn_pipeline_sse<Fut>(pipeline: Fut) -> Sse<impl futures_core::Stream<Item = Result<Event, std::convert::Infallible>>>
where
    Fut: std::future::Future<Output = Result<String, docker::DockerError>> + Send + 'static,
{
    let (tx, rx) = tokio::sync::oneshot::channel();
    tokio::spawn(async move {
        let _ = tx.send(pipeline.await);
    });

    let stream = async_stream::stream! {
        match rx.await {
            Ok(Ok(done_data)) => yield Ok(Event::default().event("done").data(done_data)),
            Ok(Err(e)) => yield Ok(sse_error_event(e)),
            Err(_) => {} // pipeline task panicked; nothing to forward
        }
    };

    Sse::new(stream).keep_alive(KeepAlive::default())
}

async fn create_backup_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Sse<impl futures_core::Stream<Item = Result<Event, std::convert::Infallible>>> {
    tracing::info!(agent = %name, "creating manual backup");
    // Inline, a disconnect could drop the future at restic::snapshot, leaving the container
    // stopped indefinitely (with_container_paused only restarts it after the snapshot returns).
    spawn_pipeline_sse(async move {
        let _guard = agent_write_guard(&state, &name).await;
        let _file_lock = backup::agent_file_lock(&name)?;
        let info = backup::create_backup(&state.docker, &name, crate::types::BackupType::Manual).await?;
        tracing::info!(backup_id = %info.id, size = info.size, "backup created");
        Ok(serde_json::to_string(&info).unwrap_or_default())
    })
}

async fn list_backups_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<Vec<crate::types::BackupInfo>>, (StatusCode, Json<serde_json::Value>)> {
    let lock = state.agent_lock(&name).await;
    let _guard = lock.read().await;

    let backups = backup::list_backups(&state.docker, &name)
        .await
        .map_err(map_docker_err)?;

    Ok(Json(backups))
}

async fn list_all_backups_handler(
    State(state): State<SharedState>,
) -> Json<Vec<crate::types::BackupInfo>> {
    let backups = backup::list_all_backups(&state.docker).await;
    Json(backups)
}

#[derive(Deserialize)]
struct RestoreBackupPath {
    name: String,
    backup_id: String,
}

async fn restore_backup_handler(
    State(state): State<SharedState>,
    Path(path): Path<RestoreBackupPath>,
) -> Sse<impl futures_core::Stream<Item = Result<Event, std::convert::Infallible>>> {
    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "restoring backup");
    // Inline, a disconnect could cancel the future after remove_container_force but before
    // create_container, leaving the agent with no container and unrecoverable via the API
    // (restore_backup's NotFound guard rejects any retry because the container is gone).
    spawn_pipeline_sse(async move {
        let _guard = agent_write_guard(&state, &path.name).await;
        let _file_lock = backup::agent_file_lock(&path.name)?;
        let manage_core_code = state.settings.read().await.manages_core_code(&path.name);
        let user_mounts = {
            let settings = state.settings.read().await;
            settings.agent_mounts(&path.name)
        };
        backup::restore_backup(&state.docker, &path.name, &path.backup_id, &state.env_config, manage_core_code, &user_mounts).await?;
        tracing::info!(agent = %path.name, backup_id = %path.backup_id, "backup restored");
        Ok(r#"{"ok":true}"#.to_string())
    })
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
    let _guard = agent_write_guard(&state, &path.name).await;

    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "deleting backup");
    backup::delete_backup(&state.docker, &path.name, &path.backup_id)
        .await
        .map_err(map_docker_err)?;

    tracing::info!(agent = %path.name, backup_id = %path.backup_id, "backup deleted");
    Ok(Json(serde_json::json!({"ok": true})))
}

// --- Auto-backup settings ---

/// The unified settings view returned by GET/PUT /gateway/settings. Single owner of
/// the daemon-settings wire shape, shared by both handlers.
fn gateway_settings_json(settings: &Settings, channel: &str) -> serde_json::Value {
    serde_json::json!({
        "auto_update": settings.auto_update,
        "channel": channel,
        "auto_backup": {
            "enabled": settings.backup.enabled,
            "hour": settings.backup.hour,
            "retention": settings.backup.retention,
        },
    })
}

/// Apply a sparse backup update in place. Validation (retention floor, hour range)
/// runs in the handler before this is called.
fn apply_backup_update(backup: &mut BackupGlobalSettings, body: &SetBackupSettingsBody) {
    if let Some(enabled) = body.enabled {
        backup.enabled = enabled;
    }
    if let Some(hour) = body.hour {
        backup.hour = hour;
    }
    if let Some(ref ret) = body.retention {
        if let Some(d) = ret.daily { backup.retention.daily = d; }
        if let Some(w) = ret.weekly { backup.retention.weekly = w; }
        if let Some(m) = ret.monthly { backup.retention.monthly = m; }
    }
}

/// The `{enabled, retention, has_override}` body the per-agent backup GET/PUT/DELETE all return.
fn agent_backup_json(enabled: bool, retention: crate::types::RetentionPolicy, has_override: bool) -> Json<serde_json::Value> {
    Json(serde_json::json!({ "enabled": enabled, "retention": retention, "has_override": has_override }))
}

#[derive(Deserialize)]
struct SetBackupSettingsBody {
    enabled: Option<bool>,
    hour: Option<u8>,
    retention: Option<RetentionUpdate>,
}

#[derive(Deserialize)]
struct RetentionUpdate {
    daily: Option<usize>,
    weekly: Option<usize>,
    monthly: Option<usize>,
}

const MIN_RETENTION: usize = 1;

fn validate_retention(update: &RetentionUpdate) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    for (name, val) in [("daily", update.daily), ("weekly", update.weekly), ("monthly", update.monthly)] {
        if let Some(v) = val {
            if v < MIN_RETENTION {
                return Err(err_response(StatusCode::BAD_REQUEST, &format!("retention.{} must be at least {}", name, MIN_RETENTION)));
            }
        }
    }
    Ok(())
}

// --- Unified gateway settings ---

#[derive(Deserialize)]
struct UpdateSettingsBody {
    auto_update: Option<bool>,
    channel: Option<String>,
    auto_backup: Option<SetBackupSettingsBody>,
}

async fn get_gateway_settings_handler(State(state): State<SharedState>) -> Json<serde_json::Value> {
    let settings = state.settings.read().await;
    let channel = crate::channel::Channel::resolve(&settings.channel);
    Json(gateway_settings_json(&settings, channel.as_str()))
}

async fn put_gateway_settings_handler(
    State(state): State<SharedState>,
    Json(body): Json<UpdateSettingsBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if let Some(ref backup) = body.auto_backup {
        if let Some(ref ret) = backup.retention {
            validate_retention(ret)?;
        }
        if let Some(hour) = backup.hour {
            if hour > 23 {
                return Err(err_response(StatusCode::BAD_REQUEST, "hour must be 0-23"));
            }
        }
    }
    let parsed_channel = match body.channel {
        Some(ref c) => Some(
            crate::channel::Channel::parse(c)
                .ok_or_else(|| err_response(StatusCode::BAD_REQUEST, "channel must be 'stable' or 'beta'"))?,
        ),
        None => None,
    };

    {
        let mut settings = state.settings.write().await;
        if let Some(auto_update) = body.auto_update {
            settings.auto_update = auto_update;
            tracing::info!(auto_update, "auto-update setting updated");
        }
        if let Some(channel) = parsed_channel {
            settings.channel = channel.as_str().to_string();
            tracing::info!(channel = channel.as_str(), "release channel updated");
        }
        if let Some(ref backup) = body.auto_backup {
            apply_backup_update(&mut settings.backup, backup);
            tracing::info!("auto-backup settings updated");
        }
        save_settings(&settings);
    }

    // A channel switch must refresh the cached update info so /version reflects the new
    // channel without waiting for the next periodic poll (mirrors the old channel handler).
    if let Some(channel) = parsed_channel {
        match tokio::task::spawn_blocking(move || update_check::check_once(channel)).await {
            Ok(Ok(info)) => *state.update_info.lock().await = Some(info),
            Ok(Err(e)) => tracing::warn!("update check after channel switch failed: {}", e),
            Err(e) => tracing::error!("update check task after channel switch failed: {}", e),
        }
    }

    let settings = state.settings.read().await;
    let channel = crate::channel::Channel::resolve(&settings.channel);
    Ok(Json(gateway_settings_json(&settings, channel.as_str())))
}

// --- Read-only gateway info ---

/// Read-only daemon reachability facts surfaced by GET /gateway/info. Pure so the
/// wire shape is unit-testable without constructing AppState.
fn gateway_info_json(expose_lan: bool, lan_url: &Option<String>, tunnel_url: &Option<String>, port: u16) -> serde_json::Value {
    serde_json::json!({
        "lan": { "exposed": expose_lan, "url": lan_url },
        "tunnel_url": tunnel_url,
        "port": port,
    })
}

async fn gateway_info_handler(State(state): State<SharedState>) -> Json<serde_json::Value> {
    let tunnel_url = state.tunnel_url.lock().await.clone();
    Json(gateway_info_json(state.expose_lan, &state.lan_url, &tunnel_url, state.https_port))
}

// --- Per-agent settings ---

async fn get_agent_settings_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let settings = state.settings.read().await;
    let agent = settings.agents.get(&name).cloned().unwrap_or_default();
    Ok(Json(serde_json::json!({
        "manage_agent_code": agent.manage_agent_code,
    })))
}

async fn get_agent_backup_settings_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Json<serde_json::Value> {
    let settings = state.settings.read().await;
    let has_override = settings.backup.agents.contains_key(&name);
    let (enabled, retention) = settings.backup.effective_for(&name);
    agent_backup_json(enabled, retention, has_override)
}

async fn set_agent_backup_settings_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<SetBackupSettingsBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if let Some(ref ret) = body.retention {
        validate_retention(ret)?;
    }

    let mut settings = state.settings.write().await;
    let global_retention = settings.backup.retention;
    let global_enabled = settings.backup.enabled;

    let entry = settings.backup.agents.entry(name.clone()).or_insert(AgentBackupOverride {
        enabled: None,
        retention: None,
    });

    if let Some(enabled) = body.enabled {
        entry.enabled = Some(enabled);
    }
    if let Some(ret) = body.retention {
        let mut r = entry.retention.unwrap_or(global_retention);
        if let Some(d) = ret.daily { r.daily = d; }
        if let Some(w) = ret.weekly { r.weekly = w; }
        if let Some(m) = ret.monthly { r.monthly = m; }
        entry.retention = Some(r);
    }

    let effective_enabled = entry.enabled.unwrap_or(global_enabled);
    let effective_retention = entry.retention.unwrap_or(global_retention);

    save_settings(&settings);
    tracing::info!(agent = %name, "agent backup settings updated");

    Ok(agent_backup_json(effective_enabled, effective_retention, true))
}

async fn delete_agent_backup_settings_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Json<serde_json::Value> {
    let mut settings = state.settings.write().await;
    settings.backup.agents.remove(&name);
    save_settings(&settings);
    tracing::info!(agent = %name, "agent backup override removed, using global settings");
    agent_backup_json(settings.backup.enabled, settings.backup.retention, false)
}

// --- Host filesystem grants ---
//
// A grant is a decision only the user makes: PUT sits behind the API-key-only middleware
// (never the agent token), so an agent can never mount itself extra host access. GET is
// dual-auth (API key or the agent's own token) so a skill can list its own grants.

#[derive(Deserialize)]
struct MountInput {
    host_path: String,
    #[serde(default)]
    container_path: Option<String>,
    #[serde(default)]
    writable: bool,
}

#[derive(Deserialize)]
struct SetMountsBody {
    mounts: Vec<MountInput>,
}

async fn list_mounts_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let settings = state.settings.read().await;
    let mounts = settings.agent_mounts(&name);
    Ok(Json(serde_json::json!({ "mounts": mounts })))
}

async fn set_mounts_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<SetMountsBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let inputs: Vec<(String, Option<String>, bool)> =
        body.mounts.into_iter().map(|m| (m.host_path, m.container_path, m.writable)).collect();
    // The agent's already-accepted grant paths grandfather a temporarily-offline existing grant so
    // one missing drive can't reject the whole edit (see mounts::validate_mount).
    let known_host_paths: std::collections::HashSet<String> = {
        let settings = state.settings.read().await;
        settings.agent_mounts(&name).into_iter().map(|m| m.host_path).collect()
    };
    // validate_mounts canonicalizes each host path (blocking std::fs, and a hung network mount can
    // stall for a long time), so run it off the async worker.
    let validated = tokio::task::spawn_blocking(move || crate::mounts::validate_mounts(&inputs, &known_host_paths))
        .await
        .map_err(|_| err_response(StatusCode::INTERNAL_SERVER_ERROR, "mount validation task failed"))?
        .map_err(|e| (StatusCode::BAD_REQUEST, Json(serde_json::json!({ "error": e.to_string() }))))?;
    {
        let mut settings = state.settings.write().await;
        settings.agents.entry(name.clone()).or_default().mounts = validated.clone();
        save_settings(&settings);
    }
    tracing::info!(agent = %name, "agent mounts updated");
    Ok(Json(serde_json::json!({ "mounts": validated, "restart_required": true })))
}

/// Suggest existing host folders the user might share, so they don't hand-type a path. Reads the
/// host filesystem (common mount roots + home media folders), so it is API-key only — never the
/// agent token; an agent must not enumerate the host. The scan is blocking std::fs (and a hung
/// network mount under one of the roots can stall it), so it runs off the async worker.
async fn host_folder_suggestions_handler() -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let folders = tokio::task::spawn_blocking(crate::mounts::suggest_host_folders)
        .await
        .map_err(|_| err_response(StatusCode::INTERNAL_SERVER_ERROR, "folder scan task failed"))?;
    Ok(Json(serde_json::json!({ "folders": folders })))
}

// --- Constitution ---
//
// A user-authored charter prepended to the agent's system prompt ahead of MEMORY.md.
// It lives in host config and is bind-mounted read-only into the container, so the agent
// reads it but cannot edit it. These endpoints sit behind the API-key middleware only
// (never the agent token), so the agent itself cannot reach them. Like the memory editor,
// PUT only persists; the client restarts the agent so the new system prompt loads.

#[derive(Deserialize)]
struct SetConstitutionBody {
    content: String,
}

async fn get_constitution_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let content = docker::read_constitution(&state.env_config.agents_dir, &name)
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string()))?;
    Ok(Json(serde_json::json!({ "content": content })))
}

async fn set_constitution_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    Json(body): Json<SetConstitutionBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    docker::validate_name(&name).map_err(map_docker_err)?;
    let _guard = agent_write_guard(&state, &name).await;

    docker::write_constitution(&state.env_config.agents_dir, &name, &body.content)
        .map_err(|e| err_response(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string()))?;
    tracing::info!(agent = %name, "constitution updated");
    Ok(ok_json())
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
        // SAFETY: fd comes from file.as_raw_fd() and file is kept alive past this call, so the
        // descriptor is valid for the duration of flock. flock with these flags has no other
        // preconditions.
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

// The request-timeout layer applied to the control/JSON sub-router only. Returns 408 Request
// Timeout when a handler exceeds the deadline. Kept as one helper so the timed routes and the
// tests that lock this behavior share a single 408-producing mechanism.
fn request_timeout_layer(deadline: std::time::Duration) -> tower_http::timeout::TimeoutLayer {
    tower_http::timeout::TimeoutLayer::with_status_code(StatusCode::REQUEST_TIMEOUT, deadline)
}

fn control_timeout_layer() -> tower_http::timeout::TimeoutLayer {
    request_timeout_layer(std::time::Duration::from_secs(CONTROL_REQUEST_TIMEOUT_SECS))
}

fn longrun_timeout_layer() -> tower_http::timeout::TimeoutLayer {
    request_timeout_layer(std::time::Duration::from_secs(LONGRUN_REQUEST_TIMEOUT_SECS))
}

pub fn build_router(state: SharedState) -> Router {

    let vestad_public = Router::new()
        .route("/health", get(health))
        .route("/info", get(info))
        .route("/auth/session", post(auth::create_session_handler))
        .route("/auth/refresh", post(auth::refresh_session_handler))
        // Reference data: read-only and non-sensitive (static per version, already shown in the
        // public onboarding UI). Unauthenticated so every frontend reads it the same way — the
        // app, the CLI, and the onboard skill (just another frontend hitting its own box's vestad
        // over the loopback), none of which then need to keep a hardcoded copy.
        .route("/manifest", get(crate::manifest::manifest_handler));

    // Control/JSON routes: bounded request/response handlers. A finite TimeoutLayer caps each
    // request so a stalled docker/restic call cannot hold a connection open indefinitely.
    let vestad_protected_timed = Router::new()
        // Hosted (vesta.run) login upgrade: the native app arrives with a control-
        // plane-minted ACCESS token (verified by auth_middleware) and exchanges it
        // for a registered, rotating refresh token — so the box never mints a
        // refresh token for an unauthenticated caller.
        .route("/auth/exchange", post(auth::exchange_session_handler))
        .route("/version", get(version))
        .route("/version/check", post(version_check))
        .route("/gateway/update", post(gateway_update_handler))
        .route("/gateway/restart", post(restart_gateway_handler))
        .route("/gateway/info", get(gateway_info_handler))
        .route("/providers/claude/oauth/start", post(crate::providers::claude::oauth_start_handler))
        .route("/providers/claude/oauth/complete", post(crate::providers::claude::oauth_complete_handler))
        .route("/providers/openrouter/models/top", get(crate::providers::openrouter::list_top_models_handler))
        .route("/providers/openrouter/validate-key", post(crate::providers::openrouter::validate_key_handler))
        .route("/agents", get(list_agents_handler))
        .route("/agents/start", post(start_all_handler))
        .route(
            "/agents/{name}",
            get(agent_status_handler).delete(destroy_agent_handler).patch(rename_agent_handler),
        )
        .route("/agents/{name}/build-phase", get(build_phase_handler))
        .route("/agents/{name}/start", post(start_agent_handler))
        .route("/agents/{name}/config", put(set_config_handler).get(get_config_handler))
        .route(
            "/agents/{name}/provider",
            get(get_provider_handler)
                .put(set_provider_handler)
                .patch(patch_provider_handler)
                .delete(clear_provider_handler),
        )
        .route("/agents/{name}/tree", get(tree_handler))
        .route("/agents/{name}/file", get(read_file_handler))
        .route("/agents/{name}/file", axum::routing::put(write_file_handler))
        .route("/backups", get(list_all_backups_handler))
        .route("/agents/{name}/backups", get(list_backups_handler))
        .route("/agents/{name}/backups/{backup_id}", axum::routing::delete(delete_backup_handler))
        .route("/agents/{name}/constitution", get(get_constitution_handler))
        .route("/agents/{name}/constitution", axum::routing::put(set_constitution_handler))
        .route("/agents/{name}/settings", get(get_agent_settings_handler))
        .route("/agents/{name}/settings/backup", get(get_agent_backup_settings_handler))
        .route("/agents/{name}/settings/backup", axum::routing::put(set_agent_backup_settings_handler))
        .route("/agents/{name}/settings/backup", axum::routing::delete(delete_agent_backup_settings_handler))
        .route("/agents/{name}/mounts", put(set_mounts_handler))
        .route("/host/folders", get(host_folder_suggestions_handler))
        .route("/gateway/settings", get(get_gateway_settings_handler).put(put_gateway_settings_handler))
        .layer(control_timeout_layer())
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware,
        ));

    // Create and rebuild run image builds; the longrun deadline keeps them from 408ing (see the const).
    let vestad_protected_longrun = Router::new()
        .route("/agents", post(create_agent_handler))
        .route("/agents/{name}/rebuild", post(rebuild_agent_handler))
        .layer(longrun_timeout_layer())
        .layer(middleware::from_fn_with_state(state.clone(), auth::auth_middleware));

    // Streaming and WS routes: long-lived connections (logs `tail -f`, backup create/restore
    // progress SSE, control WS upgrade). These are deliberately EXEMPT from the request timeout
    // so a finite deadline cannot truncate a legitimate live stream or break a WS upgrade.
    let vestad_protected_streaming = Router::new()
        .route("/agents/{name}/logs", get(logs_handler))
        .route("/agents/{name}/backups", post(create_backup_handler))
        .route("/agents/{name}/backups/{backup_id}/restore", post(restore_backup_handler))
        .route("/ws", get(control_ws::control_ws_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware,
        ));

    // Agent proxy: auth is checked inside the handler — service requests
    // (dashboard, voice, etc.) are unauthenticated so assets load in iframes.
    let agents_proxy = Router::new()
        .route("/agents/{name}/{*path}", any(agent_proxy::agent_proxy_handler))
        .with_state(state.clone());

    // Service registry: mutating endpoints require agent token. The
    // account-token mint (issue #20) rides the same agent-token tier: the agent
    // proves itself, vestad signs a server-identity token locally and returns it.
    let agents_services = Router::new()
        .route("/agents/{name}/services", post(register_service_handler))
        .route("/agents/{name}/services/{service}", axum::routing::delete(unregister_service_handler))
        .route("/agents/{name}/services/{service}/invalidate", post(control_ws::invalidate_service_handler))
        .route("/agents/{name}/account-token", post(account_token_handler))
        .route("/agents/{name}/workspace.bundle", get(workspace_bundle_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware_agent_token,
        ))
        .with_state(state.clone());

    // Self-lifecycle: stop/restart accept either the API key (app/CLI) or the agent's own
    // X-Agent-Token. The agent-token branch is inherently self-scoped — the middleware checks the
    // token against the agent name in the path — so an agent can stop/restart only itself. This is
    // how the agent's restart_vesta/stop_vesta tools reach vestad (it then does the docker action).
    // Stop is quick (control tier); restart can trigger a full snapshot+recreate when host-folder
    // grants drifted (docker export|import), which for a multi-GB agent exceeds the control deadline —
    // so it rides the longrun timeout like the rebuild route, not the control tier.
    let agents_self_stop = Router::new()
        .route("/agents/{name}/stop", post(stop_agent_handler))
        .layer(control_timeout_layer())
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware_api_or_agent_token,
        ))
        .with_state(state.clone());
    let agents_self_restart = Router::new()
        .route("/agents/{name}/restart", post(restart_agent_handler))
        .layer(longrun_timeout_layer())
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware_api_or_agent_token,
        ))
        .with_state(state.clone());

    // Service listing: read-only, accepts either API key or the agent's token
    let agents_services_read = Router::new()
        .route("/agents/{name}/services", get(list_services_handler))
        .route("/agents/{name}/mounts", get(list_mounts_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware_api_or_agent_token,
        ))
        .with_state(state.clone());

    // Gateway logs: accepts either API key or the agent's token (agent self-diagnosis)
    let gateway_logs = Router::new()
        .route("/gateway/logs", get(gateway_logs_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware_api_or_agent_token,
        ))
        .with_state(state.clone());

    Router::new()
        .merge(vestad_public)
        .merge(vestad_protected_timed)
        .merge(vestad_protected_longrun)
        .merge(vestad_protected_streaming)
        .merge(agents_self_stop)
        .merge(agents_self_restart)
        .merge(agents_services)
        .merge(agents_services_read)
        .merge(gateway_logs)
        .merge(agents_proxy)
        .merge(crate::app_static::router())
        .layer(
            tower_http::cors::CorsLayer::new()
                .allow_origin(tower_http::cors::Any)
                .allow_methods(tower_http::cors::Any)
                .allow_headers(tower_http::cors::Any),
        )
        .layer(
            tower_http::trace::TraceLayer::new_for_http()
                .make_span_with(tower_http::trace::DefaultMakeSpan::new().level(tracing::Level::INFO))
                .on_request(
                    |request: &axum::http::Request<_>, _span: &tracing::Span| {
                        let path = request.uri().path();
                        let is_noisy = request.method() == axum::http::Method::OPTIONS
                            || path.ends_with("/logs");
                        if !is_noisy {
                            tracing::info!(method = %request.method(), path = %request.uri(), "request");
                        }
                    },
                )
                .on_response(tower_http::trace::DefaultOnResponse::new().level(tracing::Level::DEBUG))
                .on_failure(tower_http::trace::DefaultOnFailure::new().level(tracing::Level::DEBUG)),
        )
        .with_state(state)
}

// --- Server start ---

// --- Auto-backup background task ---

fn spawn_auto_backup_task(state: SharedState) {
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(AUTO_BACKUP_CHECK_INTERVAL_SECS)).await;

            let backup_settings = {
                let settings = state.settings.read().await;
                settings.backup.clone()
            };

            if !backup_settings.enabled {
                tracing::debug!("auto-backup: disabled, skipping cycle");
                continue;
            }

            // Fire on or after the configured local hour rather than only during that exact hour,
            // then let the per-type dedup below make the work idempotent (one daily per local day,
            // etc.). This way a spring-forward DST jump that skips the target hour still triggers a
            // backup on the next cycle, and a daemon that was down through the hour catches up.
            let target_hour = backup_settings.hour;
            let current_hour = crate::time_utils::local_hour();
            if current_hour < target_hour {
                tracing::debug!(current_hour, target_hour, "auto-backup: before daily window, skipping");
                continue;
            }

            let agents = backup::list_agent_names(&state.docker).await;

            if agents.is_empty() {
                tracing::debug!("auto-backup: no agents found, skipping cycle");
                continue;
            }

            tracing::info!(agent_count = agents.len(), "auto-backup: starting cycle");

            let now_epoch = crate::time_utils::now_epoch_secs();
            let today_local = crate::time_utils::local_date_of_epoch(now_epoch);
            let seven_days_ago = crate::time_utils::now_timestamp_from_epoch(now_epoch - 7 * 86400);
            let thirty_days_ago = crate::time_utils::now_timestamp_from_epoch(now_epoch - 30 * 86400);

            for name in &agents {
                // Resolve per-agent settings (override or global fallback)
                let (agent_enabled, ret) = backup_settings.effective_for(name);
                if !agent_enabled {
                    tracing::debug!(agent = %name, "auto-backup: disabled for agent, skipping");
                    continue;
                }

                let _guard = agent_write_guard(&state, name).await;

                if let Some(age) = backup::container_age_secs(&state.docker, name).await {
                    if age < backup::MIN_AGE_FOR_BACKUP_SECS {
                        tracing::debug!(agent = %name, age_hours = age / 3600, "auto-backup: skipping young agent");
                        continue;
                    }
                }

                let mut backups = match backup::list_backups(&state.docker, name).await {
                    Ok(b) => b,
                    Err(e) => {
                        tracing::error!(agent = %name, error = %e, "auto-backup: failed to list backups");
                        continue;
                    }
                };

                let mut needed = Vec::new();

                let has_daily_today = backups.iter().any(|b| {
                    b.backup_type == crate::types::BackupType::Daily
                        && crate::time_utils::parse_compact_utc_epoch(&b.created_at).map(crate::time_utils::local_date_of_epoch).as_deref() == Some(today_local.as_str())
                });
                if !has_daily_today {
                    needed.push(crate::types::BackupType::Daily);
                }

                let has_recent_weekly = backups.iter().any(|b| {
                    b.backup_type == crate::types::BackupType::Weekly && b.created_at >= seven_days_ago
                });
                if !has_recent_weekly {
                    needed.push(crate::types::BackupType::Weekly);
                }

                let has_recent_monthly = backups.iter().any(|b| {
                    b.backup_type == crate::types::BackupType::Monthly && b.created_at >= thirty_days_ago
                });
                if !has_recent_monthly {
                    needed.push(crate::types::BackupType::Monthly);
                }

                if !needed.is_empty() {
                    let _file_lock = match backup::agent_file_lock(name) {
                        Ok(lock) => lock,
                        Err(e) => {
                            tracing::error!(agent = %name, error = %e, "auto-backup: failed to acquire lock");
                            continue;
                        }
                    };
                    tracing::info!(agent = %name, types = ?needed, "auto-backup: creating backups");
                    for (bt, result) in backup::create_backups_batch(&state.docker, name, needed).await {
                        match result {
                            Ok(info) => {
                                tracing::info!(agent = %name, backup_type = %bt, backup_id = %info.id, "auto-backup: created");
                                backups.insert(0, info);
                            }
                            Err(e) => {
                                tracing::error!(agent = %name, backup_type = %bt, error = %e, "auto-backup: failed");
                            }
                        }
                    }
                }

                backup::cleanup_backups(name, &backups, &ret).await;
            }

            tracing::info!(agent_count = agents.len(), "auto-backup: cycle complete");
        }
    });
}

// --- Update-check background task ---

fn spawn_update_check_task(state: SharedState) {
    tokio::spawn(async move {
        loop {
            let channel = effective_channel(&state).await;
            match tokio::task::spawn_blocking(move || update_check::check_once(channel)).await {
                Ok(Ok(info)) => {
                    let update_available = info.update_available;
                    *state.update_info.lock().await = Some(info);
                    // Auto-apply when enabled (the default) and a newer release exists
                    // on the active channel. `perform_update` no-ops if already current
                    // and restarts the systemd service on success — replacing this
                    // process — so control may never return past this call.
                    if update_available && state.settings.read().await.auto_update {
                        tracing::info!(channel = channel.as_str(), "auto-update: newer release available, applying");
                        match tokio::task::spawn_blocking(move || self_update::perform_update(channel)).await {
                            Ok(Ok(outcome)) => tracing::info!(
                                updated = outcome.updated,
                                restarted = outcome.restarted,
                                current = %outcome.current,
                                latest = %outcome.latest,
                                "auto-update finished",
                            ),
                            Ok(Err(e)) => tracing::warn!("auto-update failed: {}", e),
                            Err(e) => tracing::error!("auto-update task panicked: {}", e),
                        }
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

pub struct ServerConfig {
    pub port: u16,
    pub http_listener: tokio::net::TcpListener,
    pub api_key: String,
    pub cert_pem: String,
    pub key_pem: String,
    pub tunnel_url: Option<String>,
    pub config_dir: std::path::PathBuf,
    pub docker: bollard::Docker,
    pub dev_mode: bool,
    pub expose_lan: bool,
    pub lan_url: Option<String>,
    pub on_agents_changed: agent_status::OnAgentsChanged,
}

pub async fn run_server(cfg: ServerConfig) {
    let ServerConfig {
        port,
        http_listener,
        api_key,
        cert_pem,
        key_pem,
        tunnel_url,
        config_dir,
        docker,
        dev_mode,
        expose_lan,
        lan_url,
        on_agents_changed,
    } = cfg;
    let agents_dir = config_dir.join("agents");
    let env_config = docker::AgentEnvConfig {
        config_dir,
        agents_dir,
        vestad_port: port,
        vestad_tunnel: tunnel_url.clone(),
    };
    if let Err(e) = docker::validate_config_dir(&env_config) {
        tracing::error!(error = %e, "config directory validation failed — aborting startup");
        std::process::exit(1);
    }
    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        mode = if cfg!(debug_assertions) { "dev" } else { "prod" },
        "agent code embedded in binary",
    );
    // Capture whether this boot will deliver new agent code BEFORE extracting it: a re-extract
    // replaces the code dir, so reconcile must restart running agents to reload the new core (and
    // re-bind their now-detached core mount).
    let agent_code_changed = crate::agent_code::agent_code_is_stale(&env_config.config_dir);
    let code_dir = match crate::agent_code::ensure_agent_code(&env_config.config_dir) {
        Ok(dir) => dir,
        Err(e) => {
            tracing::error!(error = %e, "failed to extract embedded agent code — aborting startup");
            std::process::exit(1);
        }
    };
    // The workspace bundle is how every box attaches, syncs, and installs skills, so a vestad
    // that can't build it is not serviceable. A build failure (git missing, disk error) aborts
    // startup with a clear error rather than serving a half-broken daemon whose boxes silently
    // fail to sync.
    if let Err(e) = crate::workspace::ensure_workspace(&env_config.config_dir, &code_dir) {
        tracing::error!(error = %e, "workspace bundle build failed — aborting startup");
        std::process::exit(1);
    }
    let agent_settings = load_settings().agents.clone();
    let state = Arc::new(AppState::new(api_key, env_config, docker.clone(), tunnel_url, dev_mode, port, expose_lan, lan_url));
    // Reconcile in the background so the API serves immediately: a rebuild (entrypoint/mount change)
    // snapshots each container's filesystem (minutes), and awaiting it would leave vestad unreachable.
    let reconcile_docker = docker.clone();
    let reconcile_env = state.env_config.clone();
    tokio::spawn(async move {
        docker::reconcile_containers(
            &reconcile_docker,
            &reconcile_env,
            agent_code_changed,
            &move |name| agent_settings.get(name).is_none_or(|s| s.manage_agent_code),
            // Desired-run state is read LIVE (not a boot snapshot): a stop/start the user issues
            // during the slow reconcile window would otherwise be reverted by the start/stop step.
            &|name| load_settings().agents.get(name).is_none_or(|s| s.user_desired == UserDesired::Running),
            // Mount grants are also read LIVE so a grant added/removed during the reconcile window
            // (or via a later `vesta restart`) is reflected without needing a fresh vestad boot.
            &|name| load_settings().agent_mounts(name),
        )
        .await;
    });
    // Keep a docker handle for the shutdown hook: vestad stops every agent when it exits, so a
    // vestad update/restart hands off with nothing running on a stale container.
    let shutdown_docker = docker.clone();
    agent_status::spawn_agent_status_task(
        state.agent_status_cache.clone(),
        docker,
        state.http_client.clone(),
        state.env_config.agents_dir.clone(),
        on_agents_changed,
    );
    let app = build_router(state.clone());
    spawn_auto_backup_task(state.clone());
    if dev_mode {
        tracing::info!("dev mode: auto-update disabled");
    } else {
        spawn_update_check_task(state);
    }

    let rustls_config = axum_server::tls_rustls::RustlsConfig::from_pem(
        cert_pem.into_bytes(),
        key_pem.into_bytes(),
    )
    .await
    .expect("failed to configure TLS");

    // HTTP listener was bound atomically in main.rs before the runtime entered
    // the async block, closing the TOCTOU race on the HTTP port. HTTPS binds
    // inside axum_server::bind_rustls below; its window is short and a loss is
    // loud (the task panics) rather than silent.
    // Bind the HTTPS control API to loopback by default — every normal path
    // reaches vestad via localhost (cloudflared dials https://localhost:{port}),
    // so this keeps the API off the LAN and the public internet. `--expose-lan`
    // opts into binding all interfaces so other devices on the LAN can connect
    // (0.0.0.0 still includes loopback, so the tunnel keeps working); the API is
    // then guarded only by the API key + fingerprint-pinned self-signed TLS. The
    // plain HTTP server stays loopback-only regardless (see main.rs).
    let https_bind_addr = if expose_lan {
        std::net::Ipv4Addr::UNSPECIFIED
    } else {
        std::net::Ipv4Addr::LOCALHOST
    };
    let https_addr = std::net::SocketAddr::from((https_bind_addr, port));

    tracing::info!(port, %https_bind_addr, "https listening");
    tracing::info!(http_port = port + 1, "http listening on 127.0.0.1");

    let http_app = app.clone();
    let http_handle = tokio::spawn(async move {
        axum::serve(http_listener, http_app.into_make_service_with_connect_info::<std::net::SocketAddr>())
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
        _ = shutdown_signal() => {
            tracing::info!("shutdown signal received, stopping all agents before exit");
            docker::stop_all_agents(&shutdown_docker).await;
        }
    }
}

/// Resolve when vestad should shut down: SIGTERM (systemd stop/restart) or Ctrl-C. Lets vestad
/// stop its agents before exiting so the next boot owns the clean rebuild-then-start handoff.
async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut sig) => {
                sig.recv().await;
            }
            Err(e) => {
                tracing::warn!(error = %e, "failed to install SIGTERM handler; relying on Ctrl-C only");
                std::future::pending::<()>().await;
            }
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}

#[cfg(test)]
mod tests {
    use super::is_cached_port_reusable;

    // --- Rename notification payload (the content contract the agent self-heals on) ---

    #[test]
    fn rename_notification_payload_carries_both_names_and_rfc3339_timestamp() {
        // Fixed epoch -> deterministic RFC3339 timestamp, no wall clock.
        let payload = super::rename_notification_payload("old-bot", "new-bot", 1_700_000_000).expect("payload");
        assert_eq!(payload["source"], "vestad");
        assert_eq!(payload["type"], "rename");
        assert_eq!(payload["interrupt"], true);
        assert_eq!(payload["old_name"], "old-bot");
        assert_eq!(payload["new_name"], "new-bot");
        assert_eq!(payload["timestamp"], "2023-11-14T22:13:20Z");
        let message = payload["message"].as_str().expect("message is a string");
        assert!(message.contains("old-bot"), "message missing old name: {message}");
        assert!(message.contains("new-bot"), "message missing new name: {message}");
    }

    // --- Workspace bundle: 404 before first build, bytes after ---

    #[tokio::test]
    async fn workspace_bundle_404s_before_first_build_and_serves_bytes_after() {
        let tmp = tempfile::tempdir().expect("tempdir");

        let missing = super::workspace_bundle_response(tmp.path()).await;
        assert_eq!(missing.status(), super::StatusCode::NOT_FOUND);

        let bundle = crate::workspace::bundle_path(tmp.path());
        std::fs::create_dir_all(bundle.parent().expect("bundle has a parent")).expect("mkdir");
        std::fs::write(&bundle, b"BUNDLEBYTES").expect("write bundle");
        let served = super::workspace_bundle_response(tmp.path()).await;
        assert_eq!(served.status(), super::StatusCode::OK);
        let body = axum::body::to_bytes(served.into_body(), usize::MAX).await.expect("body");
        assert_eq!(&body[..], b"BUNDLEBYTES");
    }

    // --- Request-timeout layer: control routes time out, streaming/WS routes are exempt (#639) ---

    // The same layering decision build_router makes: a TimeoutLayer on the control/JSON class and
    // no timeout on the streaming/WS class. A short deadline keeps the test fast while exercising
    // the real tower-http TimeoutLayer (the production 408-producing mechanism).
    async fn serve_router(router: axum::Router) -> (u16, tokio::task::JoinHandle<()>) {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = tokio::spawn(async move {
            axum::serve(listener, router).await.unwrap();
        });
        (port, handle)
    }

    #[tokio::test]
    async fn control_route_times_out_when_handler_exceeds_deadline() {
        let deadline = std::time::Duration::from_millis(100);
        let slow = || async {
            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
            "done"
        };
        let timed = axum::Router::new()
            .route("/control", axum::routing::get(slow))
            .layer(super::request_timeout_layer(deadline));
        let (port, handle) = serve_router(timed).await;

        let response = reqwest::Client::new()
            .get(format!("http://127.0.0.1:{}/control", port))
            .send()
            .await
            .unwrap();

        assert_eq!(response.status(), reqwest::StatusCode::REQUEST_TIMEOUT);
        handle.abort();
    }

    #[tokio::test]
    async fn streaming_route_is_exempt_from_the_deadline() {
        // The streaming class carries no timeout layer, so a handler that runs longer than the
        // control deadline must still complete (mirrors logs `tail -f` / backup-progress SSE).
        let slow = || async {
            tokio::time::sleep(std::time::Duration::from_millis(300)).await;
            "stream"
        };
        let streaming = axum::Router::new().route("/stream", axum::routing::get(slow));
        let (port, handle) = serve_router(streaming).await;

        let response = reqwest::Client::new()
            .get(format!("http://127.0.0.1:{}/stream", port))
            .send()
            .await
            .unwrap();

        assert_eq!(response.status(), reqwest::StatusCode::OK);
        assert_eq!(response.text().await.unwrap(), "stream");
        handle.abort();
    }

    #[tokio::test]
    async fn control_route_under_deadline_succeeds() {
        let fast = || async { "ok" };
        let timed = axum::Router::new()
            .route("/control", axum::routing::get(fast))
            .layer(super::request_timeout_layer(std::time::Duration::from_secs(5)));
        let (port, handle) = serve_router(timed).await;

        let response = reqwest::Client::new()
            .get(format!("http://127.0.0.1:{}/control", port))
            .send()
            .await
            .unwrap();

        assert_eq!(response.status(), reqwest::StatusCode::OK);
        handle.abort();
    }

    #[tokio::test]
    async fn longrun_layer_allows_a_request_past_the_control_deadline() {
        // A handler slower than a control-class deadline must survive under the longrun layer —
        // the mechanism that keeps agent create/rebuild (multi-minute image builds) from 408ing.
        let slow = || async {
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
            "ok"
        };
        let control_deadline = std::time::Duration::from_millis(100);
        let longrun_deadline = std::time::Duration::from_millis(2000);
        let router = axum::Router::new()
            .route("/control", axum::routing::post(slow))
            .layer(super::request_timeout_layer(control_deadline))
            .merge(
                axum::Router::new()
                    .route("/longrun", axum::routing::post(slow))
                    .layer(super::request_timeout_layer(longrun_deadline)),
            );
        let (port, handle) = serve_router(router).await;
        let client = reqwest::Client::new();

        let timed = client.post(format!("http://127.0.0.1:{}/control", port)).send().await.unwrap();
        assert_eq!(timed.status(), reqwest::StatusCode::REQUEST_TIMEOUT);
        let long = client.post(format!("http://127.0.0.1:{}/longrun", port)).send().await.unwrap();
        assert_eq!(long.status(), reqwest::StatusCode::OK);

        const { assert!(super::LONGRUN_REQUEST_TIMEOUT_SECS > super::CONTROL_REQUEST_TIMEOUT_SECS) };
        handle.abort();
    }

    #[tokio::test]
    async fn cached_port_is_reusable_when_free() {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        assert!(is_cached_port_reusable(port).await, "a free port must be reusable");
    }

    // Regression for #433.
    #[tokio::test]
    async fn cached_port_is_not_reusable_when_squatted() {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(
            !is_cached_port_reusable(port).await,
            "a port held by another listener must not be reported reusable",
        );
    }

    // ── API contract fixtures ──────────────────────────────────────────────
    //
    // Serializes sample values of every wire type the web app consumes into
    // apps/web/src/lib/vestad-api-fixtures.ts, using the real production
    // serialization code. The web's api-contract.test.ts then `satisfies`-checks
    // those fixtures against its TypeScript types, so a wire format change on
    // either side fails CI instead of breaking clients at runtime.

    use super::{ServiceEntry, TreeEntry};
    use crate::providers::claude::OAuthStartResponse;
    use crate::docker::{AgentStatus, ListEntry, StatusJson};
    use crate::types::{BackupInfo, BackupType};
    use std::collections::HashMap;

    fn contract_fixtures() -> serde_json::Value {
        let agent_statuses: Vec<serde_json::Value> = [
            AgentStatus::Alive,
            AgentStatus::SettingUp,
            AgentStatus::Starting,
            AgentStatus::NotAuthenticated,
            AgentStatus::Unprovisioned,
            AgentStatus::Stopped,
            AgentStatus::Dead,
            AgentStatus::NotFound,
        ]
        .iter()
        .map(|status| serde_json::to_value(status).expect("serialize AgentStatus"))
        .collect();

        // The control WS "agents" message, built by the production code path.
        let agents = vec![
            ListEntry { name: "sample-agent".into(), status: AgentStatus::Alive, ws_port: 4200, started_at: Some("2026-01-01T00:00:00Z".into()) },
            ListEntry { name: "stopped-agent".into(), status: AgentStatus::Stopped, ws_port: 4201, started_at: None },
        ];
        let mut activity = HashMap::new();
        activity.insert("sample-agent".to_string(), "thinking".to_string());
        let mut agent_services = HashMap::new();
        agent_services.insert("dashboard".to_string(), ServiceEntry { port: 8080, public: true });
        let mut services = HashMap::new();
        services.insert("sample-agent".to_string(), agent_services);
        let mut agent_revs = HashMap::new();
        agent_revs.insert("dashboard".to_string(), 3u64);
        let mut revs = HashMap::new();
        revs.insert("sample-agent".to_string(), agent_revs);
        let agents_ws_message = crate::control_ws::build_agents_message(&agents, &activity, &services, &revs);

        let backups: Vec<serde_json::Value> = [
            BackupType::Manual,
            BackupType::Daily,
            BackupType::Weekly,
            BackupType::Monthly,
            BackupType::PreRestore,
        ]
        .into_iter()
        .map(|backup_type| {
            serde_json::to_value(BackupInfo {
                id: "1a2b3c4d".into(),
                agent_name: "sample-agent".into(),
                backup_type,
                created_at: "2026-01-01T00:00:00Z".into(),
                size: 1234567890,
            })
            .expect("serialize BackupInfo")
        })
        .collect();

        let agent_status_json = serde_json::to_value(StatusJson {
            name: "sample-agent".into(),
            status: AgentStatus::Alive,
            id: Some("c0ffee".into()),
            ws_port: 4200,
        })
        .expect("serialize StatusJson");

        let auth_start = serde_json::to_value(OAuthStartResponse {
            auth_url: "https://claude.ai/oauth/authorize?code=true".into(),
            session_id: "0123456789abcdef".into(),
        })
        .expect("serialize OAuthStartResponse");

        let tree_entry = serde_json::to_value(TreeEntry {
            path: "notes/todo.md".into(),
            is_dir: false,
            mode: 0o644,
        })
        .expect("serialize TreeEntry");

        // Mirrors version_json() above; that response is an inline json! so it cannot be
        // serialized from a struct here. Keep this in sync with version_json().
        let version = serde_json::json!({
            "version": "0.1.0",
            "api_compat": "0.2",
            "latest_version": "0.1.1",
            "update_available": true,
            "dev_mode": false,
            "channel": "stable",
            "auto_update": true,
        });

        serde_json::json!({
            "agent_statuses": agent_statuses,
            "agents_ws_message": agents_ws_message,
            "agent_status_json": agent_status_json,
            "backups": backups,
            "auth_start": auth_start,
            "tree_entry": tree_entry,
            "version": version,
        })
    }

    #[test]
    fn api_contract_fixtures_up_to_date() {
        let fixtures = contract_fixtures();
        let json = serde_json::to_string_pretty(&fixtures).expect("serialize fixtures");
        let content = format!(
            "// AUTO-GENERATED by vestad's API contract test. Do not edit by hand.\n\
             // Regenerate: cd vestad && REGEN_API_FIXTURES=1 cargo test -p vestad api_contract\n\
             // Checked by apps/web/src/lib/api-contract.test.ts against the web's TypeScript types.\n\
             export const vestadApiFixtures = {json} as const;\n"
        );

        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../apps/web/src/lib/vestad-api-fixtures.ts");
        if !path.parent().is_some_and(|dir| dir.exists()) {
            // Standalone vestad checkout without the web app (e.g. release tarball): nothing to check.
            return;
        }

        if std::env::var("REGEN_API_FIXTURES").is_ok() {
            std::fs::write(&path, &content).expect("write fixtures");
            return;
        }

        let committed = std::fs::read_to_string(&path).unwrap_or_default();
        assert_eq!(
            committed,
            content,
            "\n\nAPI contract fixtures are stale.\nRegenerate with:\n  cd vestad && REGEN_API_FIXTURES=1 cargo test -p vestad api_contract\nthen commit {}\n",
            path.display()
        );
    }
}

#[cfg(test)]
mod gateway_settings_tests {
    use super::*;
    use crate::settings::{default_retention, DEFAULT_AUTO_BACKUP_HOUR};

    #[test]
    fn settings_json_has_unified_shape() {
        let settings = Settings::default();
        let value = gateway_settings_json(&settings, "beta");
        assert_eq!(value["auto_update"], serde_json::json!(true));
        assert_eq!(value["channel"], serde_json::json!("beta"));
        assert_eq!(value["auto_backup"]["enabled"], serde_json::json!(true));
        assert_eq!(value["auto_backup"]["hour"], serde_json::json!(DEFAULT_AUTO_BACKUP_HOUR));
        assert_eq!(value["auto_backup"]["retention"]["daily"], serde_json::json!(backup::DEFAULT_RETENTION_DAILY));
    }

    #[test]
    fn backup_update_applies_only_present_fields() {
        let mut backup = BackupGlobalSettings::default();
        let original_hour = backup.hour;
        let body = SetBackupSettingsBody {
            enabled: Some(false),
            hour: None,
            retention: Some(RetentionUpdate { daily: Some(9), weekly: None, monthly: None }),
        };
        apply_backup_update(&mut backup, &body);
        assert!(!backup.enabled, "enabled should be updated");
        assert_eq!(backup.hour, original_hour, "hour absent in body must be unchanged");
        assert_eq!(backup.retention.daily, 9, "daily should be updated");
        assert_eq!(backup.retention.weekly, default_retention().weekly, "weekly absent must be unchanged");
    }

    #[test]
    fn info_json_reports_lan_tunnel_and_port() {
        let exposed = gateway_info_json(
            true,
            &Some("https://192.168.1.4:7777".to_string()),
            &Some("https://x.trycloudflare.com".to_string()),
            7777,
        );
        assert_eq!(exposed["lan"]["exposed"], serde_json::json!(true));
        assert_eq!(exposed["lan"]["url"], serde_json::json!("https://192.168.1.4:7777"));
        assert_eq!(exposed["tunnel_url"], serde_json::json!("https://x.trycloudflare.com"));
        assert_eq!(exposed["port"], serde_json::json!(7777));

        let off = gateway_info_json(false, &None, &None, 7777);
        assert_eq!(off["lan"]["exposed"], serde_json::json!(false));
        assert_eq!(off["lan"]["url"], serde_json::Value::Null);
        assert_eq!(off["tunnel_url"], serde_json::Value::Null);
    }
}

#[cfg(test)]
mod restart_body_tests {
    use super::parse_restart_reason;

    #[test]
    fn tolerates_empty_bodies_and_parses_reason() {
        // Bodyless POSTs (the CLI, the agent's self-restart, curl with a stray JSON header)
        // must keep working — the pre-reason handler accepted them all.
        assert_eq!(parse_restart_reason(b"").unwrap(), None);
        assert_eq!(parse_restart_reason(b"{}").unwrap(), None);
        assert_eq!(parse_restart_reason(br#"{"reason": null}"#).unwrap(), None);
        assert_eq!(
            parse_restart_reason(br#"{"reason": "manual: switching to Claude Opus 4.8"}"#).unwrap(),
            Some("manual: switching to Claude Opus 4.8".to_string())
        );
        assert!(parse_restart_reason(b"not json").is_err());
    }
}

#[cfg(test)]
mod restart_detach_tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::time::Duration;
    use tokio::sync::Notify;

    /// Regression for the nightly-dream restart that stranded the agent: a self-restart's client is
    /// the agent inside the container being stopped, so the request future is dropped mid-operation.
    /// spawn_detached must run the operation to completion regardless — mirroring the drop-cancellation
    /// fix already covered for backup/restore in backup.rs::sse_stream_drop_cancels_container_restart.
    #[tokio::test]
    async fn detached_op_completes_after_request_future_dropped() {
        let completed = Arc::new(AtomicBool::new(false));
        let op_started = Arc::new(Notify::new());
        let op_gate = Arc::new(Notify::new());

        let completed_c = completed.clone();
        let op_started_c = op_started.clone();
        let op_gate_c = op_gate.clone();

        // The request side: spawn_detached spawns the op, then awaits its oneshot result. Drive it on
        // its own task so we can drop it (client disconnect) once the op is in flight.
        let request = tokio::spawn(spawn_detached(async move {
            op_started_c.notify_one();
            // Mirrors the multi-step rebuild in progress (stop -> snapshot -> recreate -> start).
            op_gate_c.notified().await;
            completed_c.store(true, Ordering::SeqCst);
            Ok(ok_json())
        }));

        // Once the op is running, drop the request future — as hyper does when the loopback client dies.
        op_started.notified().await;
        assert!(!completed.load(Ordering::SeqCst), "op should still be in flight");
        request.abort();

        // The detached op must still finish despite the dropped request.
        op_gate.notify_one();
        for _ in 0..200 {
            if completed.load(Ordering::SeqCst) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        assert!(completed.load(Ordering::SeqCst), "detached op must run to completion after request dropped");
    }
}
