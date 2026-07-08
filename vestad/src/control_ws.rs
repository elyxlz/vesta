use std::collections::HashMap;

use axum::{
    extract::{ws::WebSocketUpgrade, Path, State},
    http::StatusCode,
    response::Response,
    Json,
};

use std::time::Duration;

use crate::docker;
use crate::serve::{ServiceEntry, SharedState, err_response, ok_json, WS_KEEPALIVE_INTERVAL_SECS};

pub async fn invalidate_service_handler(
    State(state): State<SharedState>,
    Path((name, service_name)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let settings = state.settings.read().await;
    let exists = settings
        .services
        .get(&name)
        .is_some_and(|s| s.contains_key(&service_name));
    if !exists {
        return Err(err_response(
            StatusCode::NOT_FOUND,
            &format!("service '{}' not registered for agent '{}'", service_name, name),
        ));
    }
    drop(settings);

    state.agent_status_cache.invalidate_service(&name, &service_name);
    tracing::debug!(agent = %name, service = %service_name, "service invalidated");
    Ok(ok_json())
}

pub async fn control_ws_handler(
    State(state): State<SharedState>,
    ws: WebSocketUpgrade,
) -> Response {
    ws.on_upgrade(move |socket| control_ws_session(state, socket))
}

// pub(crate): also exercised by the API contract test in serve.rs, which captures this
// message's wire format into fixtures checked against the web app's TypeScript types.
pub(crate) fn build_agents_message(
    agents: &[docker::ListEntry],
    activity: &HashMap<String, String>,
    services: &HashMap<String, HashMap<String, ServiceEntry>>,
    revs: &HashMap<String, HashMap<String, u64>>,
) -> serde_json::Value {
    let enriched: Vec<serde_json::Value> = agents
        .iter()
        .map(|a| {
            let mut obj = serde_json::to_value(a).unwrap_or_default();
            if let Some(map) = obj.as_object_mut() {
                let state = activity.get(&a.name).map(|s| s.as_str()).unwrap_or("idle");
                map.insert("activityState".into(), serde_json::Value::String(state.into()));

                let agent_revs = revs.get(&a.name);
                let svc_obj: serde_json::Map<String, serde_json::Value> = services
                    .get(&a.name)
                    .map(|svc_map| {
                        svc_map
                            .iter()
                            .map(|(svc_name, entry)| {
                                let rev = agent_revs.and_then(|m| m.get(svc_name)).copied().unwrap_or(0);
                                let val = serde_json::json!({
                                    "port": entry.port,
                                    "public": entry.public,
                                    "rev": rev,
                                    "key": entry.key,
                                });
                                (svc_name.clone(), val)
                            })
                            .collect()
                    })
                    .unwrap_or_default();
                map.insert("services".into(), serde_json::Value::Object(svc_obj));
            }
            obj
        })
        .collect();
    serde_json::json!({ "type": "agents", "agents": enriched })
}

async fn control_ws_session(state: SharedState, socket: axum::extract::ws::WebSocket) {
    use axum::extract::ws::Message;
    use futures_util::{SinkExt, StreamExt};

    let (mut tx, mut rx) = socket.split();

    // 1. Send hello handshake
    let hello = serde_json::json!({
        "type": "hello",
        "version": env!("CARGO_PKG_VERSION"),
        "port": state.env_config.vestad_port,
    });
    if tx.send(Message::Text(hello.to_string().into())).await.is_err() {
        return;
    }

    // 2. Send initial agents snapshot
    let mut agents_rx = state.agent_status_cache.subscribe_agents();
    let mut activity_rx = state.agent_status_cache.subscribe_activity();
    let mut services_rx = state.agent_status_cache.subscribe_services();
    let mut invalidations_rx = state.agent_status_cache.subscribe_invalidations();

    let agents = agents_rx.borrow_and_update().clone();
    let activity = activity_rx.borrow_and_update().clone();
    let services = services_rx.borrow_and_update().clone();
    let revs = state.agent_status_cache.service_revs();
    let msg = build_agents_message(&agents, &activity, &services, &revs);
    if tx.send(Message::Text(msg.to_string().into())).await.is_err() {
        return;
    }

    // 3. Event loop. The ping keeps an idle socket alive through the Cloudflare tunnel, which
    // reaps connections silent for ~100s; without it an idle client is dropped and forced to
    // reconnect, which tears the whole app tree down and back up.
    let mut keepalive = tokio::time::interval(Duration::from_secs(WS_KEEPALIVE_INTERVAL_SECS));
    keepalive.tick().await; // the first tick is immediate; drop it so the first ping waits a full interval
    loop {
        tokio::select! {
            result = agents_rx.changed() => { if result.is_err() { break; } }
            result = activity_rx.changed() => { if result.is_err() { break; } }
            result = services_rx.changed() => { if result.is_err() { break; } }
            result = invalidations_rx.changed() => { if result.is_err() { break; } }
            msg = rx.next() => {
                match msg {
                    Some(Ok(Message::Close(_))) | None => break,
                    _ => { continue; }
                }
            }
            _ = keepalive.tick() => {
                if tx.send(Message::Ping(Default::default())).await.is_err() { break; }
                continue;
            }
        }

        // Drain all watches and send a single coalesced snapshot
        let agents = agents_rx.borrow_and_update().clone();
        let activity = activity_rx.borrow_and_update().clone();
        let services = services_rx.borrow_and_update().clone();
        let revs = state.agent_status_cache.service_revs();
        let msg = build_agents_message(&agents, &activity, &services, &revs);
        if tx.send(Message::Text(msg.to_string().into())).await.is_err() {
            break;
        }
    }
}
