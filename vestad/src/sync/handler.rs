use std::collections::{BTreeMap, HashMap};
use std::ops::ControlFlow;
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{RawQuery, State};
use axum::http::HeaderMap;
use axum::response::Response;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::{broadcast, mpsc};

use crate::docker::ListEntry;
use crate::settings::ServiceEntry;
use crate::state::{SharedState, WS_KEEPALIVE_INTERVAL_SECS};

use super::hub::{LiveMessage, SyncHub};
use super::protocol::{
    AgentInfo, AgentNode, ClientFrame, Frame, GatewayInfo, GatewayLan, GatewayScope,
    NotificationsBranch, ServiceInfo, Tree,
};
use super::{PROTOCOL_FLOOR, PROTOCOL_VERSION};

/// Per-connection buffer for the fan-in of every watch's live edge into the one socket writer.
const WATCH_FANIN_CAPACITY: usize = 128;

type Tx = futures_util::stream::SplitSink<WebSocket, Message>;

pub(crate) async fn sync_ws_handler(
    State(state): State<SharedState>,
    headers: HeaderMap,
    RawQuery(raw_query): RawQuery,
    ws: WebSocketUpgrade,
) -> Response {
    // auth_middleware already validated the connect token; capture it to derive the reauth deadline.
    let token = connect_token(&headers, raw_query.as_deref());
    ws.on_upgrade(move |socket| sync_session(state, socket, token))
}

/// The connect token, from either `Authorization: Bearer` or `?token=` (browser WS connects cannot
/// set headers, so the query form is the one the app uses).
fn connect_token(headers: &HeaderMap, raw_query: Option<&str>) -> Option<String> {
    if let Some(bearer) = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
    {
        return Some(bearer.to_string());
    }
    raw_query?.split('&').find_map(|p| p.strip_prefix("token=")).map(str::to_string)
}

/// The instant a connection's auth token expires, or None for the non-expiring raw API key. A JWT
/// access token carries `exp`; `/sync` closes the socket at the deadline unless a `reauth` extends
/// it. `auth_middleware` already gated the upgrade, so a token that does not validate here (only the
/// raw-key path) simply yields no deadline.
fn token_deadline(token: &str, api_key: &str) -> Option<tokio::time::Instant> {
    if !token.contains('.') {
        return None;
    }
    let claims = crate::jwt::validate_token(api_key, token, "access").ok()?;
    let remaining = claims.exp.saturating_sub(crate::time_utils::now_epoch_secs());
    Some(tokio::time::Instant::now() + Duration::from_secs(remaining))
}

async fn sync_session(state: SharedState, socket: WebSocket, connect_token: Option<String>) {
    let (mut tx, mut rx) = socket.split();

    // 1. hello
    let hello = Frame::Hello {
        version: env!("CARGO_PKG_VERSION").to_string(),
        protocol: PROTOCOL_VERSION,
        floor: PROTOCOL_FLOOR,
    };
    if send_frame(&mut tx, &hello).await.is_err() {
        return;
    }

    // Subscribe every delta source before reading the snapshot, so an update landing in the gap
    // between the snapshot read and the subscribe still fires changed() (notifications have no
    // keepalive re-emit to self-heal a missed one). borrow_and_update marks the current values seen,
    // making the snapshot the baseline the deltas build on.
    let mut agents_rx = state.agent_status_cache.subscribe_agents();
    let mut activity_rx = state.agent_status_cache.subscribe_activity();
    let mut services_rx = state.agent_status_cache.subscribe_services();
    let mut invalidations_rx = state.agent_status_cache.subscribe_invalidations();
    let mut notifications_rx = state.sync_hub.subscribe_notifications();
    agents_rx.borrow_and_update();
    activity_rx.borrow_and_update();
    services_rx.borrow_and_update();
    invalidations_rx.borrow_and_update();
    notifications_rx.borrow_and_update();

    // 2. immediate snapshot: gateway + agents (info + pending sets), no tails.
    let mut last_roster = current_roster(&state);
    let mut last_gateway = build_gateway_info(&state).await;
    let mut last_pending = state.sync_hub.pending_all();
    let tree = build_tree(&last_gateway, &last_roster, &last_pending);
    if send_frame(&mut tx, &Frame::Snapshot { tree }).await.is_err() {
        return;
    }

    // Each watch spawns a task forwarding the hub's live edge into this per-connection mpsc; the one
    // socket writer drains it, so a chatty agent never blocks the others.
    let (watch_tx, mut watch_rx) = mpsc::channel::<Frame>(WATCH_FANIN_CAPACITY);
    let mut watches: HashMap<String, tokio::task::AbortHandle> = HashMap::new();

    let mut deadline = connect_token.as_deref().and_then(|t| token_deadline(t, &state.api_key));

    // The ping keeps an idle socket alive through the Cloudflare tunnel (reaps ~100s silence), same
    // as the control WS.
    let mut keepalive = tokio::time::interval(Duration::from_secs(WS_KEEPALIVE_INTERVAL_SECS));
    keepalive.tick().await;

    loop {
        // Branch futures borrow only the receivers, never `tx`; the mutable send work happens after
        // the select resolves (tokio::select! constructs every branch future up front).
        let wake = tokio::select! {
            r = agents_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = activity_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = services_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = invalidations_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = notifications_rx.changed() => { if r.is_err() { break } Wake::Notifications }
            frame = watch_rx.recv() => Wake::Watch(frame),
            client = rx.next() => Wake::Client(client),
            _ = keepalive.tick() => Wake::Keepalive,
            () = expire(deadline) => Wake::Expire,
        };

        match wake {
            Wake::Keepalive => {
                if tx.send(Message::Ping(bytes::Bytes::new())).await.is_err() {
                    break;
                }
                if emit_roster_and_gateway(&state, &mut tx, &mut last_roster, &mut last_gateway, &mut watches).await.is_err() {
                    break;
                }
            }
            Wake::Roster => {
                if emit_roster_and_gateway(&state, &mut tx, &mut last_roster, &mut last_gateway, &mut watches).await.is_err() {
                    break;
                }
            }
            Wake::Notifications => {
                if emit_notifications(&state, &mut tx, &mut last_pending).await.is_err() {
                    break;
                }
            }
            Wake::Watch(Some(delta)) => {
                // A resync from a watch task means that watch ended (overflow or a tap gap); drop it
                // so the client re-watches.
                if let Frame::Resync { agent } = &delta {
                    watches.remove(agent);
                }
                if send_frame(&mut tx, &delta).await.is_err() {
                    break;
                }
            }
            Wake::Client(Some(Ok(Message::Text(text)))) => {
                if let ControlFlow::Break(()) =
                    handle_client_frame(&state.sync_hub, &state.api_key, text.as_str(), &mut watches, &watch_tx, &mut deadline)
                {
                    break;
                }
            }
            // End the session: the peer closed, the stream ended, a transport error, or the deadline.
            Wake::Expire | Wake::Client(None | Some(Ok(Message::Close(_)) | Err(_))) => break,
            // Ignore: an empty watch wake and any non-text control frame (ping/pong/binary).
            Wake::Watch(None) | Wake::Client(Some(Ok(_))) => {}
        }
    }

    for (_, handle) in watches {
        handle.abort();
    }
}

/// What woke the session loop. Kept small and owned so no branch future borrows the socket writer.
enum Wake {
    Roster,
    Notifications,
    Watch(Option<Frame>),
    Client(Option<Result<Message, axum::Error>>),
    Keepalive,
    Expire,
}

/// Sleep until the token deadline, or forever when there is none (the raw API key).
async fn expire(deadline: Option<tokio::time::Instant>) {
    match deadline {
        Some(instant) => tokio::time::sleep_until(instant).await,
        None => std::future::pending::<()>().await,
    }
}

async fn send_frame(tx: &mut Tx, frame: &Frame) -> Result<(), ()> {
    let encoded = match frame.encode() {
        Ok(text) => text,
        Err(error) => {
            tracing::error!(%error, "failed to encode sync frame; dropping it");
            return Ok(());
        }
    };
    tx.send(Message::Text(encoded.into())).await.map_err(|_| ())
}

/// Diff the roster against last-sent and emit `agent`/`agent_removed`, then the gateway `state`
/// delta if the host branch changed. An `agent_removed` also cancels that agent's watch.
async fn emit_roster_and_gateway(
    state: &SharedState,
    tx: &mut Tx,
    last_roster: &mut BTreeMap<String, AgentInfo>,
    last_gateway: &mut GatewayInfo,
    watches: &mut HashMap<String, tokio::task::AbortHandle>,
) -> Result<(), ()> {
    let current = current_roster(state);
    for delta in roster_deltas(last_roster, &current) {
        if let Frame::AgentRemoved { name } = &delta {
            if let Some(handle) = watches.remove(name) {
                handle.abort();
            }
        }
        send_frame(tx, &delta).await?;
    }
    *last_roster = current;

    let gateway = build_gateway_info(state).await;
    if gateway != *last_gateway {
        send_frame(tx, &Frame::State { scope: GatewayScope::Gateway, value: gateway.clone() }).await?;
        *last_gateway = gateway;
    }
    Ok(())
}

async fn emit_notifications(
    state: &SharedState,
    tx: &mut Tx,
    last: &mut HashMap<String, Vec<serde_json::Value>>,
) -> Result<(), ()> {
    let current = state.sync_hub.pending_all();
    for (agent, pending) in &current {
        if last.get(agent) != Some(pending) {
            send_frame(tx, &Frame::Notifications { agent: agent.clone(), pending: pending.clone() }).await?;
        }
    }
    // Agents dropped from the map (forgotten) need no notifications delta; `agent_removed` covers it.
    *last = current;
    Ok(())
}

/// Handle one client frame. Unknown/malformed frames are ignored by rule. Returns Break only on a
/// failed reauth (the loop then closes the socket).
fn handle_client_frame(
    sync_hub: &SyncHub,
    api_key: &str,
    text: &str,
    watches: &mut HashMap<String, tokio::task::AbortHandle>,
    watch_tx: &mpsc::Sender<Frame>,
    deadline: &mut Option<tokio::time::Instant>,
) -> ControlFlow<()> {
    let Ok(frame) = serde_json::from_str::<ClientFrame>(text) else {
        return ControlFlow::Continue(());
    };
    match frame {
        ClientFrame::Watch { agent } => {
            if let std::collections::hash_map::Entry::Vacant(slot) = watches.entry(agent) {
                let handle = spawn_watch(sync_hub, slot.key(), watch_tx.clone());
                slot.insert(handle);
            }
        }
        ClientFrame::Unwatch { agent } => {
            if let Some(handle) = watches.remove(&agent) {
                handle.abort();
            }
        }
        ClientFrame::Reauth { token } => {
            if crate::auth::verify_token(&token, api_key) {
                *deadline = token_deadline(&token, api_key);
            } else {
                tracing::warn!("sync reauth failed; closing socket");
                return ControlFlow::Break(());
            }
        }
    }
    ControlFlow::Continue(())
}

/// Spawn the forward task for one watch: the hub's live edge becomes `append` deltas; a `Resync` or a
/// lagging receiver (overflow) becomes one `resync` delta and ends the watch (client re-watches).
fn spawn_watch(sync_hub: &SyncHub, agent: &str, watch_tx: mpsc::Sender<Frame>) -> tokio::task::AbortHandle {
    let mut events = sync_hub.subscribe_events(agent);
    let agent = agent.to_string();
    let task = tokio::spawn(async move {
        loop {
            match events.recv().await {
                Ok(LiveMessage::Event(event)) => {
                    let delta = Frame::Append { agent: agent.clone(), events: vec![(*event).clone()] };
                    if watch_tx.send(delta).await.is_err() {
                        break;
                    }
                }
                Ok(LiveMessage::Resync) | Err(broadcast::error::RecvError::Lagged(_)) => {
                    let _ = watch_tx.send(Frame::Resync { agent: agent.clone() }).await;
                    break;
                }
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    });
    task.abort_handle()
}

fn current_roster(state: &SharedState) -> BTreeMap<String, AgentInfo> {
    let agents = state.agent_status_cache.agents();
    let activity = state.agent_status_cache.subscribe_activity().borrow().clone();
    let services = state.agent_status_cache.subscribe_services().borrow().clone();
    let revs = state.agent_status_cache.service_revs();
    agents
        .iter()
        .map(|entry| {
            let build_phase = state.build_phase(&crate::docker::normalize_name(&entry.name));
            (entry.name.clone(), agent_info(entry, &activity, &services, &revs, build_phase))
        })
        .collect()
}

fn agent_info(
    entry: &ListEntry,
    activity: &HashMap<String, String>,
    services: &HashMap<String, HashMap<String, ServiceEntry>>,
    revs: &HashMap<String, HashMap<String, u64>>,
    build_phase: Option<crate::docker::BuildPhase>,
) -> AgentInfo {
    let activity_state = activity.get(&entry.name).cloned().unwrap_or_else(|| "idle".to_string());
    let agent_revs = revs.get(&entry.name);
    let services = services
        .get(&entry.name)
        .map(|svc| {
            svc.iter()
                .map(|(svc_name, e)| {
                    let rev = agent_revs.and_then(|m| m.get(svc_name)).copied().unwrap_or(0);
                    (svc_name.clone(), ServiceInfo { port: e.port, rev })
                })
                .collect()
        })
        .unwrap_or_default();
    AgentInfo {
        status: entry.status,
        activity_state,
        build_phase,
        started_at: entry.started_at.clone(),
        services,
    }
}

/// New or changed agents -> `agent` upserts; agents gone from the roster -> `agent_removed`. Ordered
/// deterministically (`BTreeMap` iteration) so the wire stream is stable.
fn roster_deltas(last: &BTreeMap<String, AgentInfo>, current: &BTreeMap<String, AgentInfo>) -> Vec<Frame> {
    let mut deltas = Vec::new();
    for (name, info) in current {
        if last.get(name) != Some(info) {
            deltas.push(Frame::Agent { name: name.clone(), info: info.clone() });
        }
    }
    for name in last.keys() {
        if !current.contains_key(name) {
            deltas.push(Frame::AgentRemoved { name: name.clone() });
        }
    }
    deltas
}

fn build_tree(
    gateway: &GatewayInfo,
    roster: &BTreeMap<String, AgentInfo>,
    pending: &HashMap<String, Vec<serde_json::Value>>,
) -> Tree {
    let agents = roster
        .iter()
        .map(|(name, info)| {
            let pending = pending.get(name).cloned().unwrap_or_default();
            (name.clone(), AgentNode { info: info.clone(), notifications: NotificationsBranch { pending } })
        })
        .collect();
    Tree { gateway: gateway.clone(), agents }
}

async fn build_gateway_info(state: &SharedState) -> GatewayInfo {
    let (update_available, latest_version) = {
        let update = state.update_info.lock().await;
        (
            update.as_ref().is_some_and(|i| i.update_available),
            update.as_ref().map(|i| i.latest.clone()),
        )
    };
    let (auto_update, channel) = {
        let settings = state.settings.read().await;
        (settings.auto_update, crate::channel::Channel::resolve(&settings.channel).as_str().to_string())
    };
    let tunnel_url = state.tunnel_url.lock().await.clone();
    GatewayInfo {
        version: env!("CARGO_PKG_VERSION").to_string(),
        channel,
        auto_update,
        port: state.https_port,
        lan: GatewayLan { exposed: state.expose_lan, url: state.lan_url.clone() },
        tunnel_url,
        update_available,
        latest_version,
        managed: crate::is_cloud_managed(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::docker::AgentStatus;

    fn entry(name: &str, status: AgentStatus) -> ListEntry {
        ListEntry { name: name.to_string(), status, ws_port: 4200, started_at: Some("2026-01-01T00:00:00Z".into()) }
    }

    #[test]
    fn agent_info_defaults_activity_and_carries_service_revs() {
        let mut activity = HashMap::new();
        activity.insert("scout".to_string(), "thinking".to_string());
        let mut svc = HashMap::new();
        svc.insert("scout".to_string(), HashMap::from([("dashboard".to_string(), ServiceEntry { port: 8080, public: true })]));
        let mut revs = HashMap::new();
        revs.insert("scout".to_string(), HashMap::from([("dashboard".to_string(), 3u64)]));

        let info = agent_info(&entry("scout", AgentStatus::Alive), &activity, &svc, &revs, None);
        assert_eq!(info.activity_state, "thinking");
        assert_eq!(info.services["dashboard"], ServiceInfo { port: 8080, rev: 3 });

        // An agent with no activity entry defaults to idle.
        let idle = agent_info(&entry("mona", AgentStatus::Alive), &HashMap::new(), &HashMap::new(), &HashMap::new(), None);
        assert_eq!(idle.activity_state, "idle");
    }

    fn info_of(status: AgentStatus) -> AgentInfo {
        AgentInfo { status, activity_state: "idle".into(), build_phase: None, started_at: None, services: BTreeMap::new() }
    }

    #[test]
    fn roster_deltas_emit_upserts_and_removals() {
        let mut last = BTreeMap::new();
        last.insert("scout".to_string(), info_of(AgentStatus::Alive));
        last.insert("gone".to_string(), info_of(AgentStatus::Alive));

        let mut current = BTreeMap::new();
        current.insert("scout".to_string(), info_of(AgentStatus::Stopped)); // changed -> agent upsert
        current.insert("new".to_string(), info_of(AgentStatus::Alive)); // added -> agent upsert

        let deltas = roster_deltas(&last, &current);
        assert!(deltas.contains(&Frame::Agent { name: "scout".into(), info: info_of(AgentStatus::Stopped) }));
        assert!(deltas.contains(&Frame::Agent { name: "new".into(), info: info_of(AgentStatus::Alive) }));
        assert!(deltas.contains(&Frame::AgentRemoved { name: "gone".into() }));
        assert_eq!(deltas.len(), 3);

        // No change -> no deltas.
        assert!(roster_deltas(&current, &current).is_empty());
    }

    #[test]
    fn connect_token_reads_bearer_then_query() {
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer abc".parse().expect("header"));
        assert_eq!(connect_token(&headers, None).as_deref(), Some("abc"));
        assert_eq!(connect_token(&HeaderMap::new(), Some("x=1&token=q2&y=3")).as_deref(), Some("q2"));
        assert_eq!(connect_token(&HeaderMap::new(), None), None);
    }

    #[test]
    fn token_deadline_is_set_for_jwt_and_absent_for_raw_key() {
        let token = crate::jwt::create_token("secret", "access", crate::jwt::ACCESS_TOKEN_TTL);
        assert!(token_deadline(&token, "secret").is_some());
        assert!(token_deadline("secret", "secret").is_none()); // raw key never expires
        assert!(token_deadline(&token, "other-key").is_none()); // fails validation -> no deadline
    }

    fn abort_all(watches: HashMap<String, tokio::task::AbortHandle>) {
        for (_, handle) in watches {
            handle.abort();
        }
    }

    // The four tests below drive handle_client_frame/spawn_watch against a bare SyncHub (no
    // SharedState), the hermetic seam the explicit-deps refactor unlocks. Current-thread runtime: a
    // spawned forward task does not run until the test awaits, which is what makes the flood-then-lag
    // path deterministic.

    #[tokio::test]
    async fn watch_then_publish_delivers_an_append_delta() {
        let hub = SyncHub::new();
        let (watch_tx, mut watch_rx) = mpsc::channel::<Frame>(WATCH_FANIN_CAPACITY);
        let mut watches = HashMap::new();
        let mut deadline = None;

        let flow = handle_client_frame(&hub, "key", r#"{"type":"watch","agent":"scout"}"#, &mut watches, &watch_tx, &mut deadline);
        assert!(matches!(flow, ControlFlow::Continue(())));
        assert!(watches.contains_key("scout"));

        hub.publish_event("scout", std::sync::Arc::new(serde_json::json!({"id": 1, "text": "hi"})));
        match watch_rx.recv().await.expect("append delta") {
            Frame::Append { agent, events } => {
                assert_eq!(agent, "scout");
                assert_eq!(events[0]["text"], serde_json::json!("hi"));
            }
            other => panic!("expected an append, got {other:?}"),
        }
        abort_all(watches);
    }

    #[tokio::test]
    async fn unwatch_aborts_delivery() {
        let hub = SyncHub::new();
        let (watch_tx, mut watch_rx) = mpsc::channel::<Frame>(WATCH_FANIN_CAPACITY);
        let mut watches = HashMap::new();
        let mut deadline = None;

        let _ = handle_client_frame(&hub, "key", r#"{"type":"watch","agent":"scout"}"#, &mut watches, &watch_tx, &mut deadline);
        let _ = handle_client_frame(&hub, "key", r#"{"type":"unwatch","agent":"scout"}"#, &mut watches, &watch_tx, &mut deadline);
        assert!(watches.is_empty());

        hub.publish_event("scout", std::sync::Arc::new(serde_json::json!({"id": 1})));
        // Let the runtime cancel the aborted forward task, then confirm it never forwarded the event.
        for _ in 0..8 {
            tokio::task::yield_now().await;
        }
        assert!(matches!(watch_rx.try_recv(), Err(mpsc::error::TryRecvError::Empty)));
    }

    #[tokio::test]
    async fn overflow_yields_one_resync_and_ends_the_watch() {
        let hub = SyncHub::new();
        let (watch_tx, mut watch_rx) = mpsc::channel::<Frame>(WATCH_FANIN_CAPACITY);
        let mut watches = HashMap::new();
        let mut deadline = None;

        let _ = handle_client_frame(&hub, "key", r#"{"type":"watch","agent":"chatty"}"#, &mut watches, &watch_tx, &mut deadline);

        // The forward task has not been polled yet, so its broadcast receiver sits at the initial
        // version; flooding well past the buffer forces Lagged on its first recv.
        for id in 0..2048 {
            hub.publish_event("chatty", std::sync::Arc::new(serde_json::json!({"id": id})));
        }
        assert!(matches!(watch_rx.recv().await, Some(Frame::Resync { agent }) if agent == "chatty"));

        // The watch ended on the resync: further live events deliver nothing.
        hub.publish_event("chatty", std::sync::Arc::new(serde_json::json!({"id": 9999})));
        for _ in 0..8 {
            tokio::task::yield_now().await;
        }
        assert!(matches!(watch_rx.try_recv(), Err(mpsc::error::TryRecvError::Empty)));
        abort_all(watches);
    }

    #[tokio::test]
    async fn reauth_extends_on_valid_token_and_breaks_on_invalid() {
        let hub = SyncHub::new();
        let (watch_tx, _watch_rx) = mpsc::channel::<Frame>(WATCH_FANIN_CAPACITY);
        let mut watches = HashMap::new();
        let mut deadline: Option<tokio::time::Instant> = None;

        let token = crate::jwt::create_token("secret", "access", crate::jwt::ACCESS_TOKEN_TTL);
        let valid = format!(r#"{{"type":"reauth","token":"{token}"}}"#);
        let flow = handle_client_frame(&hub, "secret", &valid, &mut watches, &watch_tx, &mut deadline);
        assert!(matches!(flow, ControlFlow::Continue(())));
        assert!(deadline.is_some(), "a valid reauth extends the deadline");

        let before = deadline;
        let flow = handle_client_frame(&hub, "secret", r#"{"type":"reauth","token":"bad.token.here"}"#, &mut watches, &watch_tx, &mut deadline);
        assert!(matches!(flow, ControlFlow::Break(())), "a bad reauth breaks the loop");
        assert_eq!(deadline, before, "a failed reauth leaves the deadline unchanged");
    }
}
