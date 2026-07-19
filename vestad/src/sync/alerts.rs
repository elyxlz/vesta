//! The single owner of "is this live agent event notification-worthy, and what is its preview?".
//! Both the web toast (the `/sync` `alert` delta) and mobile push read this one decision, so
//! notification-worthiness never drifts between clients.

use serde_json::Value;

/// Longest preview text carried in an alert; longer text is truncated with an ellipsis.
const MAX_PREVIEW_CHARS: usize = 180;

/// A live event judged notification-worthy, plus the user-facing preview to show.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AlertPayload {
    pub preview: String,
}

/// Decide whether a live agent event should surface as a user-facing alert and render its preview.
/// Only `chat` (the agent's message, truncated) and `rate_limited` (its text) qualify; everything
/// else, including high-frequency `status` activity frames, yields None.
pub(crate) fn alert_for(event: &Value) -> Option<AlertPayload> {
    let text = event.get("text")?.as_str()?;
    match event.get("type")?.as_str()? {
        "chat" => Some(AlertPayload { preview: truncate_preview(text) }),
        "rate_limited" => Some(AlertPayload { preview: text.to_string() }),
        _ => None,
    }
}

fn truncate_preview(value: &str) -> String {
    let mut preview: String = value.chars().take(MAX_PREVIEW_CHARS).collect();
    if value.chars().count() > MAX_PREVIEW_CHARS {
        preview.push('…');
    }
    preview
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chat_is_worthy_with_a_truncated_preview() {
        let long = "x".repeat(MAX_PREVIEW_CHARS + 20);
        let alert = alert_for(&serde_json::json!({ "type": "chat", "text": long })).expect("chat alert");
        assert_eq!(alert.preview.chars().count(), MAX_PREVIEW_CHARS + 1); // truncated + the ellipsis
        assert!(alert.preview.ends_with('…'));

        let short = alert_for(&serde_json::json!({ "type": "chat", "text": "hi there" })).expect("chat alert");
        assert_eq!(short.preview, "hi there");
    }

    #[test]
    fn rate_limited_is_worthy_with_its_verbatim_text() {
        let alert = alert_for(&serde_json::json!({ "type": "rate_limited", "text": "usage limit reached" }))
            .expect("rate_limited alert");
        assert_eq!(alert.preview, "usage limit reached");
    }

    #[test]
    fn activity_and_other_events_are_never_worthy() {
        for event in [
            serde_json::json!({ "type": "status", "state": "thinking" }),
            serde_json::json!({ "type": "tool_start", "tool": "bash", "text": "ignored" }),
            serde_json::json!({ "type": "notification", "source": "sms", "summary": "hi" }),
            serde_json::json!({ "type": "chat" }),
        ] {
            assert!(alert_for(&event).is_none(), "unexpected alert for {event}");
        }
    }
}
