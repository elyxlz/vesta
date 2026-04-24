use std::net::Ipv4Addr;
use std::time::Duration;

use axum::{
    body::Body,
    extract::{ws::WebSocketUpgrade, Path, Request, State},
    http::StatusCode,
    response::Response,
    Json,
};
use tokio::net::TcpStream;
use tokio::time::Instant;

use crate::auth;
use crate::docker;
use crate::serve::{ServiceEntry, SharedState, err_response, map_docker_err, PROXY_MAX_BODY_BYTES};

// When a freshly-registered service is still binding its port (e.g. `vite preview`
// takes a couple of seconds), wait briefly for the upstream to start accepting
// connections before proxying. Without this, the first iframe load hits 502 and
// the app caches "unavailable" until a manual refresh. See issue #379.
const UPSTREAM_READY_TIMEOUT: Duration = Duration::from_secs(5);
const UPSTREAM_READY_POLL_INITIAL: Duration = Duration::from_millis(25);
const UPSTREAM_READY_POLL_MAX: Duration = Duration::from_millis(250);

async fn wait_for_upstream(port: u16, timeout: Duration) {
    let deadline = Instant::now() + timeout;
    let mut delay = UPSTREAM_READY_POLL_INITIAL;
    loop {
        if TcpStream::connect((Ipv4Addr::LOCALHOST, port)).await.is_ok() {
            return;
        }
        let now = Instant::now();
        if now >= deadline {
            return;
        }
        let remaining = deadline - now;
        tokio::time::sleep(delay.min(remaining)).await;
        delay = (delay * 2).min(UPSTREAM_READY_POLL_MAX);
    }
}

async fn resolve_service(
    state: &crate::serve::AppState,
    agent_name: &str,
    service_name: &str,
) -> Option<ServiceEntry> {
    let settings = state.settings.read().await;
    settings.services.get(agent_name)?.get(service_name).copied()
}

/// Split the axum-captured `{*path}` tail into `(first_segment, forwarded_subpath)`.
///
/// The axum wildcard strips the leading `/`, so a request for
/// `GET /agents/foo/dashboard/assets/index.js` arrives here with
/// `path = "dashboard/assets/index.js"`. The first segment selects the
/// upstream (registered service, or fallback to the agent). The remainder,
/// with a leading `/` re-added, is the path we forward upstream.
fn split_service_subpath(path: &str) -> (&str, &str) {
    let first = path.split('/').next().unwrap_or("");
    if first.is_empty() {
        return ("", "/");
    }
    let rest = &path[first.len()..];
    if rest.is_empty() { (first, "/") } else { (first, rest) }
}

/// Match `services/{svc}/s/{sid}/{rest...}` → `(svc, sid, /rest)`.
/// Returns `None` if the shape doesn't match. Used to route iframe
/// sub-resource requests authenticated by a session id in the path.
fn split_session_subpath(path: &str) -> Option<(&str, &str, String)> {
    let rest = path.strip_prefix("services/")?;
    let (svc, rest) = rest.split_once('/')?;
    if svc.is_empty() {
        return None;
    }
    let rest = rest.strip_prefix("s/")?;
    let (sid, rest) = match rest.split_once('/') {
        Some((sid, rest)) => (sid, format!("/{}", rest)),
        None => (rest, "/".to_string()),
    };
    if sid.is_empty() {
        return None;
    }
    Some((svc, sid, rest))
}

pub async fn agent_proxy_handler(
    State(state): State<SharedState>,
    Path((name, path)): Path<(String, String)>,
    request: Request,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    use axum::extract::FromRequestParts;

    docker::validate_name(&name).map_err(map_docker_err)?;
    let cname = docker::container_name(&name);

    let lock = state.agent_lock(&name).await;
    let guard = lock.read_owned().await;

    docker::ensure_running(&state.docker, &cname).await.map_err(map_docker_err)?;
    let (agent_port, agent_token) = docker::read_agent_port_and_token(&name, &state.env_config.agents_dir);
    let agent_port = agent_port
        .ok_or_else(|| err_response(StatusCode::INTERNAL_SERVER_ERROR, "agent has no port — check the agent's .env file in ~/.config/vesta/vestad/agents/"))?;

    let (target_port, stripped_path, service, via_session) = if let Some((svc, sid, rest)) =
        split_session_subpath(&path)
    {
        let Some(entry) = resolve_service(&state, &name, svc).await else {
            return Err(err_response(
                StatusCode::NOT_FOUND,
                &format!("service '{}' not registered for agent '{}'", svc, name),
            ));
        };
        let Some((bound_agent, bound_service)) = state.service_sessions.lookup_and_touch(sid).await else {
            return Err(err_response(
                StatusCode::UNAUTHORIZED,
                "session expired or invalid — refresh the parent app",
            ));
        };
        if bound_agent != name || bound_service != svc {
            // Don't leak whether the session exists — treat mismatch as not-found.
            return Err(err_response(
                StatusCode::NOT_FOUND,
                "session does not match agent/service",
            ));
        }
        (entry.port, rest, Some(entry), true)
    } else {
        let (first_segment, service_subpath) = split_service_subpath(&path);
        if first_segment.is_empty() {
            (agent_port, format!("/{}", path), None, false)
        } else if let Some(entry) = resolve_service(&state, &name, first_segment).await {
            (entry.port, service_subpath.to_string(), Some(entry), false)
        } else {
            (agent_port, format!("/{}", path), None, false)
        }
    };

    // Public services are fully open; session-authed requests skip the header
    // check (session id in the path is the auth). Everything else requires a
    // Bearer token or ?token= query param.
    let is_public = service.as_ref().is_some_and(|s| s.public);
    if !via_session
        && !is_public
        && !auth::has_valid_api_auth(request.headers(), request.uri(), &state.api_key)
    {
        return Err(err_response(StatusCode::UNAUTHORIZED, "unauthorized — pass a valid Bearer token or ?token= query parameter"));
    }

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

    // Only wait for registered services — the raw agent port is already running
    // by the time ensure_running() returns, so a wait there would just mask dead agents.
    let is_registered_service = service.is_some();

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
        let ws_token = if is_public { None } else { agent_token.clone() };
        Ok(ws.on_upgrade(move |socket| async move {
            drop(guard);
            if is_registered_service {
                wait_for_upstream(target_port, UPSTREAM_READY_TIMEOUT).await;
            }
            ws_proxy(socket, target_port, &target_path, ws_token.as_deref()).await;
        }))
    } else {
        drop(guard);
        let token = if is_public { None } else { agent_token.as_deref() };
        if is_registered_service {
            wait_for_upstream(target_port, UPSTREAM_READY_TIMEOUT).await;
        }
        forward_http_to_container(&state.http_client, target_port, &target_path, request, token)
            .await
    }
}

async fn ws_proxy(client_ws: axum::extract::ws::WebSocket, agent_port: u16, path: &str, agent_token: Option<&str>) {
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    let url = if let Some(token) = agent_token {
        let sep = if path.contains('?') { "&" } else { "?" };
        format!("ws://localhost:{}{}{}agent_token={}", agent_port, path, sep, token)
    } else {
        format!("ws://localhost:{}{}", agent_port, path)
    };
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
                AxumMsg::Binary(b) => TungMsg::Binary(b),
                AxumMsg::Ping(p) => TungMsg::Ping(p),
                AxumMsg::Pong(p) => TungMsg::Pong(p),
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
                TungMsg::Binary(b) => AxumMsg::Binary(b),
                TungMsg::Ping(p) => AxumMsg::Ping(p),
                TungMsg::Pong(p) => AxumMsg::Pong(p),
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

async fn forward_http_to_container(
    client: &reqwest::Client,
    port: u16,
    target_path: &str,
    request: Request,
    agent_token: Option<&str>,
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
        let n = name.as_str().to_ascii_lowercase();
        if matches!(n.as_str(), "host" | "connection" | "transfer-encoding" | "content-length") {
            continue;
        }
        req_builder = req_builder.header(name.as_str(), value.as_bytes());
    }
    if let Some(token) = agent_token {
        req_builder = req_builder.header("X-Agent-Token", token);
    }
    if !body_bytes.is_empty() {
        req_builder = req_builder.body(body_bytes.to_vec());
    }

    let upstream = req_builder.send().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("container unreachable on port {} ({}): {} — is the service running?", port, target_path, e),
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

#[cfg(test)]
mod tests {
    use super::{split_service_subpath, split_session_subpath, wait_for_upstream};
    use std::net::Ipv4Addr;
    use std::time::Duration;
    use tokio::net::TcpListener;
    use tokio::time::Instant;

    #[test]
    fn forwards_nested_asset_path_to_service() {
        assert_eq!(
            split_service_subpath("dashboard/assets/index-abc.js"),
            ("dashboard", "/assets/index-abc.js"),
        );
    }

    #[test]
    fn forwards_deeply_nested_path_to_service() {
        assert_eq!(
            split_service_subpath("dashboard/a/b/c/d.png"),
            ("dashboard", "/a/b/c/d.png"),
        );
    }

    #[test]
    fn forwards_root_with_trailing_slash_as_root() {
        assert_eq!(split_service_subpath("dashboard/"), ("dashboard", "/"));
    }

    #[test]
    fn forwards_root_without_trailing_slash_as_root() {
        assert_eq!(split_service_subpath("dashboard"), ("dashboard", "/"));
    }

    #[test]
    fn empty_path_yields_empty_segment() {
        assert_eq!(split_service_subpath(""), ("", "/"));
    }

    #[test]
    fn session_subpath_parses_nested_asset() {
        assert_eq!(
            split_session_subpath("services/dashboard/s/abc123/assets/index.js"),
            Some(("dashboard", "abc123", "/assets/index.js".to_string())),
        );
    }

    #[test]
    fn session_subpath_parses_root_with_trailing_slash() {
        assert_eq!(
            split_session_subpath("services/dashboard/s/abc123/"),
            Some(("dashboard", "abc123", "/".to_string())),
        );
    }

    #[test]
    fn session_subpath_parses_root_without_trailing_slash() {
        assert_eq!(
            split_session_subpath("services/dashboard/s/abc123"),
            Some(("dashboard", "abc123", "/".to_string())),
        );
    }

    #[test]
    fn session_subpath_rejects_non_services_prefix() {
        assert_eq!(split_session_subpath("dashboard/assets/x.js"), None);
        assert_eq!(split_session_subpath(""), None);
    }

    #[test]
    fn session_subpath_rejects_missing_s_segment() {
        assert_eq!(split_session_subpath("services/dashboard/x/abc/index.js"), None);
        assert_eq!(split_session_subpath("services/dashboard/"), None);
    }

    #[test]
    fn session_subpath_rejects_empty_session_id() {
        assert_eq!(split_session_subpath("services/dashboard/s//index.js"), None);
        assert_eq!(split_session_subpath("services/dashboard/s/"), None);
    }

    #[test]
    fn session_subpath_rejects_empty_service_name() {
        assert_eq!(split_session_subpath("services//s/abc/index.js"), None);
    }

    #[tokio::test]
    async fn wait_returns_immediately_when_port_is_listening() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let port = listener.local_addr().unwrap().port();

        let start = Instant::now();
        wait_for_upstream(port, Duration::from_secs(5)).await;
        assert!(start.elapsed() < Duration::from_millis(100));
    }

    #[tokio::test]
    async fn wait_returns_after_timeout_when_port_never_binds() {
        // Reserve a port by binding+dropping, so nothing is listening there now.
        let port = {
            let tmp = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
            tmp.local_addr().unwrap().port()
        };

        let start = Instant::now();
        wait_for_upstream(port, Duration::from_millis(300)).await;
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(300));
        assert!(elapsed < Duration::from_millis(1200));
    }

    #[tokio::test]
    async fn wait_returns_once_port_starts_listening_mid_wait() {
        let port = {
            let tmp = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
            tmp.local_addr().unwrap().port()
        };

        let binder = tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(150)).await;
            TcpListener::bind((Ipv4Addr::LOCALHOST, port)).await.unwrap()
        });

        let start = Instant::now();
        wait_for_upstream(port, Duration::from_secs(5)).await;
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(150));
        assert!(elapsed < Duration::from_millis(800));

        drop(binder.await.unwrap());
    }
}
