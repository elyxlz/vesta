//! The attachment surface: an upload session, its offset-addressed chunks, and the blob read.
//! Every route reads the store the node owns; the policy here is what a browser is told about a
//! blob, since the declared mime is caller input and only media may render inline.

use std::str::FromStr;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query, State};
use axum::http::header::{
    HeaderName, HeaderValue, CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_SECURITY_POLICY,
    X_CONTENT_TYPE_OPTIONS,
};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Deserialize;
use tower::ServiceExt;
use tower_http::services::ServeFile;

use crate::chat::attachments::{valid_mime, AttachmentError, MetaExtra};
use crate::chat::routes::{error, ApiError};
use crate::state::SharedState;

/// How long a client may cache a blob. Not forever: a blob a sweep freed must be able to surface
/// its 410 on a client that already viewed it.
const ATTACHMENT_CACHE_MAX_AGE_SECS: u64 = 3600;
const INLINE_MIME_PREFIXES: [&str; 3] = ["image/", "video/", "audio/"];
const INLINE_MIMES: [&str; 1] = ["application/pdf"];
const OPAQUE_MIME: &str = "application/octet-stream";
/// What the ascii fallback reads as when the real name holds no ascii at all.
const ASCII_FALLBACK_NAME: &str = "file";
const CREATE_SHAPE: &str = "body must be {name, mime, size}";
const HEX_DIGITS: &[u8; 16] = b"0123456789ABCDEF";

fn attachment_error(err: &AttachmentError) -> ApiError {
    match err {
        AttachmentError::Unknown => error(StatusCode::NOT_FOUND, err.to_string()),
        AttachmentError::Size(_) => error(StatusCode::PAYLOAD_TOO_LARGE, err.to_string()),
        AttachmentError::SizeMismatch { .. } => error(StatusCode::CONFLICT, err.to_string()),
        AttachmentError::Offset { received } => (
            StatusCode::CONFLICT,
            Json(serde_json::json!({ "error": "offset mismatch", "received": received })),
        ),
    }
}

#[derive(Debug, PartialEq)]
pub(crate) struct ValidCreate {
    name: String,
    mime: String,
    size: u64,
    extra: MetaExtra,
}

/// Pure shape work over the raw body, mirroring the chat skill's create rules: the three declared
/// fields are required, and an optional dimension that is present but mistyped is dropped.
pub(crate) fn validate_create(body: &serde_json::Value) -> Result<ValidCreate, String> {
    let Some(object) = body.as_object() else {
        return Err(CREATE_SHAPE.into());
    };
    let (Some(name), Some(mime), Some(size)) = (
        object.get("name").and_then(serde_json::Value::as_str),
        object.get("mime").and_then(serde_json::Value::as_str),
        object.get("size").and_then(serde_json::Value::as_u64),
    ) else {
        return Err(CREATE_SHAPE.into());
    };
    // The declared mime later becomes a response header, so a control character there would make
    // the blob permanently unservable; refuse it at the door.
    if !valid_mime(mime) {
        return Err("invalid mime type".into());
    }
    let dimension = |field: &str| {
        object
            .get(field)
            .and_then(serde_json::Value::as_u64)
            .and_then(|value| u32::try_from(value).ok())
    };
    Ok(ValidCreate {
        name: name.to_string(),
        mime: mime.to_string(),
        size,
        extra: MetaExtra {
            width: dimension("width"),
            height: dimension("height"),
            duration_secs: object
                .get("duration_secs")
                .and_then(serde_json::Value::as_f64),
        },
    })
}

pub(crate) async fn create_attachment_handler(
    State(state): State<SharedState>,
    body: Result<Json<serde_json::Value>, JsonRejection>,
) -> Result<Response, ApiError> {
    let Ok(Json(body)) = body else {
        return Err(error(StatusCode::BAD_REQUEST, "invalid json body"));
    };
    let create = validate_create(&body).map_err(|reason| error(StatusCode::BAD_REQUEST, reason))?;
    let id = state
        .chat
        .attachments()
        .create_session(&create.name, &create.mime, create.size, create.extra)
        .map_err(|err| attachment_error(&err))?;
    Ok(Json(serde_json::json!({ "id": id })).into_response())
}

#[derive(Deserialize)]
pub(crate) struct DataQuery {
    #[serde(default)]
    offset: Option<String>,
}

/// Append one chunk at an explicit offset. A 409 carries the staged size so the client resyncs; a
/// replayed chunk whose bytes already landed reads `received == offset + len` as delivered.
pub(crate) async fn attachment_data_handler(
    State(state): State<SharedState>,
    Path(id): Path<String>,
    Query(query): Query<DataQuery>,
    body: bytes::Bytes,
) -> Result<Response, ApiError> {
    let Some(offset) = query.offset.and_then(|raw| raw.parse::<u64>().ok()) else {
        return Err(error(StatusCode::BAD_REQUEST, "invalid offset"));
    };
    let received = state
        .chat
        .attachments()
        .append_at(&id, offset, &body)
        .map_err(|err| attachment_error(&err))?;
    Ok(Json(serde_json::json!({ "ok": true, "received": received })).into_response())
}

/// The resume probe: where to continue after a connection gap.
pub(crate) async fn attachment_status_handler(
    State(state): State<SharedState>,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    let (received, size, finalized) = state
        .chat
        .attachments()
        .upload_status(&id)
        .map_err(|err| attachment_error(&err))?;
    Ok(
        Json(serde_json::json!({ "received": received, "size": size, "finalized": finalized }))
            .into_response(),
    )
}

/// Finalize a fully staged upload. Idempotent, so a lost response is retried safely.
pub(crate) async fn complete_attachment_handler(
    State(state): State<SharedState>,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    let meta = state
        .chat
        .attachments()
        .finalize(&id)
        .map_err(|err| attachment_error(&err))?;
    Ok(Json(serde_json::json!({ "attachment": meta })).into_response())
}

/// Percent-encode over the RFC 3986 unreserved set, which is what `filename*` carries.
fn percent_encode(name: &str) -> String {
    let mut encoded = String::with_capacity(name.len());
    for byte in name.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            encoded.push(char::from(byte));
        } else {
            encoded.push('%');
            encoded.push(char::from(HEX_DIGITS[usize::from(byte >> 4)]));
            encoded.push(char::from(HEX_DIGITS[usize::from(byte & 0x0f)]));
        }
    }
    encoded
}

/// RFC 6266/5987: an ascii fallback plus the percent-encoded real name, so a unicode filename
/// survives every browser instead of being mangled or truncated at a semicolon.
pub(crate) fn content_disposition(kind: &str, name: &str) -> String {
    let stripped: String = name
        .chars()
        .filter(|character| character.is_ascii() && !matches!(character, '"' | ';' | '\\'))
        .collect();
    let fallback = if stripped.is_empty() {
        ASCII_FALLBACK_NAME
    } else {
        &stripped
    };
    format!(
        "{kind}; filename=\"{fallback}\"; filename*=UTF-8''{}",
        percent_encode(name)
    )
}

/// Whether the blob renders inline, and the content type it is served as. The declared mime is
/// caller input, so anything but media downloads as an opaque stream.
pub(crate) fn inline_policy(mime: &str, download: bool) -> (bool, &str) {
    let inline_safe = INLINE_MIME_PREFIXES
        .iter()
        .any(|prefix| mime.starts_with(prefix))
        || INLINE_MIMES.contains(&mime);
    let content_type = if inline_safe { mime } else { OPAQUE_MIME };
    (inline_safe && !download, content_type)
}

#[derive(Deserialize)]
pub(crate) struct ServeQuery {
    #[serde(default)]
    download: Option<String>,
}

fn insert_header(response: &mut Response, name: HeaderName, value: &str) {
    if let Ok(header) = HeaderValue::from_str(value) {
        response.headers_mut().insert(name, header);
    }
}

/// Stream a finalized blob. `ServeFile` answers Range natively, so video seeking is free. A blob a
/// sweep freed keeps its meta and answers 410, which clients render as a terminal tile.
pub(crate) async fn serve_attachment_handler(
    State(state): State<SharedState>,
    Path(id): Path<String>,
    Query(query): Query<ServeQuery>,
    request: axum::extract::Request,
) -> Result<Response, ApiError> {
    let store = state.chat.attachments();
    let Some(meta) = store.read_meta(&id) else {
        return Err(error(StatusCode::NOT_FOUND, "unknown attachment"));
    };
    let path = store.root().join(&id).join(&meta.name);
    if !path.exists() {
        return Err(error(StatusCode::GONE, "attachment removed"));
    }
    let (inline, content_type) = inline_policy(&meta.mime, query.download.as_deref() == Some("1"));
    let served_as =
        mime::Mime::from_str(content_type).unwrap_or(mime::APPLICATION_OCTET_STREAM.clone());
    let served = match ServeFile::new_with_mime(&path, &served_as)
        .oneshot(request)
        .await
    {
        Ok(response) => response,
        Err(infallible) => match infallible {},
    };
    let mut response = served.map(axum::body::Body::new);
    let kind = if inline { "inline" } else { "attachment" };
    insert_header(
        &mut response,
        CONTENT_DISPOSITION,
        &content_disposition(kind, &meta.name),
    );
    insert_header(&mut response, X_CONTENT_TYPE_OPTIONS, "nosniff");
    insert_header(&mut response, CONTENT_SECURITY_POLICY, "sandbox");
    insert_header(
        &mut response,
        CACHE_CONTROL,
        &format!("private, max-age={ATTACHMENT_CACHE_MAX_AGE_SECS}"),
    );
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_disposition_carries_an_ascii_fallback_and_the_encoded_real_name() {
        assert_eq!(
            content_disposition("inline", "résumé; \"final\".pdf"),
            "inline; filename=\"rsum final.pdf\"; filename*=UTF-8''r%C3%A9sum%C3%A9%3B%20%22final%22.pdf"
        );
        assert_eq!(
            content_disposition("attachment", "\u{4f60}"),
            "attachment; filename=\"file\"; filename*=UTF-8''%E4%BD%A0"
        );
    }

    #[test]
    fn only_media_serves_inline_and_a_download_asks_for_the_file() {
        assert_eq!(inline_policy("image/png", false), (true, "image/png"));
        assert_eq!(
            inline_policy("text/html", false),
            (false, "application/octet-stream")
        );
        assert_eq!(
            inline_policy("application/pdf", true),
            (false, "application/pdf")
        );
    }

    #[test]
    fn a_create_body_declares_a_name_a_mime_and_a_size() {
        let body = serde_json::json!({
            "name": "clip.mp4", "mime": "video/mp4", "size": 12,
            "width": 1920, "height": 1080, "duration_secs": 2.5
        });
        assert_eq!(
            validate_create(&body).expect("valid"),
            ValidCreate {
                name: "clip.mp4".into(),
                mime: "video/mp4".into(),
                size: 12,
                extra: MetaExtra {
                    width: Some(1920),
                    height: Some(1080),
                    duration_secs: Some(2.5),
                },
            }
        );
        assert_eq!(
            validate_create(&serde_json::json!({ "name": "a", "mime": "text/plain" }))
                .expect_err("no size"),
            CREATE_SHAPE
        );
        assert_eq!(
            validate_create(&serde_json::json!({ "name": "a", "mime": "text/plain", "size": -1 }))
                .expect_err("negative size"),
            CREATE_SHAPE
        );
        assert_eq!(
            validate_create(&serde_json::json!({ "name": "a", "mime": "plain", "size": 1 }))
                .expect_err("mime"),
            "invalid mime type"
        );
        assert_eq!(
            validate_create(&serde_json::json!({
                "name": "a", "mime": "text/plain", "size": 1, "width": "wide"
            }))
            .expect("a mistyped dimension is dropped")
            .extra,
            MetaExtra::default()
        );
    }
}
