use std::time::Duration;

use axum::{
    body::Body,
    extract::{ws::WebSocketUpgrade, Path, Request, State},
    http::StatusCode,
    response::Response,
    Json,
};
use tokio::time::Instant;

use crate::auth;
use crate::docker;
use crate::settings::ServiceEntry;
use crate::state::{
    err_response, map_docker_err, SharedState, PROXY_MAX_BODY_BYTES, WS_KEEPALIVE_INTERVAL_SECS,
};

// When a freshly-registered service is still binding its port (e.g. `vite preview`
// takes a couple of seconds), retry a refused connect within this window instead of
// failing the request. Without this, the first iframe load hits 502 and the app
// caches "unavailable" until a manual refresh. See issue #379. A healthy service
// costs no probe: the real request is the only connect made.
const UPSTREAM_READY_TIMEOUT: Duration = Duration::from_secs(5);
const UPSTREAM_READY_POLL_INITIAL: Duration = Duration::from_millis(25);
const UPSTREAM_READY_POLL_MAX: Duration = Duration::from_millis(250);

/// Send the request, retrying connection failures within the bind-grace window when `grace`
/// (registered services only; the raw agent port is up whenever its container is). The last
/// error is handed back for diagnosis.
async fn send_with_bind_grace(
    req_builder: reqwest::RequestBuilder,
    grace: bool,
    timeout: Duration,
) -> Result<reqwest::Response, reqwest::Error> {
    let deadline = Instant::now() + timeout;
    let mut delay = UPSTREAM_READY_POLL_INITIAL;
    loop {
        let result = match req_builder.try_clone() {
            Some(attempt) => attempt.send().await,
            // A non-clonable (streaming) body cannot retry; send it once.
            None => return req_builder.send().await,
        };
        match result {
            Ok(response) => return Ok(response),
            Err(error) => {
                let now = Instant::now();
                if !(grace && error.is_connect() && now < deadline) {
                    return Err(error);
                }
                tokio::time::sleep(delay.min(deadline - now)).await;
                delay = (delay * 2).min(UPSTREAM_READY_POLL_MAX);
            }
        }
    }
}

/// Dial a registered service's upstream socket, retrying io-level failures within the
/// bind-grace window, the socket counterpart of `send_with_bind_grace`.
async fn dial_upstream_ws(
    url: &str,
    timeout: Duration,
) -> Result<
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
    tokio_tungstenite::tungstenite::Error,
> {
    let deadline = Instant::now() + timeout;
    let mut delay = UPSTREAM_READY_POLL_INITIAL;
    loop {
        match tokio_tungstenite::connect_async(url).await {
            Ok((ws, _)) => return Ok(ws),
            Err(error) => {
                let now = Instant::now();
                let retryable = matches!(error, tokio_tungstenite::tungstenite::Error::Io(_));
                if !retryable || now >= deadline {
                    return Err(error);
                }
                tokio::time::sleep(delay.min(deadline - now)).await;
                delay = (delay * 2).min(UPSTREAM_READY_POLL_MAX);
            }
        }
    }
}

/// Build the URL the proxy dials: `host` is the agent's own address on its bridge network.
fn build_target_url(scheme: &str, host: &str, port: u16, path: &str) -> String {
    format!("{scheme}://{host}:{port}{path}")
}

pub(crate) async fn resolve_service(
    state: &crate::state::AppState,
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

/// Split a `/k/{key}/...` service subpath into its key and the path forwarded upstream.
/// A path prefix is the only carrier a relative sub-resource inherits, which is how an
/// iframe's assets authenticate without headers or a query string.
fn split_key_subpath(subpath: &str) -> Option<(&str, String)> {
    let rest = subpath.strip_prefix("/k/")?;
    let (key, tail) = match rest.split_once('/') {
        Some((key, tail)) => (key, format!("/{tail}")),
        None => (rest, "/".to_string()),
    };
    if key.is_empty() {
        return None;
    }
    Some((key, tail))
}

/// The path forwarded upstream for a keyed request, or `None` when the subpath carries no
/// key prefix or one that does not open this service. A wrong key never reshapes the
/// forwarded path: the caller keeps the original subpath and falls through to normal auth.
fn keyed_forward_path(
    subpath: &str,
    keys: &crate::service_keys::ServiceKeyStore,
    agent: &str,
    service: &str,
    now: u64,
) -> Option<String> {
    let (key, forwarded) = split_key_subpath(subpath)?;
    keys.accepts(agent, service, key, now).then_some(forwarded)
}

/// The query string forwarded upstream: the client's query minus every `token=` pair
/// (`auth::presented_tokens` reads that carrier, so vestad has already consumed it and no
/// upstream may see it). `None` when nothing else remains, so the URL carries no stray `?`.
fn forwarded_query(query: &str) -> Option<String> {
    let kept = query
        .split('&')
        .filter(|pair| !pair.is_empty() && !pair.starts_with(auth::CLIENT_CREDENTIAL_QUERY_PREFIX))
        .collect::<Vec<_>>()
        .join("&");
    (!kept.is_empty()).then_some(kept)
}

/// The agent token vestad injects upstream. Only the raw agent port consumes it, so a
/// registered service is never handed one.
fn injected_agent_token(agent_token: Option<&str>, is_registered_service: bool) -> Option<&str> {
    if is_registered_service {
        None
    } else {
        agent_token
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

    let (agent_port, agent_token) =
        docker::read_agent_port_and_token_async(&name, &state.env_config.agents_dir).await;
    let agent_port = agent_port.ok_or_else(|| {
        err_response(
            StatusCode::INTERNAL_SERVER_ERROR,
            "agent has no port — check the agent's .env file in ~/.config/vesta/vestad/agents/",
        )
    })?;
    // The agent answers on its own bridge network (see AgentStatusCache::bridge_ip_or_resolve).
    // The happy path is a cache hit; only the miss asks Docker, and only then whether the
    // container itself explains the unresolved address.
    let Some(target_host) = state
        .agent_status_cache
        .bridge_ip_or_resolve(&state.docker, &cname, &name)
        .await
    else {
        return Err(match docker::ensure_running(&state.docker, &cname).await {
            Err(docker_error) => map_docker_err(docker_error),
            Ok(()) => err_response(
                StatusCode::SERVICE_UNAVAILABLE,
                "agent's network address not yet resolved -- retry shortly",
            ),
        });
    };

    let (first_segment, service_subpath) = split_service_subpath(&path);
    let resolved = if first_segment.is_empty() {
        None
    } else {
        resolve_service(&state, &name, first_segment).await
    };

    // A `/k/{key}/` prefix is stripped only when the key actually opens this service, so a
    // wrong key can never reshape the forwarded path: it falls through to normal auth. The
    // key store is only consulted when a prefix is present, keeping the common prefix-less
    // request off its lock.
    let keyed_subpath = if resolved.is_some() && split_key_subpath(service_subpath).is_some() {
        let now = crate::time_utils::now_epoch_secs();
        let keys = state.service_keys.read().await;
        keyed_forward_path(service_subpath, &keys, &name, first_segment, now)
    } else {
        None
    };
    let via_key = keyed_subpath.is_some();

    let (target_port, stripped_path, service) = match resolved {
        Some(entry) => (
            entry.port,
            keyed_subpath.unwrap_or_else(|| service_subpath.to_string()),
            Some(entry),
        ),
        None => (agent_port, format!("/{path}"), None),
    };

    if !via_key
        && !auth::proxy_authorized(
            &state,
            request.headers(),
            request.uri(),
            &name,
            first_segment,
            service.as_ref(),
        )
        .await
    {
        return Err(err_response(
            StatusCode::UNAUTHORIZED,
            "unauthorized — pass a valid Bearer token, ?token= query parameter, or /k/{key}/ path prefix",
        ));
    }

    // Both the HTTP and WS branches forward this path, so the credential strip covers both.
    let mut target_path = stripped_path;
    if let Some(query) = request.uri().query().and_then(forwarded_query) {
        target_path.push('?');
        target_path.push_str(&query);
    }

    let is_ws_upgrade = request
        .headers()
        .get("upgrade")
        .is_some_and(|v| v.as_bytes().eq_ignore_ascii_case(b"websocket"));

    // Bind grace applies to registered services only — the raw agent port is up whenever
    // its container is, so a retry there would just mask dead agents.
    let is_registered_service = service.is_some();

    if is_ws_upgrade {
        // The raw agent port carries the internal event bus, which is not client-exposed.
        // Only registered-service WS (voice STT, dashboard-registered services) may upgrade.
        if service.is_none() {
            return Err(err_response(
                StatusCode::NOT_FOUND,
                "the raw agent event bus is not client-exposed; use /sync",
            ));
        }
        // One inspect per socket connect, amortized over the socket's life: a stopped agent
        // must refuse the handshake rather than accept the upgrade and immediately close.
        docker::ensure_running(&state.docker, &cname)
            .await
            .map_err(map_docker_err)?;
        let (mut parts, _body) = request.into_parts();
        let ws = match WebSocketUpgrade::from_request_parts(&mut parts, &state).await {
            Ok(ws) => ws,
            Err(e) => {
                return Err(err_response(
                    StatusCode::BAD_REQUEST,
                    &format!("invalid ws upgrade: {e}"),
                ));
            }
        };
        Ok(ws.on_upgrade(move |socket| async move {
            drop(guard);
            ws_proxy(socket, &target_host, target_port, &target_path).await;
        }))
    } else {
        drop(guard);
        let token = injected_agent_token(agent_token.as_deref(), is_registered_service);
        forward_http_to_container(
            &state,
            &cname,
            UpstreamTarget {
                host: &target_host,
                port: target_port,
                path: &target_path,
            },
            request,
            token,
            is_registered_service,
        )
        .await
    }
}

/// The upstream address a forward dials: the agent's bridge-network host plus the resolved
/// service (or raw agent) port and the credential-stripped path.
struct UpstreamTarget<'a> {
    host: &'a str,
    port: u16,
    path: &'a str,
}

/// Bridge a client socket to a registered service's upstream. Only registered services reach
/// here (the raw agent port 404s on upgrade), so the socket carries no injected credential.
async fn ws_proxy(
    client_ws: axum::extract::ws::WebSocket,
    host: &str,
    agent_port: u16,
    path: &str,
) {
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    let url = build_target_url("ws", host, agent_port, path);
    let agent_ws = match dial_upstream_ws(&url, UPSTREAM_READY_TIMEOUT).await {
        Ok(ws) => ws,
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
        () = client_to_agent => {},
        () = pump_agent_to_client(client_tx, agent_rx, keepalive) => {},
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
                    TungMsg::Frame(_) => continue,
                };
                if client_tx.send(axum_msg).await.is_err() {
                    break;
                }
            }
            _ = ticker.tick() => {
                if client_tx.send(AxumMsg::Ping(bytes::Bytes::new())).await.is_err() {
                    break;
                }
            }
        }
    }
}

async fn forward_http_to_container(
    state: &crate::state::AppState,
    cname: &str,
    target: UpstreamTarget<'_>,
    request: Request,
    agent_token: Option<&str>,
    bind_grace: bool,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    let (parts, body) = request.into_parts();
    let url = build_target_url("http", target.host, target.port, target.path);

    let method = reqwest::Method::from_bytes(parts.method.as_str().as_bytes())
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &format!("bad method: {e}")))?;

    let body_bytes = axum::body::to_bytes(body, PROXY_MAX_BODY_BYTES)
        .await
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &format!("read body: {e}")))?;

    // Hop-by-hop headers, plus the client credential vestad already consumed
    // (auth::presented_tokens): the proxy is the gate, so no upstream, registered
    // service or raw agent port alike, is handed the gateway-tier bearer.
    let mut req_builder = state.http_client.request(method, &url);
    for (name, value) in &parts.headers {
        let n = name.as_str().to_ascii_lowercase();
        if matches!(
            n.as_str(),
            "host" | "connection" | "transfer-encoding" | "content-length"
        ) || n == auth::CLIENT_CREDENTIAL_HEADER
        {
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

    let upstream = match send_with_bind_grace(req_builder, bind_grace, UPSTREAM_READY_TIMEOUT).await
    {
        Ok(upstream) => upstream,
        Err(send_error) => {
            // Ask Docker only on the failure path: a missing or stopped container explains an
            // unreachable upstream better than the transport error, and the happy path pays
            // no inspect.
            return Err(match docker::ensure_running(&state.docker, cname).await {
                Err(docker_error) => map_docker_err(docker_error),
                Ok(()) => err_response(
                    StatusCode::BAD_GATEWAY,
                    &format!(
                        "container unreachable on port {port} ({target_path}): {send_error} — is the service running?",
                        port = target.port,
                        target_path = target.path,
                    ),
                ),
            });
        }
    };

    let status =
        StatusCode::from_u16(upstream.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let mut builder = Response::builder().status(status);
    for (name, value) in upstream.headers() {
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
            &format!("build response: {e}"),
        )
    })
}

/// The join between the path carrier and the key check. The rule each row pins is that a
/// prefix is stripped only when the key opens this exact service, so a wrong key leaves the
/// forwarded path untouched instead of reshaping it.
#[cfg(test)]
mod keyed_forward_path_tests {
    use super::keyed_forward_path;
    use crate::service_keys::ServiceKeyStore;

    const NOW: u64 = 1_800_000_000;
    const AGENT: &str = "alpha";
    const SERVICE: &str = "dashboard";

    /// A store holding one live key for `(alpha, dashboard)`, plus that key's secret.
    fn store_with_live_key() -> (ServiceKeyStore, String) {
        let mut keys = ServiceKeyStore::default();
        let (_, secret) = keys.mint(AGENT, SERVICE, None, Some(NOW + 600), NOW);
        (keys, secret)
    }

    /// The forwarded path for a request to `(alpha, dashboard)`.
    fn forwarded(subpath: &str, keys: &ServiceKeyStore) -> Option<String> {
        keyed_forward_path(subpath, keys, AGENT, SERVICE, NOW)
    }

    #[test]
    fn a_valid_key_strips_the_prefix_from_the_forwarded_path() {
        let (keys, secret) = store_with_live_key();
        assert_eq!(
            forwarded(&format!("/k/{secret}/assets/index.js"), &keys),
            Some("/assets/index.js".to_string())
        );
    }

    #[test]
    fn a_valid_key_on_the_bare_form_forwards_the_root() {
        let (keys, secret) = store_with_live_key();
        assert_eq!(forwarded(&format!("/k/{secret}/"), &keys), Some("/".to_string()));
    }

    /// The rule this whole seam exists for: the caller must keep the original subpath
    /// verbatim and fall through to normal auth, never forward a reshaped path.
    #[test]
    fn a_wrong_key_yields_nothing_so_the_original_subpath_survives() {
        let (keys, _) = store_with_live_key();
        assert_eq!(forwarded("/k/not-the-secret/assets/index.js", &keys), None);
    }

    #[test]
    fn an_expired_key_yields_nothing() {
        let mut keys = ServiceKeyStore::default();
        let (_, secret) = keys.mint(AGENT, SERVICE, None, Some(NOW - 1), NOW);
        assert_eq!(forwarded(&format!("/k/{secret}/assets/index.js"), &keys), None);
    }

    #[test]
    fn a_key_for_another_service_yields_nothing() {
        let mut keys = ServiceKeyStore::default();
        let (_, secret) = keys.mint(AGENT, "voice", None, Some(NOW + 600), NOW);
        assert_eq!(forwarded(&format!("/k/{secret}/assets/index.js"), &keys), None);
    }

    #[test]
    fn a_key_for_another_agent_yields_nothing() {
        let mut keys = ServiceKeyStore::default();
        let (_, secret) = keys.mint("beta", SERVICE, None, Some(NOW + 600), NOW);
        assert_eq!(forwarded(&format!("/k/{secret}/assets/index.js"), &keys), None);
    }

    /// No `/k/` prefix means the store is never consulted, so even a live secret sitting
    /// elsewhere in the path buys nothing.
    #[test]
    fn a_subpath_without_the_key_prefix_yields_nothing() {
        let (keys, secret) = store_with_live_key();
        assert_eq!(forwarded("/assets/index.js", &keys), None);
        assert_eq!(forwarded(&format!("/assets/{secret}.js"), &keys), None);
        assert_eq!(forwarded(&format!("/k2/{secret}/assets/index.js"), &keys), None);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        build_target_url, dial_upstream_ws, forwarded_query, injected_agent_token,
        pump_agent_to_client, send_with_bind_grace, split_key_subpath, split_service_subpath,
    };
    use axum::extract::ws::Message as AxumMsg;
    use futures_util::stream;
    use std::convert::Infallible;
    use std::net::Ipv4Addr;
    use std::time::Duration;
    use tokio::net::TcpListener;
    use tokio::time::Instant;
    use tokio_tungstenite::tungstenite::Message as TungMsg;

    #[test]
    fn only_the_raw_agent_port_receives_the_injected_agent_token() {
        // The agent's own API is the one consumer of X-Agent-Token
        // (agent/core/api.py), and it lives on the raw agent port. A registered
        // service is reached only through this proxy, so it needs no credential of
        // its own and must not be handed a gateway-tier one.
        assert_eq!(injected_agent_token(Some("tok"), true), None);
        assert_eq!(injected_agent_token(Some("tok"), false), Some("tok"));
        assert_eq!(injected_agent_token(None, false), None);
        assert_eq!(injected_agent_token(None, true), None);
    }

    /// The `?token=` pair is the query carrier `auth::presented_tokens` consumes, so the
    /// forwarded query must never contain one, while every other pair passes untouched.
    /// Both the HTTP forward and the WS upstream dial use the path this filter produces.
    #[test]
    fn the_forwarded_query_drops_every_token_pair_and_keeps_the_rest() {
        // (client query, query forwarded upstream)
        let cases = [
            ("token=secret", None),
            ("token=secret&lang=en", Some("lang=en")),
            ("lang=en&token=secret&fmt=json", Some("lang=en&fmt=json")),
            ("token=one&token=two", None),
            ("lang=en", Some("lang=en")),
            // `tokens=` is a different name; only the exact `token=` carrier is a credential.
            ("tokens=plural&mytoken=x", Some("tokens=plural&mytoken=x")),
            ("", None),
        ];
        for (query, expected) in cases {
            assert_eq!(
                forwarded_query(query).as_deref(),
                expected,
                "forwarded_query({query:?})"
            );
        }
    }

    #[test]
    fn build_target_url_uses_the_given_host_not_localhost() {
        assert_eq!(
            build_target_url("http", "172.20.0.5", 8080, "/health"),
            "http://172.20.0.5:8080/health"
        );
        assert_eq!(
            build_target_url("ws", "172.20.0.5", 8080, "/voice/stt?lang=en"),
            "ws://172.20.0.5:8080/voice/stt?lang=en"
        );
    }

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
        pump_agent_to_client(sink, agent_rx, Duration::from_hours(1)).await;

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

        pump_agent_to_client(sink, agent_rx, Duration::from_hours(1)).await;

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

    #[test]
    fn splits_the_key_prefix_from_the_forwarded_subpath() {
        assert_eq!(
            split_key_subpath("/k/abc123/assets/index.js"),
            Some(("abc123", "/assets/index.js".to_string()))
        );
        assert_eq!(split_key_subpath("/k/abc123/"), Some(("abc123", "/".to_string())));
        assert_eq!(split_key_subpath("/k/abc123"), Some(("abc123", "/".to_string())));
    }

    #[test]
    fn rejects_a_missing_or_empty_key_prefix() {
        assert_eq!(split_key_subpath("/assets/index.js"), None);
        assert_eq!(split_key_subpath("/"), None);
        assert_eq!(split_key_subpath("/k/"), None);
        assert_eq!(split_key_subpath("/k//assets/index.js"), None);
    }

    /// Reserve a port by binding+dropping, so nothing is listening there now.
    async fn free_port() -> u16 {
        let tmp = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        tmp.local_addr().unwrap().port()
    }

    /// Accept one connection and answer any bytes with an empty 200, the smallest
    /// upstream a real `send` can complete against.
    async fn serve_one_http_200(listener: TcpListener) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        if let Ok((mut socket, _)) = listener.accept().await {
            let mut buf = [0u8; 1024];
            let _ = socket.read(&mut buf).await;
            let _ = socket
                .write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n")
                .await;
        }
    }

    fn get_builder(port: u16) -> reqwest::RequestBuilder {
        reqwest::Client::new().get(format!("http://127.0.0.1:{port}/"))
    }

    #[tokio::test]
    async fn a_live_upstream_serves_the_first_send_with_no_probe_delay() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(serve_one_http_200(listener));

        let start = Instant::now();
        let response = send_with_bind_grace(get_builder(port), true, Duration::from_secs(5))
            .await
            .expect("send succeeds");
        assert_eq!(response.status(), 200);
        assert!(start.elapsed() < Duration::from_millis(300));
    }

    #[tokio::test]
    async fn bind_grace_retries_until_a_late_binding_service_answers() {
        let port = free_port().await;
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(150)).await;
            let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, port)).await.unwrap();
            serve_one_http_200(listener).await;
        });

        let start = Instant::now();
        let response = send_with_bind_grace(get_builder(port), true, Duration::from_secs(5))
            .await
            .expect("send succeeds once the port binds");
        assert_eq!(response.status(), 200);
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(150));
        assert!(elapsed < Duration::from_millis(1500));
    }

    #[tokio::test]
    async fn without_grace_a_refused_connect_fails_immediately() {
        let port = free_port().await;

        let start = Instant::now();
        let error = send_with_bind_grace(get_builder(port), false, Duration::from_secs(5))
            .await
            .expect_err("dead port refuses");
        assert!(error.is_connect());
        assert!(start.elapsed() < Duration::from_millis(300));
    }

    #[tokio::test]
    async fn bind_grace_gives_up_at_the_deadline() {
        let port = free_port().await;

        let start = Instant::now();
        let error = send_with_bind_grace(get_builder(port), true, Duration::from_millis(300))
            .await
            .expect_err("port never binds");
        assert!(error.is_connect());
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(300));
        assert!(elapsed < Duration::from_millis(1500));
    }

    #[tokio::test]
    async fn ws_dial_retries_until_a_late_binding_service_accepts() {
        let port = free_port().await;
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(150)).await;
            let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, port)).await.unwrap();
            if let Ok((socket, _)) = listener.accept().await {
                let _ = tokio_tungstenite::accept_async(socket).await;
            }
        });

        let start = Instant::now();
        dial_upstream_ws(&format!("ws://127.0.0.1:{port}/ws"), Duration::from_secs(5))
            .await
            .expect("dial succeeds once the port binds");
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(150));
        assert!(elapsed < Duration::from_millis(1500));
    }

    #[tokio::test]
    async fn ws_dial_gives_up_at_the_deadline() {
        let port = free_port().await;

        let start = Instant::now();
        let error = dial_upstream_ws(
            &format!("ws://127.0.0.1:{port}/ws"),
            Duration::from_millis(300),
        )
        .await
        .expect_err("port never binds");
        assert!(matches!(error, tokio_tungstenite::tungstenite::Error::Io(_)));
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(300));
        assert!(elapsed < Duration::from_millis(1500));
    }
}
