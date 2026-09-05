//! The chat node: rooms, an append-only message log, the live edge, and the routes clients and
//! agents share. `ChatNode` is the one owner of chat state on `AppState`; the store below it is
//! two files under `<config_dir>/chat/`, held in memory.

pub(crate) mod attachments;
pub(crate) mod node;
pub(crate) mod routes;
pub(crate) mod socket;
pub(crate) mod store;

use serde::{Deserialize, Serialize};

pub(crate) use attachments::AttachmentMeta;
pub(crate) use node::{ChatError, ChatNode, ImportItem, OpenRoom};

/// The longest message text intake accepts, in characters.
pub(crate) const MAX_TEXT_CHARS: usize = 64 * 1024;
/// How many recent client intent ids intake remembers for retry dedup.
pub(crate) const SEEN_INTENT_IDS_CAP: usize = 256;
/// The live-edge broadcast depth; a session that lags past it is closed so its client reseeds.
pub(crate) const CHAT_EVENT_BROADCAST_CAPACITY: usize = 1024;
/// Agent messages a room may hold since the user's last message before agent posts are refused.
pub(crate) const ROOM_AGENT_POSTS_WITHOUT_USER: usize = 40;
pub(crate) const DEFAULT_PAGE_SIZE: usize = 50;
pub(crate) const MAX_PAGE_SIZE: usize = 500;
pub(crate) const ROOM_NAME_MAX_CHARS: usize = 80;
pub(crate) const USER_NOTIFICATION_PREVIEW_CHARS: usize = 180;
pub(crate) const USER_SENDER: &str = "user";

pub(crate) const SPEAKING_REFUSAL: &str =
    "the user is talking right now: drop this reply, wait for their next message, then answer the whole thought";
pub(crate) const BURST_REFUSAL: &str =
    "burst guard: this room holds 40 agent messages since the user last spoke; stop until the user writes again";

/// A conversation: its agents, and the user, who is a member of every room.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Room {
    pub id: String,
    pub name: Option<String>,
    pub agents: Vec<String>,
    /// Unix seconds.
    pub created_at: u64,
    /// Unix seconds of the newest message, absent while the room is empty.
    pub last_message_at: Option<u64>,
}

impl Room {
    pub(crate) fn direct_id(agent: &str) -> String {
        format!("dm:{agent}")
    }

    pub(crate) fn peer_id(first: &str, second: &str) -> String {
        let mut pair = [first, second];
        pair.sort_unstable();
        format!("dm:{}:{}", pair[0], pair[1])
    }

    pub(crate) fn is_direct(&self) -> bool {
        self.name.is_none() && self.agents.len() == 1 && self.id == Self::direct_id(&self.agents[0])
    }

    pub(crate) fn has_agent(&self, agent: &str) -> bool {
        self.agents.iter().any(|member| member == agent)
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum MessageKind {
    User,
    Chat,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum InputMethod {
    Voice,
    Typed,
}

/// One message as the history page and the socket carry it. Field names mirror the chat skill's
/// event wire, which is why this struct is `snake_case` while `Room` is camelCase like the tree.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
pub(crate) struct Message {
    pub id: u64,
    /// RFC 3339 UTC with millisecond precision.
    pub ts: String,
    pub room: String,
    #[serde(rename = "type")]
    pub kind: MessageKind,
    pub sender: String,
    pub text: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub input_method: Option<InputMethod>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intent_id: Option<String>,
    /// The agent's local id of an imported message, so a re-import skips what already landed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub origin_id: Option<u64>,
}

/// What `ChatNode::append` takes: everything but the id and the formatted stamp.
#[derive(Debug, Clone)]
pub(crate) struct MessageDraft {
    pub room: String,
    pub kind: MessageKind,
    pub sender: String,
    pub text: String,
    pub input_method: Option<InputMethod>,
    pub intent_id: Option<String>,
    pub origin_id: Option<u64>,
    /// Unix milliseconds.
    pub at_ms: u64,
}

/// One live-edge event. A message serializes as itself; the room events carry a `type` tag.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ChatEvent {
    Message(Message),
    RoomCreated(Room),
    RoomDeleted { room: String },
    UserFinishedTalking { room: String },
}

impl ChatEvent {
    pub(crate) fn room_id(&self) -> &str {
        match self {
            Self::Message(message) => &message.room,
            Self::RoomCreated(room) => &room.id,
            Self::RoomDeleted { room } | Self::UserFinishedTalking { room } => room,
        }
    }

    pub(crate) fn to_frame(&self) -> serde_json::Value {
        match self {
            Self::Message(message) => {
                serde_json::to_value(message).unwrap_or(serde_json::Value::Null)
            }
            Self::RoomCreated(room) => serde_json::json!({ "type": "room_created", "room": room }),
            Self::RoomDeleted { room } => {
                serde_json::json!({ "type": "room_deleted", "room": room })
            }
            Self::UserFinishedTalking { room } => {
                serde_json::json!({ "type": "user_finished_talking", "room": room })
            }
        }
    }
}

/// RFC 3339 UTC with millisecond precision, the stamp every message carries.
pub(crate) fn format_ts(at_ms: u64) -> String {
    let nanos = i128::from(at_ms) * 1_000_000;
    time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .ok()
        .and_then(|stamp| {
            stamp
                .format(&time::format_description::well_known::Rfc3339)
                .ok()
        })
        .unwrap_or_default()
}

/// The inverse of `format_ts`, accepting any RFC 3339 stamp (an agent's local store writes
/// microseconds and a `+00:00` offset).
pub(crate) fn parse_ts(ts: &str) -> Option<u64> {
    let stamp =
        time::OffsetDateTime::parse(ts, &time::format_description::well_known::Rfc3339).ok()?;
    u64::try_from(stamp.unix_timestamp_nanos() / 1_000_000).ok()
}
