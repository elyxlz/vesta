use axum::{
    body::Body,
    extract::{ws::WebSocketUpgrade, Path, Request, State},
    http::StatusCode,
    response::Response,
    Json,
};

use crate::auth::verify_token;
use crate::docker;
use crate::serve::{SharedState, err_response, map_docker_err, PROXY_MAX_BODY_BYTES};

fn check_request_auth(request: &Request, api_key: &str) -> bool {
    let bearer_ok = request
        .headers()
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|token: &str| verify_token(token, api_key))
        .unwrap_or(false);
    if bearer_ok {
        return true;
    }
    request
        .uri()
        .query()
        .and_then(|q: &str| q.split('&').find_map(|p: &str| p.strip_prefix("token=")))
        .map(|t: &str| verify_token(t, api_key))
        .unwrap_or(false)
}

async fn resolve_service_port(
    state: &crate::serve::AppState,
    agent_name: &str,
    service_name: &str,
) -> Option<u16> {
    let settings = state.settings.read().await;
    settings.services.get(agent_name)?.get(service_name).copied()
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

    let first_segment = path.split('/').next().unwrap_or("");
    let (target_port, stripped_path, is_service) = if !first_segment.is_empty() {
        if let Some(service_port) = resolve_service_port(&state, &name, first_segment).await {
            let rest = &path[first_segment.len()..];
            let rest = if rest.is_empty() { "/" } else { rest };
            (service_port, rest.to_string(), true)
        } else {
            (agent_port, format!("/{}", path), false)
        }
    } else {
        (agent_port, format!("/{}", path), false)
    };

    // Service requests are unauthenticated (assets load freely in iframes).
    // Non-service requests require auth.
    if !is_service && !check_request_auth(&request, &state.api_key) {
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
        let ws_token = agent_token.clone();
        Ok(ws.on_upgrade(move |socket| async move {
            drop(guard);
            ws_proxy(socket, target_port, &target_path, ws_token.as_deref()).await;
        }))
    } else {
        drop(guard);
        let is_service_root = is_service
            && path.strip_suffix('/').unwrap_or(&path) == first_segment;
        let token = if is_service_root {
            crate::service_proxy::extract_token(request.uri())
        } else {
            None
        };
        let resp =
            forward_http_to_container(&state.http_client, target_port, &target_path, request, agent_token.as_deref())
                .await?;
        match token {
            Some(token) => crate::service_proxy::rewrite_asset_urls(resp, &token).await,
            None => Ok(resp),
        }
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
                AxumMsg::Binary(b) => TungMsg::Binary(b.into()),
                AxumMsg::Ping(p) => TungMsg::Ping(p.into()),
                AxumMsg::Pong(p) => TungMsg::Pong(p.into()),
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
                TungMsg::Binary(b) => AxumMsg::Binary(b.into()),
                TungMsg::Ping(p) => AxumMsg::Ping(p.into()),
                TungMsg::Pong(p) => AxumMsg::Pong(p.into()),
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
