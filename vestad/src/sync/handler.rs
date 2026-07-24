use std::collections::{BTreeMap, HashMap};
use std::ops::ControlFlow;
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{RawQuery, State};
use axum::http::HeaderMap;
use axum::response::Response;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::broadcast;

use crate::docker::{AgentStatus, BuildPhase, ListEntry};
use crate::settings::ServiceEntry;
use crate::state::{SharedState, WS_KEEPALIVE_INTERVAL_SECS};

use super::hub::UserNotification;
use super::protocol::{
    AgentInfo, AgentNode, ClientFrame, Frame, GatewayInfo, GatewayLan, GatewayScope, ModelAccess,
    NotificationsBranch, ServiceInfo, Tree,
};
use super::MIN_SUPPORTED_CLIENT_VERSION;

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

    // 1. hello: the served compatibility window (this gateway's version + the oldest client it accepts)
    let hello = Frame::Hello {
        version: env!("CARGO_PKG_VERSION").to_string(),
        min_supported: MIN_SUPPORTED_CLIENT_VERSION.to_string(),
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
    let mut model_access_rx = state.agent_status_cache.subscribe_model_access();
    let mut services_rx = state.agent_status_cache.subscribe_services();
    let mut invalidations_rx = state.agent_status_cache.subscribe_invalidations();
    let mut notifications_rx = state.sync_hub.subscribe_notifications();
    // User notifications are live-only (no snapshot backlog), so subscribing before the snapshot send
    // just avoids missing one that lands during setup; a broadcast receiver needs no borrow_and_update baseline.
    let mut user_notifications_rx = state.sync_hub.subscribe_user_notifications();
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
            r = model_access_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = services_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = invalidations_rx.changed() => { if r.is_err() { break } Wake::Roster }
            r = notifications_rx.changed() => { if r.is_err() { break } Wake::Notifications }
            user_notification = user_notifications_rx.recv() => Wake::UserNotification(user_notification),
            client = rx.next() => Wake::Client(client),
            _ = keepalive.tick() => Wake::Keepalive,
            () = expire(deadline) => Wake::Expire,
        };

        match wake {
            Wake::Keepalive => {
                if tx.send(Message::Ping(bytes::Bytes::new())).await.is_err() {
                    break;
                }
                if emit_roster_and_gateway(&state, &mut tx, &mut last_roster, &mut last_gateway).await.is_err() {
                    break;
                }
            }
            Wake::Roster => {
                if emit_roster_and_gateway(&state, &mut tx, &mut last_roster, &mut last_gateway).await.is_err() {
                    break;
                }
            }
            Wake::Notifications => {
                if emit_notifications(&state, &mut tx, &mut last_pending, &last_roster).await.is_err() {
                    break;
                }
            }
            Wake::UserNotification(Ok(user_notification)) => {
                let frame = Frame::UserNotification {
                    agent: user_notification.agent.clone(),
                    kind: user_notification.kind.clone(),
                    title: user_notification.title.clone(),
                    body: user_notification.body.clone(),
                };
                if send_frame(&mut tx, &frame).await.is_err() {
                    break;
                }
            }
            Wake::Client(Some(Ok(Message::Text(text)))) => {
                if let ControlFlow::Break(()) =
                    handle_client_frame(&state.api_key, text.as_str(), &mut deadline)
                {
                    break;
                }
            }
            // End the session: the peer closed, the stream ended, a transport error, the deadline, or
            // the process-lifetime user-notification hub going away (Closed, which cannot happen in practice).
            Wake::Expire
            | Wake::Client(None | Some(Ok(Message::Close(_)) | Err(_)))
            | Wake::UserNotification(Err(broadcast::error::RecvError::Closed)) => break,
            // Ignore: any non-text control frame (ping/pong/binary) and a lagged user notification
            // (ephemeral, dropped by design).
            Wake::Client(Some(Ok(_)))
            | Wake::UserNotification(Err(broadcast::error::RecvError::Lagged(_))) => {}
        }
    }
}

/// What woke the session loop. Kept small and owned so no branch future borrows the socket writer.
enum Wake {
    Roster,
    Notifications,
    UserNotification(Result<std::sync::Arc<UserNotification>, broadcast::error::RecvError>),
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
/// delta if the host branch changed.
async fn emit_roster_and_gateway(
    state: &SharedState,
    tx: &mut Tx,
    last_roster: &mut BTreeMap<String, AgentInfo>,
    last_gateway: &mut GatewayInfo,
) -> Result<(), ()> {
    let current = current_roster(state);
    for delta in roster_deltas(last_roster, &current) {
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
    last_roster: &BTreeMap<String, AgentInfo>,
) -> Result<(), ()> {
    let (deltas, recorded) = notifications_deltas(last, state.sync_hub.pending_all(), last_roster);
    for delta in &deltas {
        send_frame(tx, delta).await?;
    }
    *last = recorded;
    Ok(())
}

/// Changed pending sets -> `notifications` deltas, plus the map to record as sent. An agent absent
/// from the last-sent roster is skipped AND left unrecorded: the client's reducer drops a delta with
/// no node to attach it to, so leaving it unrecorded lets the next notifications wake retry once the
/// roster catches up. Agents dropped from `current` (forgotten) fall out of the record; `agent_removed`
/// covers them.
fn notifications_deltas(
    last: &HashMap<String, Vec<serde_json::Value>>,
    current: HashMap<String, Vec<serde_json::Value>>,
    last_roster: &BTreeMap<String, AgentInfo>,
) -> (Vec<Frame>, HashMap<String, Vec<serde_json::Value>>) {
    let mut deltas = Vec::new();
    let mut recorded = HashMap::new();
    for (agent, pending) in current {
        if !last_roster.contains_key(&agent) {
            continue;
        }
        if last.get(&agent) != Some(&pending) {
            deltas.push(Frame::Notifications { agent: agent.clone(), pending: pending.clone() });
        }
        recorded.insert(agent, pending);
    }
    (deltas, recorded)
}

/// Handle one client frame. Unknown/malformed frames are ignored by rule. Returns Break only on a
/// failed reauth (the loop then closes the socket).
fn handle_client_frame(
    api_key: &str,
    text: &str,
    deadline: &mut Option<tokio::time::Instant>,
) -> ControlFlow<()> {
    let Ok(frame) = serde_json::from_str::<ClientFrame>(text) else {
        return ControlFlow::Continue(());
    };
    match frame {
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

fn current_roster(state: &SharedState) -> BTreeMap<String, AgentInfo> {
    let cache = &state.agent_status_cache;
    build_roster(
        &cache.agents(),
        &cache.subscribe_activity().borrow(),
        &cache.subscribe_model_access().borrow(),
        &cache.subscribe_services().borrow(),
        &cache.service_revs(),
        cache.build_phases(),
    )
}

/// Join the docker-derived roster with the in-flight build phases. A creating agent has no
/// container yet during Pulling/Building/Preparing, so its phase would otherwise reach no one;
/// synthesize a `setting_up` row keyed by the same normalized name the container will take, so it
/// is replaced in place once the real entry appears.
fn build_roster(
    agents: &[ListEntry],
    activity: &HashMap<String, String>,
    model_access: &HashMap<String, ModelAccess>,
    services: &HashMap<String, HashMap<String, ServiceEntry>>,
    revs: &HashMap<String, HashMap<String, u64>>,
    mut build_phases: HashMap<String, BuildPhase>,
) -> BTreeMap<String, AgentInfo> {
    let mut roster: BTreeMap<String, AgentInfo> = agents
        .iter()
        .map(|entry| {
            let build_phase = build_phases.remove(&crate::docker::normalize_name(&entry.name));
            (entry.name.clone(), agent_info(entry, activity, model_access, services, revs, build_phase))
        })
        .collect();
    for (name, phase) in build_phases {
        roster.entry(name).or_insert_with(|| synthetic_building_info(phase));
    }
    roster
}

/// A stand-in roster row for an agent still being created, before its container exists.
fn synthetic_building_info(phase: BuildPhase) -> AgentInfo {
    AgentInfo {
        status: AgentStatus::SettingUp,
        activity_state: "idle".into(),
        model_access: ModelAccess::default(),
        build_phase: Some(phase),
        started_at: None,
        services: BTreeMap::new(),
    }
}

fn agent_info(
    entry: &ListEntry,
    activity: &HashMap<String, String>,
    model_access: &HashMap<String, ModelAccess>,
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
        model_access: model_access.get(&entry.name).cloned().unwrap_or_default(),
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
    use crate::agent_status::AgentStatusCache;

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

        let info = agent_info(&entry("scout", AgentStatus::Alive), &activity, &HashMap::new(), &svc, &revs, None);
        assert_eq!(info.activity_state, "thinking");
        assert_eq!(info.services["dashboard"], ServiceInfo { port: 8080, rev: 3 });

        // An agent with no activity entry defaults to idle.
        let idle = agent_info(
            &entry("mona", AgentStatus::Alive),
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            None,
        );
        assert_eq!(idle.activity_state, "idle");
    }

    fn info_of(status: AgentStatus) -> AgentInfo {
        AgentInfo {
            status,
            activity_state: "idle".into(),
            model_access: ModelAccess::default(),
            build_phase: None,
            started_at: None,
            services: BTreeMap::new(),
        }
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
    fn notifications_for_an_agent_absent_from_the_roster_wait_unrecorded() {
        let pending = vec![serde_json::json!("n1")];
        let current = HashMap::from([("newbie".to_string(), pending.clone())]);

        // The roster has not caught up: no delta (the client would drop it) and nothing recorded.
        let empty_roster = BTreeMap::new();
        let (deltas, recorded) = notifications_deltas(&HashMap::new(), current.clone(), &empty_roster);
        assert!(deltas.is_empty());
        assert!(recorded.is_empty());

        // Roster upsert lands; the next emit with the same pending now delivers and records it.
        let roster = BTreeMap::from([("newbie".to_string(), info_of(AgentStatus::Alive))]);
        let (deltas, recorded) = notifications_deltas(&recorded, current, &roster);
        assert_eq!(deltas, vec![Frame::Notifications { agent: "newbie".into(), pending: pending.clone() }]);
        assert_eq!(recorded.get("newbie"), Some(&pending));
    }

    #[test]
    fn build_roster_synthesizes_a_mid_build_agent_without_a_container() {
        let build_phases = HashMap::from([("luna".to_string(), BuildPhase::Pulling)]);
        let roster = build_roster(&[], &HashMap::new(), &HashMap::new(), &HashMap::new(), &HashMap::new(), build_phases);

        let luna = roster.get("luna").expect("synthetic row for the creating agent");
        assert_eq!(luna.status, AgentStatus::SettingUp);
        assert_eq!(luna.build_phase, Some(BuildPhase::Pulling));
        assert_eq!(luna.started_at, None);
        assert!(luna.services.is_empty());
    }

    #[test]
    fn build_roster_replaces_the_synthetic_row_when_the_container_appears() {
        // The container now exists while the phase is still recorded: one real row carries the
        // phase, with no lingering synthetic ghost.
        let agents = [entry("luna", AgentStatus::SettingUp)];
        let build_phases = HashMap::from([("luna".to_string(), BuildPhase::Starting)]);
        let roster = build_roster(
            &agents,
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            build_phases,
        );
        assert_eq!(roster.len(), 1);
        assert_eq!(roster["luna"].build_phase, Some(BuildPhase::Starting));

        // Create settled: phase cleared, the real row remains with no phase.
        let settled = build_roster(
            &[entry("luna", AgentStatus::Alive)],
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            HashMap::new(),
        );
        assert_eq!(settled.len(), 1);
        assert_eq!(settled["luna"].build_phase, None);
    }

    #[test]
    fn set_and_clear_build_phase_wake_the_roster_subscription() {
        let cache = AgentStatusCache::new();
        let mut invalidations = cache.subscribe_invalidations();
        invalidations.borrow_and_update();

        // The roster loop wakes on this channel (Wake::Roster); each transition must fire it.
        cache.set_build_phase("luna", BuildPhase::Building);
        assert!(invalidations.has_changed().expect("sender alive"));
        assert_eq!(cache.build_phases()["luna"], BuildPhase::Building);

        invalidations.borrow_and_update();
        cache.clear_build_phase("luna");
        assert!(invalidations.has_changed().expect("sender alive"));
        assert!(cache.build_phases().is_empty());
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

    #[test]
    fn reauth_extends_on_valid_token_and_breaks_on_invalid() {
        let mut deadline: Option<tokio::time::Instant> = None;

        let token = crate::jwt::create_token("secret", "access", crate::jwt::ACCESS_TOKEN_TTL);
        let valid = format!(r#"{{"type":"reauth","token":"{token}"}}"#);
        let flow = handle_client_frame("secret", &valid, &mut deadline);
        assert!(matches!(flow, ControlFlow::Continue(())));
        assert!(deadline.is_some(), "a valid reauth extends the deadline");

        let before = deadline;
        let flow = handle_client_frame("secret", r#"{"type":"reauth","token":"bad.token.here"}"#, &mut deadline);
        assert!(matches!(flow, ControlFlow::Break(())), "a bad reauth breaks the loop");
        assert_eq!(deadline, before, "a failed reauth leaves the deadline unchanged");
    }
}
