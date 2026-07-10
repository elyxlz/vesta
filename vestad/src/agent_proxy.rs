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
use crate::serve::{
    err_response, map_docker_err, ServiceEntry, SharedState, PROXY_MAX_BODY_BYTES,
    WS_KEEPALIVE_INTERVAL_SECS,
};

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
        if TcpStream::connect((Ipv4Addr::LOCALHOST, port))
            .await
            .is_ok()
        {
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
    settings
        .services
        .get(agent_name)?
        .get(service_name)
        .copied()
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
    if rest.is_empty() {
        (first, "/")
    } else {
        (first, rest)
    }
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

    docker::ensure_running(&state.docker, &cname)
        .await
        .map_err(map_docker_err)?;
    let (agent_port, agent_token) =
        docker::read_agent_port_and_token(&name, &state.env_config.agents_dir);
    let agent_port = agent_port.ok_or_else(|| {
        err_response(
            StatusCode::INTERNAL_SERVER_ERROR,
            "agent has no port — check the agent's .env file in ~/.config/vesta/vestad/agents/",
        )
    })?;

    let (first_segment, service_subpath) = split_service_subpath(&path);
    let resolved = if first_segment.is_empty() {
        None
    } else {
        resolve_service(&state, &name, first_segment).await
    };
    let (target_port, stripped_path, service) = match resolved {
        Some(entry) => (entry.port, service_subpath.to_string(), Some(entry)),
        None => (agent_port, format!("/{}", path), None),
    };

    // Public services are fully open; everything else requires auth.
    let is_public = service.as_ref().is_some_and(|s| s.public);
    if !is_public && !auth::has_valid_api_auth(request.headers(), request.uri(), &state.api_key) {
        return Err(err_response(
            StatusCode::UNAUTHORIZED,
            "unauthorized — pass a valid Bearer token or ?token= query parameter",
        ));
    }

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
        let token = if is_public {
            None
        } else {
            agent_token.as_deref()
        };
        if is_registered_service {
            wait_for_upstream(target_port, UPSTREAM_READY_TIMEOUT).await;
        }
        forward_http_to_container(
            &state.http_client,
            target_port,
            &target_path,
            request,
            token,
        )
        .await
    }
}

async fn ws_proxy(
    client_ws: axum::extract::ws::WebSocket,
    agent_port: u16,
    path: &str,
    agent_token: Option<&str>,
) {
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    let url = if let Some(token) = agent_token {
        let sep = if path.contains('?') { "&" } else { "?" };
        format!(
            "ws://localhost:{}{}{}agent_token={}",
            agent_port, path, sep, token
        )
    } else {
        format!("ws://localhost:{}{}", agent_port, path)
    };
    let agent_ws = match tokio_tungstenite::connect_async(&url).await {
        Ok((ws, _)) => ws,
        Err(e) => {
            tracing::warn!(port = agent_port, error = %e, "agent websocket not reachable");
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

    let (client_tx, mut client_rx) = client_ws.split();
    let (mut agent_tx, agent_rx) = agent_ws.split();

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

    let keepalive = Duration::from_secs(WS_KEEPALIVE_INTERVAL_SECS);
    tokio::select! {
        _ = client_to_agent => {},
        _ = pump_agent_to_client(client_tx, agent_rx, keepalive) => {},
    }

    tracing::info!(port = agent_port, "client websocket disconnected");
}

/// Forward agent frames to the client, and ping the client every `keepalive` when otherwise
/// idle so the Cloudflare tunnel never sees the socket as idle and reaps it (~100s window).
/// Only the client hop is tunneled, so only it needs keepalive; the agent hop is local.
/// Returns when the agent stream ends/closes or the client send fails. Generic over the
/// sink/stream so it can be exercised in-process with in-memory streams (see tests).
async fn pump_agent_to_client<ClientSink, AgentStream, AgentErr>(
    mut client_tx: ClientSink,
    mut agent_rx: AgentStream,
    keepalive: Duration,
) where
    ClientSink: futures_util::Sink<axum::extract::ws::Message> + Unpin,
    AgentStream: futures_util::Stream<Item = Result<tokio_tungstenite::tungstenite::Message, AgentErr>>
        + Unpin,
{
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    let mut ticker = tokio::time::interval(keepalive);
    ticker.tick().await; // the first tick is immediate; drop it so the first ping waits a full interval

    loop {
        tokio::select! {
            agent_msg = agent_rx.next() => {
                let Some(Ok(msg)) = agent_msg else { break };
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
            _ = ticker.tick() => {
                if client_tx.send(AxumMsg::Ping(Default::default())).await.is_err() {
                    break;
                }
            }
        }
    }
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
        if matches!(
            n.as_str(),
            "host" | "connection" | "transfer-encoding" | "content-length"
        ) {
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
            &format!(
                "container unreachable on port {} ({}): {} — is the service running?",
                port, target_path, e
            ),
        )
    })?;

    let status =
        StatusCode::from_u16(upstream.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let mut builder = Response::builder().status(status);
    for (name, value) in upstream.headers().iter() {
        let n = name.as_str().to_ascii_lowercase();
        if matches!(
            n.as_str(),
            "transfer-encoding" | "connection" | "content-length"
        ) {
            continue;
        }
        builder = builder.header(name.as_str(), value.as_bytes());
    }

    let stream = upstream.bytes_stream();
    let body = Body::from_stream(stream);
    builder.body(body).map_err(|e| {
        err_response(
            StatusCode::INTERNAL_SERVER_ERROR,
            &format!("build response: {}", e),
        )
    })
}

#[cfg(test)]
mod tests {
    use super::{pump_agent_to_client, split_service_subpath, wait_for_upstream};
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::stream;
    use std::convert::Infallible;
    use std::net::Ipv4Addr;
    use std::time::Duration;
    use tokio::net::TcpListener;
    use tokio::time::Instant;
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    /// A `Sink<AxumMsg>` that records every frame to an unbounded channel, so a test can
    /// observe exactly what the pump sent to the client.
    fn recording_client_sink() -> (
        impl futures_util::Sink<AxumMsg, Error = ()> + Unpin,
        tokio::sync::mpsc::UnboundedReceiver<AxumMsg>,
    ) {
        let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
        let sink = futures_util::sink::unfold(tx, |tx, msg: AxumMsg| async move {
            tx.send(msg).map_err(|_| ())?;
            Ok(tx)
        });
        (Box::pin(sink), rx)
    }

    #[tokio::test]
    async fn idle_connection_pings_the_client_every_interval() {
        let (sink, mut rx) = recording_client_sink();
        // Agent never speaks: the only frames the client can receive are keepalive pings.
        let agent_rx = stream::pending::<Result<TungMsg, Infallible>>();

        let keepalive = Duration::from_millis(100);
        let pump = tokio::spawn(pump_agent_to_client(sink, agent_rx, keepalive));

        let start = Instant::now();
        let first = rx.recv().await.expect("first keepalive ping");
        let second = rx.recv().await.expect("second keepalive ping");
        assert!(
            matches!(first, AxumMsg::Ping(_)),
            "expected a ping, got {first:?}"
        );
        assert!(
            matches!(second, AxumMsg::Ping(_)),
            "expected a ping, got {second:?}"
        );
        // First ping waits a full interval (the immediate tick is dropped), two pings ~= 2 intervals.
        let elapsed = start.elapsed();
        assert!(
            elapsed >= keepalive,
            "first ping fired too early: {elapsed:?}"
        );
        assert!(elapsed < keepalive * 6, "pings too slow: {elapsed:?}");

        pump.abort();
    }

    #[tokio::test]
    async fn agent_close_ends_the_pump() {
        let (sink, mut rx) = recording_client_sink();
        let agent_rx = stream::iter([Ok::<_, Infallible>(TungMsg::Close(None))]);

        // A long keepalive guarantees the pump returns because of the Close, not a tick.
        pump_agent_to_client(sink, agent_rx, Duration::from_secs(3600)).await;

        // The Close is consumed (not forwarded) and the pump has returned, so the channel is empty/closed.
        assert!(
            rx.try_recv().is_err(),
            "Close frame should not be forwarded to the client"
        );
    }

    #[tokio::test]
    async fn agent_text_is_forwarded_to_the_client() {
        let (sink, mut rx) = recording_client_sink();
        let agent_rx = stream::iter([Ok::<_, Infallible>(TungMsg::Text("hello".into()))]);

        pump_agent_to_client(sink, agent_rx, Duration::from_secs(3600)).await;

        let forwarded = rx.try_recv().expect("text frame forwarded");
        assert!(
            matches!(forwarded, AxumMsg::Text(ref t) if t.as_str() == "hello"),
            "got {forwarded:?}"
        );
    }

    #[test]
    fn splits_service_name_from_forwarded_subpath() {
        // (path, expected service, expected subpath)
        let cases = [
            (
                "dashboard/assets/index-abc.js",
                ("dashboard", "/assets/index-abc.js"),
            ),
            ("dashboard/a/b/c/d.png", ("dashboard", "/a/b/c/d.png")),
            ("dashboard/", ("dashboard", "/")),
            ("dashboard", ("dashboard", "/")),
            ("", ("", "/")),
        ];
        for (path, expected) in cases {
            assert_eq!(
                split_service_subpath(path),
                expected,
                "split_service_subpath({path:?})"
            );
        }
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
            TcpListener::bind((Ipv4Addr::LOCALHOST, port))
                .await
                .unwrap()
        });

        let start = Instant::now();
        wait_for_upstream(port, Duration::from_secs(5)).await;
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(150));
        assert!(elapsed < Duration::from_millis(800));

        drop(binder.await.unwrap());
    }
}
