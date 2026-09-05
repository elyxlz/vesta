//! The chat routes clients and agents share: rooms, history, intake, and import. Every one reads
//! the `ChatPrincipal` the chat middleware inserted and checks membership itself; the node owns
//! every other decision.

use axum::extract::rejection::JsonRejection;
use axum::extract::{Extension, Path, Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Deserialize;

use crate::auth::ChatPrincipal;
use crate::chat::attachments::MAX_ATTACHMENTS_PER_MESSAGE;
use crate::chat::{
    AttachmentMeta, ChatError, ImportItem, InputMethod, MessageDraft, MessageKind, OpenRoom,
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MAX_TEXT_CHARS, USER_NOTIFICATION_PREVIEW_CHARS, USER_SENDER,
};
use crate::state::SharedState;
use crate::time_utils::{now_epoch_millis, now_epoch_secs};

pub(crate) type ApiError = (StatusCode, Json<serde_json::Value>);

fn error(status: StatusCode, message: impl Into<String>) -> ApiError {
    (status, Json(serde_json::json!({ "error": message.into() })))
}

pub(crate) fn chat_error(err: ChatError) -> ApiError {
    match err {
        ChatError::NotFound => error(StatusCode::NOT_FOUND, "no such room"),
        ChatError::Forbidden => error(StatusCode::FORBIDDEN, "not a member of this room"),
        ChatError::Invalid(reason) => error(StatusCode::BAD_REQUEST, reason),
        ChatError::Speaking(reason) => (
            StatusCode::CONFLICT,
            Json(serde_json::json!({ "error": reason, "user_speaking": true })),
        ),
        ChatError::Burst(reason) => error(StatusCode::TOO_MANY_REQUESTS, reason),
    }
}

fn now_millis() -> u64 {
    u64::try_from(now_epoch_millis()).unwrap_or(u64::MAX)
}

/// The room, once the caller is a member of it.
pub(crate) fn member_room(
    state: &SharedState,
    principal: &ChatPrincipal,
    id: &str,
) -> Result<crate::chat::Room, ApiError> {
    let room = state
        .chat
        .room(id)
        .ok_or_else(|| chat_error(ChatError::NotFound))?;
    if !principal.is_member(&room) {
        return Err(chat_error(ChatError::Forbidden));
    }
    Ok(room)
}

pub(crate) async fn list_rooms_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
) -> Response {
    let rooms = match &principal {
        ChatPrincipal::User => state.chat.rooms_snapshot(),
        ChatPrincipal::Agent(name) => state.chat.rooms_for_agent(name),
    };
    Json(serde_json::json!({ "rooms": rooms })).into_response()
}

#[derive(Deserialize)]
pub(crate) struct OpenRoomBody {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    agents: Vec<String>,
}

pub(crate) async fn open_room_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
    body: Result<Json<OpenRoomBody>, JsonRejection>,
) -> Result<Response, ApiError> {
    let Ok(Json(body)) = body else {
        return Err(error(StatusCode::BAD_REQUEST, "invalid json body"));
    };
    if let ChatPrincipal::Agent(name) = &principal {
        if !body.agents.iter().any(|agent| agent == name) {
            return Err(error(
                StatusCode::FORBIDDEN,
                "an agent may only open rooms it is in",
            ));
        }
    }
    let (room, created) = state
        .chat
        .open_room(
            OpenRoom {
                name: body.name,
                agents: body.agents,
            },
            now_epoch_secs(),
        )
        .map_err(chat_error)?;
    let status = if created {
        StatusCode::CREATED
    } else {
        StatusCode::OK
    };
    Ok((status, Json(serde_json::json!({ "room": room }))).into_response())
}

pub(crate) async fn delete_room_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    if principal != ChatPrincipal::User {
        return Err(error(StatusCode::FORBIDDEN, "only the user deletes rooms"));
    }
    let live = crate::docker::env_file_names(&state.env_config.agents_dir);
    match state.chat.delete_room(&id, &live) {
        Ok(()) => Ok(Json(serde_json::json!({ "ok": true })).into_response()),
        Err(ChatError::Invalid(reason)) => Err(error(StatusCode::CONFLICT, reason)),
        Err(other) => Err(chat_error(other)),
    }
}

#[derive(Deserialize, Default)]
pub(crate) struct HistoryQuery {
    #[serde(default)]
    pub(crate) cursor: Option<String>,
    #[serde(default)]
    pub(crate) after: Option<String>,
    #[serde(default)]
    pub(crate) limit: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum HistoryWalk {
    Page { before: Option<u64>, limit: usize },
    After { after: u64, limit: usize },
}

pub(crate) fn parse_history_query(query: &HistoryQuery) -> Result<HistoryWalk, &'static str> {
    let limit = match &query.limit {
        None => DEFAULT_PAGE_SIZE,
        Some(raw) => raw
            .parse::<usize>()
            .map_err(|_| "invalid limit")?
            .clamp(1, MAX_PAGE_SIZE),
    };
    match (&query.cursor, &query.after) {
        (Some(_), Some(_)) => Err("pass cursor or after, not both"),
        (Some(raw), None) => Ok(HistoryWalk::Page {
            before: Some(raw.parse().map_err(|_| "invalid cursor")?),
            limit,
        }),
        (None, Some(raw)) => Ok(HistoryWalk::After {
            after: raw.parse().map_err(|_| "invalid after")?,
            limit,
        }),
        (None, None) => Ok(HistoryWalk::Page {
            before: None,
            limit,
        }),
    }
}

pub(crate) async fn history_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
    Path(id): Path<String>,
    Query(query): Query<HistoryQuery>,
) -> Result<Response, ApiError> {
    let walk =
        parse_history_query(&query).map_err(|reason| error(StatusCode::BAD_REQUEST, reason))?;
    member_room(&state, &principal, &id)?;
    let (events, cursor) = match walk {
        HistoryWalk::Page { before, limit } => state.chat.page(&id, before, limit),
        HistoryWalk::After { after, limit } => state.chat.after(&id, after, limit),
    };
    Ok(Json(serde_json::json!({ "events": events, "cursor": cursor })).into_response())
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct ValidPost {
    pub(crate) text: String,
    pub(crate) input_method: Option<InputMethod>,
    pub(crate) intent_id: Option<String>,
    /// Ids the caller uploaded; the handler resolves them to metadata before anything lands.
    pub(crate) attachment_ids: Vec<String>,
}

/// Pure shape work over the raw body, mirroring the chat skill's intake rules.
pub(crate) fn validate_post(body: &serde_json::Value) -> Result<ValidPost, String> {
    let shape = "body must be {text?: string, attachments?: [id], input_method?, intent_id?}";
    let attachment_shape = "attachments must be a list of ids";
    let Some(object) = body.as_object() else {
        return Err(shape.into());
    };
    let text = match object.get("text") {
        Some(serde_json::Value::String(text)) => text.trim().to_string(),
        None => String::new(),
        Some(_) => return Err(shape.into()),
    };
    if text.chars().count() > MAX_TEXT_CHARS {
        return Err(format!(
            "message text is capped at {MAX_TEXT_CHARS} characters"
        ));
    }
    let attachment_ids = match object.get("attachments") {
        None => Vec::new(),
        Some(serde_json::Value::Array(items)) => {
            let ids: Vec<String> = items
                .iter()
                .filter_map(serde_json::Value::as_str)
                .map(str::to_string)
                .collect();
            if ids.len() != items.len() {
                return Err(attachment_shape.into());
            }
            ids
        }
        Some(_) => return Err(attachment_shape.into()),
    };
    if attachment_ids.len() > MAX_ATTACHMENTS_PER_MESSAGE {
        return Err(format!(
            "at most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message"
        ));
    }
    // Attachments alone are a message: the text is what may be missing, not both.
    if text.is_empty() && attachment_ids.is_empty() {
        return Err("empty message".into());
    }
    let input_method = match object
        .get("input_method")
        .and_then(serde_json::Value::as_str)
    {
        Some("voice") => Some(InputMethod::Voice),
        Some("typed") => Some(InputMethod::Typed),
        _ => None,
    };
    let intent_id = object
        .get("intent_id")
        .and_then(serde_json::Value::as_str)
        .map(str::to_string);
    Ok(ValidPost {
        text,
        input_method,
        intent_id,
        attachment_ids,
    })
}

pub(crate) async fn post_message_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
    Path(id): Path<String>,
    body: Result<Json<serde_json::Value>, JsonRejection>,
) -> Result<Response, ApiError> {
    let Ok(Json(body)) = body else {
        return Err(error(StatusCode::BAD_REQUEST, "invalid json body"));
    };
    let post = validate_post(&body).map_err(|reason| error(StatusCode::BAD_REQUEST, reason))?;
    // Resolved before any side effect, so a body naming an attachment this node never finalized
    // persists nothing.
    let attachments = post
        .attachment_ids
        .iter()
        .map(|attachment_id| {
            state
                .chat
                .attachments()
                .read_meta(attachment_id)
                .ok_or_else(|| {
                    error(
                        StatusCode::BAD_REQUEST,
                        format!("unknown attachment: {attachment_id}"),
                    )
                })
        })
        .collect::<Result<Vec<AttachmentMeta>, ApiError>>()?;
    member_room(&state, &principal, &id)?;
    if let Some(intent_id) = &post.intent_id {
        if state.chat.intent_seen(intent_id) {
            return Ok(Json(serde_json::json!({ "ok": true, "deduped": true })).into_response());
        }
    }
    let (kind, sender) = match &principal {
        ChatPrincipal::User => (MessageKind::User, USER_SENDER.to_string()),
        ChatPrincipal::Agent(name) => (MessageKind::Chat, name.clone()),
    };
    if kind == MessageKind::Chat {
        state.chat.check_speaking(&id).map_err(chat_error)?;
        state.chat.check_burst(&id).map_err(chat_error)?;
    }
    let message = state.chat.append(MessageDraft {
        room: id,
        kind,
        sender: sender.clone(),
        text: post.text,
        input_method: post.input_method,
        intent_id: post.intent_id.clone(),
        origin_id: None,
        attachments,
        at_ms: now_millis(),
    });
    // Last, so only a message that landed deduplicates its retry.
    if let Some(intent_id) = &post.intent_id {
        state.chat.remember_intent(intent_id);
    }
    if kind == MessageKind::Chat {
        // An attachment-only reply still deserves its notification: fall back to the file names.
        let announced = if message.text.is_empty() {
            let names: Vec<&str> = message
                .attachments
                .iter()
                .map(|meta| meta.name.as_str())
                .collect();
            names.join(", ")
        } else {
            message.text.clone()
        };
        let preview: String = announced
            .chars()
            .take(USER_NOTIFICATION_PREVIEW_CHARS)
            .collect();
        state.user_notifier().await.notify(
            &sender,
            crate::user_notifications::KIND_MESSAGE,
            sender.clone(),
            preview,
        );
    }
    Ok(Json(serde_json::json!({ "ok": true, "id": message.id })).into_response())
}

#[derive(Deserialize)]
pub(crate) struct ImportBody {
    messages: Vec<ImportBodyItem>,
}

#[derive(Deserialize)]
pub(crate) struct ImportBodyItem {
    origin_id: u64,
    ts: String,
    #[serde(rename = "type")]
    kind: MessageKind,
    text: String,
    #[serde(default)]
    input_method: Option<InputMethod>,
    #[serde(default)]
    attachments: Option<Vec<String>>,
}

pub(crate) async fn import_handler(
    State(state): State<SharedState>,
    Extension(principal): Extension<ChatPrincipal>,
    Path(id): Path<String>,
    body: Result<Json<ImportBody>, JsonRejection>,
) -> Result<Response, ApiError> {
    let Ok(Json(body)) = body else {
        return Err(error(StatusCode::BAD_REQUEST, "invalid json body"));
    };
    let ChatPrincipal::Agent(agent) = principal else {
        return Err(error(
            StatusCode::FORBIDDEN,
            "only an agent imports its own history",
        ));
    };
    if id != crate::chat::Room::direct_id(&agent) {
        return Err(error(
            StatusCode::FORBIDDEN,
            "an agent imports only into its direct room",
        ));
    }
    if state.chat.room(&id).is_none() {
        return Err(chat_error(ChatError::NotFound));
    }
    // Every stamp is parsed before anything lands, so a batch carrying one unreadable stamp is
    // refused whole rather than imported with that message stamped at the epoch.
    let items: Vec<ImportItem> = body
        .messages
        .into_iter()
        .map(|item| {
            let at_ms = crate::chat::parse_ts(&item.ts).ok_or(item.origin_id)?;
            Ok(ImportItem {
                origin_id: item.origin_id,
                at_ms,
                kind: item.kind,
                text: item.text,
                input_method: item.input_method,
                attachments: item.attachments.unwrap_or_default(),
            })
        })
        .collect::<Result<Vec<ImportItem>, u64>>()
        .map_err(|origin_id| {
            error(
                StatusCode::BAD_REQUEST,
                format!("invalid ts on origin_id {origin_id}"),
            )
        })?;
    let outcome = state.chat.import(&id, items);
    Ok(
        Json(serde_json::json!({ "imported": outcome.imported, "skipped": outcome.skipped }))
            .into_response(),
    )
}

/// The other agents on this gateway, for `chat peers`.
pub(crate) async fn peers_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> Response {
    let peers: Vec<String> = state
        .chat
        .known_agents()
        .into_iter()
        .filter(|agent| *agent != name)
        .collect();
    Json(serde_json::json!({ "peers": peers })).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_post_body_is_validated_into_text_and_options() {
        let body =
            serde_json::json!({ "text": "  hi  ", "input_method": "voice", "intent_id": "c-1" });
        let post = validate_post(&body).expect("valid");
        assert_eq!(post.text, "hi");
        assert_eq!(post.input_method, Some(crate::chat::InputMethod::Voice));
        assert_eq!(post.intent_id.as_deref(), Some("c-1"));
        assert_eq!(
            validate_post(&serde_json::json!({ "text": "   " })).expect_err("empty"),
            "empty message"
        );
        assert_eq!(
            validate_post(&serde_json::json!({ "text": 5 })).expect_err("shape"),
            "body must be {text?: string, attachments?: [id], input_method?, intent_id?}"
        );
        let long = serde_json::json!({ "text": "x".repeat(crate::chat::MAX_TEXT_CHARS + 1) });
        assert_eq!(
            validate_post(&long).expect_err("long"),
            "message text is capped at 65536 characters"
        );
        let odd_method = serde_json::json!({ "text": "hi", "input_method": "telepathy" });
        assert_eq!(
            validate_post(&odd_method)
                .expect("odd method is dropped")
                .input_method,
            None
        );
        let attachment_only = serde_json::json!({ "attachments": ["a", "b"] });
        let post = validate_post(&attachment_only).expect("attachments carry an empty text");
        assert_eq!(post.text, "");
        assert_eq!(post.attachment_ids, vec!["a".to_string(), "b".to_string()]);
        assert_eq!(
            validate_post(&serde_json::json!({ "text": "", "attachments": [] }))
                .expect_err("nothing at all"),
            "empty message"
        );
        assert_eq!(
            validate_post(&serde_json::json!({ "attachments": "x" })).expect_err("not a list"),
            "attachments must be a list of ids"
        );
        assert_eq!(
            validate_post(&serde_json::json!({ "attachments": ["a", 2] })).expect_err("not ids"),
            "attachments must be a list of ids"
        );
        let ids: Vec<String> = (0..=MAX_ATTACHMENTS_PER_MESSAGE)
            .map(|index| index.to_string())
            .collect();
        assert_eq!(
            validate_post(&serde_json::json!({ "text": "hi", "attachments": ids }))
                .expect_err("too many"),
            "at most 10 attachments per message"
        );
    }

    #[test]
    fn history_query_resolves_a_page_size_and_one_cursor_kind() {
        assert_eq!(
            parse_history_query(&HistoryQuery::default()).expect("default"),
            HistoryWalk::Page {
                before: None,
                limit: crate::chat::DEFAULT_PAGE_SIZE
            }
        );
        let query = HistoryQuery {
            cursor: Some("12".into()),
            after: None,
            limit: Some("9000".into()),
        };
        assert_eq!(
            parse_history_query(&query).expect("clamped"),
            HistoryWalk::Page {
                before: Some(12),
                limit: crate::chat::MAX_PAGE_SIZE
            }
        );
        let query = HistoryQuery {
            cursor: None,
            after: Some("3".into()),
            limit: Some("2".into()),
        };
        assert_eq!(
            parse_history_query(&query).expect("after"),
            HistoryWalk::After { after: 3, limit: 2 }
        );
        let both = HistoryQuery {
            cursor: Some("1".into()),
            after: Some("1".into()),
            limit: None,
        };
        assert_eq!(
            parse_history_query(&both).expect_err("both"),
            "pass cursor or after, not both"
        );
        let bad = HistoryQuery {
            cursor: Some("x".into()),
            after: None,
            limit: None,
        };
        assert_eq!(
            parse_history_query(&bad).expect_err("cursor"),
            "invalid cursor"
        );
        let bad = HistoryQuery {
            cursor: None,
            after: None,
            limit: Some("-1".into()),
        };
        assert_eq!(
            parse_history_query(&bad).expect_err("limit"),
            "invalid limit"
        );
        let none = HistoryQuery {
            cursor: None,
            after: None,
            limit: Some("0".into()),
        };
        assert_eq!(
            parse_history_query(&none).expect("zero"),
            HistoryWalk::Page {
                before: None,
                limit: 1
            },
            "a zero page size reads as one, never as an empty page"
        );
    }
}
