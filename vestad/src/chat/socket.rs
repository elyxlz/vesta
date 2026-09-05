//! The chat live-edge socket: one session per connection, filtered to the rooms it may read.
//! `/rooms/ws` is the replay-free live edge of one room (a client) or of every room the caller is
//! in (an agent's daemon). Inbound carries the speaking report; a lagging session is closed so its
//! client reseeds by id.

use std::time::Duration;

use axum::extract::ws::{Message as WsMessage, WebSocket, WebSocketUpgrade};
use axum::extract::{Extension, Query, State};
use axum::response::{IntoResponse, Response};
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use tokio::sync::broadcast::error::RecvError;

use crate::auth::ChatPrincipal;
use crate::chat::routes::member_room;
use crate::chat::{ChatEvent, Room};
use crate::state::{SharedState, WS_KEEPALIVE_INTERVAL_SECS};

/// How long one outbound frame may take before the session is abandoned.
pub(crate) const WS_SEND_TIMEOUT_SECS: u64 = 10;

type Sender = futures_util::stream::SplitSink<WebSocket, WsMessage>;

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
        // A deletion outlives the room it names, so the lookup can no longer answer for it and a
        // replica must drop it; an id the reader never held is a no-op there.
        Scope::All if matches!(event, ChatEvent::RoomDeleted { .. }) => true,
        Scope::All => lookup(room_id).is_some_and(|room| principal.is_member(&room)),
    }
}

/// Send one frame under a deadline. A client that stops reading must never pin the session: its
/// speaking flag would refuse every agent post in that room until the OS dropped the socket.
async fn send_bounded(tx: &mut Sender, message: WsMessage) -> bool {
    let deadline = Duration::from_secs(WS_SEND_TIMEOUT_SECS);
    matches!(
        tokio::time::timeout(deadline, tx.send(message)).await,
        Ok(Ok(()))
    )
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
        Some(id) => match member_room(&state, &principal, &id) {
            Err(api_error) => return api_error.into_response(),
            Ok(_) => Scope::Room(id),
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
                    if !send_bounded(&mut tx, WsMessage::Text(text.into())).await {
                        break;
                    }
                }
                Err(RecvError::Lagged(_)) => {
                    send_bounded(&mut tx, WsMessage::Close(None)).await;
                    break;
                }
                Err(RecvError::Closed) => break,
            },
            _ = keepalive.tick() => {
                if !send_bounded(&mut tx, WsMessage::Ping(bytes::Bytes::new())).await {
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
        assert!(wants(
            &scope,
            &ChatPrincipal::User,
            &message("dm:alice"),
            lookup
        ));
        assert!(!wants(
            &scope,
            &ChatPrincipal::User,
            &message("dm:bob"),
            lookup
        ));
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
        assert!(!wants(
            &scope,
            &ChatPrincipal::Agent("cy".into()),
            &message("dm:alice:bob"),
            lookup
        ));
        assert!(!wants(&scope, &alice, &message("gone"), lookup));
        assert!(wants(
            &scope,
            &ChatPrincipal::User,
            &message("dm:alice"),
            lookup
        ));
    }

    #[test]
    fn an_unscoped_session_hears_a_deletion_of_a_room_that_is_already_gone() {
        let alice = ChatPrincipal::Agent("alice".into());
        let deleted = ChatEvent::RoomDeleted {
            room: "gone".into(),
        };
        assert!(wants(&Scope::All, &alice, &deleted, |_| None));
        assert!(!wants(&Scope::All, &alice, &message("gone"), |_| None));
    }

    #[test]
    fn only_a_well_formed_speaking_frame_is_read() {
        assert_eq!(
            parse_client_frame(r#"{"type":"speaking","active":true}"#),
            Some(true)
        );
        assert_eq!(
            parse_client_frame(r#"{"type":"speaking","active":false}"#),
            Some(false)
        );
        assert_eq!(
            parse_client_frame(r#"{"type":"speaking","active":"yes"}"#),
            None
        );
        assert_eq!(parse_client_frame(r#"{"type":"other"}"#), None);
        assert_eq!(parse_client_frame("not json"), None);
    }
}
