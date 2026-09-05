//! The chat live-edge socket: one session per connection, filtered to the rooms it may read.
//! `/rooms/ws` is the replay-free live edge of one room (a client) or of every room the caller is
//! in (an agent's daemon). Inbound carries the speaking report; a lagging session is closed so its
//! client reseeds by id.

use std::time::Duration;

use axum::extract::ws::{Message as WsMessage, WebSocket, WebSocketUpgrade};
use axum::extract::{Extension, Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use tokio::sync::broadcast::error::RecvError;

use crate::auth::ChatPrincipal;
use crate::chat::{ChatEvent, Room};
use crate::state::{SharedState, WS_KEEPALIVE_INTERVAL_SECS};

/// What a session reads: one named room, or every room its principal is a member of.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum Scope {
    Room(String),
    All,
}

#[derive(Deserialize)]
pub(crate) struct SocketQuery {
    room: Option<String>,
}

/// Whether `event` belongs on a session of `scope` for `principal`, judged against the rooms as
/// they are now, so membership changes after connect apply at once.
pub(crate) fn wants(
    scope: &Scope,
    principal: &ChatPrincipal,
    event: &ChatEvent,
    lookup: impl Fn(&str) -> Option<Room>,
) -> bool {
    let room_id = event.room_id();
    match scope {
        Scope::Room(id) => id == room_id,
        Scope::All => lookup(room_id).is_some_and(|room| principal.is_member(&room)),
    }
}

/// The one inbound frame: `{"type":"speaking","active":bool}`; anything else is ignored.
pub(crate) fn parse_client_frame(raw: &str) -> Option<bool> {
    let frame: serde_json::Value = serde_json::from_str(raw).ok()?;
    if frame.get("type").and_then(serde_json::Value::as_str) != Some("speaking") {
        return None;
    }
    frame.get("active").and_then(serde_json::Value::as_bool)
}

pub(crate) async fn rooms_ws_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
    Query(query): Query<SocketQuery>,
    ws: WebSocketUpgrade,
) -> Response {
    let scope = match query.room {
        None => Scope::All,
        Some(id) => match state.chat.room(&id) {
            None => {
                let body = serde_json::json!({ "error": "no such room" });
                return (StatusCode::NOT_FOUND, Json(body)).into_response();
            }
            Some(room) if !principal.is_member(&room) => {
                let body = serde_json::json!({ "error": "not a member of this room" });
                return (StatusCode::FORBIDDEN, Json(body)).into_response();
            }
            Some(_) => Scope::Room(id),
        },
    };
    ws.on_upgrade(move |socket| session(state, principal, scope, socket))
}

async fn session(state: SharedState, principal: ChatPrincipal, scope: Scope, socket: WebSocket) {
    let connection = state.chat.new_connection();
    let mut events = state.chat.subscribe_events();
    let (mut tx, mut rx) = socket.split();
    let mut keepalive = tokio::time::interval(Duration::from_secs(WS_KEEPALIVE_INTERVAL_SECS));
    keepalive.tick().await;
    loop {
        tokio::select! {
            received = events.recv() => match received {
                Ok(event) => {
                    if !wants(&scope, &principal, &event, |id| state.chat.room(id)) {
                        continue;
                    }
                    let Ok(text) = serde_json::to_string(&event.to_frame()) else { continue };
                    if tx.send(WsMessage::Text(text.into())).await.is_err() {
                        break;
                    }
                }
                Err(RecvError::Lagged(_)) => {
                    let _ = tx.send(WsMessage::Close(None)).await;
                    break;
                }
                Err(RecvError::Closed) => break,
            },
            _ = keepalive.tick() => {
                if tx.send(WsMessage::Ping(bytes::Bytes::new())).await.is_err() {
                    break;
                }
            }
            inbound = rx.next() => match inbound {
                Some(Ok(WsMessage::Text(text))) => {
                    if let (Scope::Room(id), Some(active)) = (&scope, parse_client_frame(&text)) {
                        state.chat.set_speaking(connection, id, active);
                    }
                }
                Some(Ok(WsMessage::Close(_)) | Err(_)) | None => break,
                Some(Ok(_)) => {}
            }
        }
    }
    state.chat.drop_connection(connection);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::ChatPrincipal;
    use crate::chat::{ChatEvent, Message, MessageKind, Room};

    fn room(id: &str, agents: &[&str]) -> Room {
        Room {
            id: id.into(),
            name: None,
            agents: agents.iter().map(|agent| (*agent).to_string()).collect(),
            created_at: 0,
            last_message_at: None,
        }
    }

    fn message(room: &str) -> ChatEvent {
        ChatEvent::Message(Message {
            id: 1,
            ts: "1970-01-01T00:00:00Z".into(),
            room: room.into(),
            kind: MessageKind::User,
            sender: "user".into(),
            text: "x".into(),
            input_method: None,
            intent_id: None,
            origin_id: None,
        })
    }

    #[test]
    fn a_scoped_session_sees_only_its_room() {
        let scope = Scope::Room("dm:alice".into());
        let lookup = |id: &str| (id == "dm:alice").then(|| room("dm:alice", &["alice"]));
        assert!(wants(&scope, &ChatPrincipal::User, &message("dm:alice"), lookup));
        assert!(!wants(&scope, &ChatPrincipal::User, &message("dm:bob"), lookup));
    }

    #[test]
    fn an_unscoped_agent_session_sees_its_rooms_as_they_are_now() {
        let scope = Scope::All;
        let lookup = |id: &str| match id {
            "dm:alice" => Some(room("dm:alice", &["alice"])),
            "dm:alice:bob" => Some(room("dm:alice:bob", &["alice", "bob"])),
            _ => None,
        };
        let alice = ChatPrincipal::Agent("alice".into());
        assert!(wants(&scope, &alice, &message("dm:alice:bob"), lookup));
        assert!(!wants(&scope, &ChatPrincipal::Agent("cy".into()), &message("dm:alice:bob"), lookup));
        assert!(!wants(&scope, &alice, &message("gone"), lookup));
        assert!(wants(&scope, &ChatPrincipal::User, &message("dm:alice"), lookup));
    }

    #[test]
    fn only_a_well_formed_speaking_frame_is_read() {
        assert_eq!(parse_client_frame(r#"{"type":"speaking","active":true}"#), Some(true));
        assert_eq!(parse_client_frame(r#"{"type":"speaking","active":false}"#), Some(false));
        assert_eq!(parse_client_frame(r#"{"type":"speaking","active":"yes"}"#), None);
        assert_eq!(parse_client_frame(r#"{"type":"other"}"#), None);
        assert_eq!(parse_client_frame("not json"), None);
    }
}
