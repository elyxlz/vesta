use std::collections::HashMap;

use axum::{
    extract::{ws::WebSocketUpgrade, Path, State},
    http::StatusCode,
    response::Response,
    Json,
};

use crate::{agent_status, docker};
use crate::serve::{ServiceEntry, SharedState, err_response, ok_json};

pub async fn invalidate_service_handler(
    State(state): State<SharedState>,
    Path((name, service_name)): Path<(String, String)>,
    body: Option<Json<serde_json::Value>>,
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

    let scope = body
        .and_then(|Json(v)| v.get("scope").and_then(|s| s.as_str().map(String::from)));
    state
        .agent_status_cache
        .invalidate_service(&name, &service_name, scope.as_deref());
    tracing::debug!(agent = %name, service = %service_name, ?scope, "service invalidated");
    Ok(ok_json())
}

pub async fn control_ws_handler(
    State(state): State<SharedState>,
    ws: WebSocketUpgrade,
) -> Response {
    ws.on_upgrade(move |socket| control_ws_session(state, socket))
}

fn build_agents_message(
    agents: &[docker::ListEntry],
    activity: &HashMap<String, String>,
    services: &HashMap<String, HashMap<String, ServiceEntry>>,
    invalidations: &HashMap<String, HashMap<String, agent_status::DrainedInvalidation>>,
) -> serde_json::Value {
    let enriched: Vec<serde_json::Value> = agents
        .iter()
        .map(|a| {
            let mut obj = serde_json::to_value(a).unwrap_or_default();
            if let Some(map) = obj.as_object_mut() {
                let state = activity.get(&a.name).map(|s| s.as_str()).unwrap_or("idle");
                map.insert("activityState".into(), serde_json::Value::String(state.into()));

                let agent_inv = invalidations.get(&a.name);
                let svc_obj: serde_json::Map<String, serde_json::Value> = services
                    .get(&a.name)
                    .map(|svc_map| {
                        svc_map
                            .iter()
                            .map(|(svc_name, entry)| {
                                let inv = agent_inv.and_then(|m| m.get(svc_name));
                                let val = serde_json::json!({
                                    "port": entry.port,
                                    "public": entry.public,
                                    "rev": inv.map(|i| i.rev).unwrap_or(0),
                                    "scopes": inv.map(|i| &i.scopes).unwrap_or(&Vec::new()),
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
    let invalidations = state.agent_status_cache.drain_invalidations();
    let msg = build_agents_message(&agents, &activity, &services, &invalidations);
    if tx.send(Message::Text(msg.to_string().into())).await.is_err() {
        return;
    }

    // 3. Event loop
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
        }

        // Drain all watches and send a single coalesced snapshot
        let agents = agents_rx.borrow_and_update().clone();
        let activity = activity_rx.borrow_and_update().clone();
        let services = services_rx.borrow_and_update().clone();
        let invalidations = state.agent_status_cache.drain_invalidations();
        let msg = build_agents_message(&agents, &activity, &services, &invalidations);
        if tx.send(Message::Text(msg.to_string().into())).await.is_err() {
            break;
        }
    }
}
