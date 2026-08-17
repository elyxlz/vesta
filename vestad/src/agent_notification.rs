//! vestad-authored notifications into an agent's intake (`~/agent/notifications/`), the one owner
//! of their envelope and file name. Every kind (`rename`, `user-presence`, `user-timezone`,
//! `user-location`) is the same outer shape, `{timestamp, source: "vestad", type, interrupt}` plus
//! its own fields, written under `{kind}-{millis}.json`, so a fifth kind adds fields and nothing
//! else. The millisecond in the name keeps two notifications minted inside one second (every client
//! replaying after a gateway restart) from overwriting each other in the intake.

use crate::docker;
use crate::time_utils::{epoch_to_rfc3339, now_epoch_millis};

const INTAKE_DIR: &str = "/root/agent/notifications";

/// One notification's own content: its kind, whether it interrupts the agent's turn (`false`
/// snoozes it until idle, overridable by the user's `notification_rules`), and its fields.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct AgentNotification {
    pub kind: &'static str,
    pub interrupt: bool,
    pub fields: serde_json::Map<String, serde_json::Value>,
}

impl AgentNotification {
    /// The wire envelope around the fields, stamped with `epoch_secs`. Pure so every kind's shape
    /// is asserted without a container.
    pub(crate) fn envelope(&self, epoch_secs: u64) -> Result<serde_json::Value, String> {
        let mut payload = serde_json::Map::new();
        payload.insert("timestamp".into(), epoch_to_rfc3339(epoch_secs)?.into());
        payload.insert("source".into(), "vestad".into());
        payload.insert("type".into(), self.kind.into());
        payload.insert("interrupt".into(), self.interrupt.into());
        payload.extend(self.fields.clone());
        Ok(serde_json::Value::Object(payload))
    }
}

/// The intake file name for a notification minted at `epoch_millis`.
pub(crate) fn file_name(kind: &str, epoch_millis: u128) -> String {
    format!("{kind}-{epoch_millis}.json")
}

/// Write `notification` into `agent`'s intake, stamped now. Best-effort: the caller decides
/// whether a failure is fatal. Returns the file name written.
pub(crate) async fn drop(
    docker: &bollard::Docker,
    agent: &str,
    notification: &AgentNotification,
) -> Result<String, String> {
    let millis = now_epoch_millis();
    let secs = u64::try_from(millis / 1000).map_err(|error| format!("clock out of range: {error}"))?;
    let payload = notification.envelope(secs)?;
    let name = file_name(notification.kind, millis);
    let bytes = serde_json::to_vec(&payload).map_err(|error| format!("serialize notification: {error}"))?;
    docker::upload_to_container(docker, &docker::container_name(agent), INTAKE_DIR, &name, &bytes)
        .await
        .map_err(|error| error.to_string())?;
    Ok(name)
}

/// The fields of a `serde_json::json!` object literal, for building a notification's own content.
pub(crate) fn fields(value: serde_json::Value) -> serde_json::Map<String, serde_json::Value> {
    match value {
        serde_json::Value::Object(map) => map,
        _ => serde_json::Map::new(),
    }
}

/// The rename notification: high priority, so the renamed agent self-updates MEMORY.md and
/// anything else that references its old name.
pub(crate) fn rename(old_name: &str, new_name: &str) -> AgentNotification {
    AgentNotification {
        kind: "rename",
        interrupt: true,
        fields: fields(serde_json::json!({
            "old_name": old_name,
            "new_name": new_name,
            "message": format!(
                "you have been renamed from '{old_name}' to '{new_name}'. \
                 AGENT_NAME is now '{new_name}'. update your MEMORY.md and anything else \
                 that references your old name."
            ),
        })),
    }
}

/// The presence notification: the user just opened this agent's page on a client. Snoozed
/// (ambient presence).
pub(crate) fn user_presence(client: crate::types::ClientKind) -> AgentNotification {
    let client = client.display_name();
    AgentNotification {
        kind: "user-presence",
        interrupt: false,
        fields: fields(serde_json::json!({
            "message": format!("the user just opened your page on {client} and is here now."),
        })),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_wraps_the_fields_with_the_shared_outer_shape() {
        let notification = AgentNotification {
            kind: "user-presence",
            interrupt: false,
            fields: fields(serde_json::json!({ "message": "hello" })),
        };
        let payload = notification.envelope(1_700_000_000).expect("payload");
        assert_eq!(
            payload,
            serde_json::json!({
                "timestamp": "2023-11-14T22:13:20Z",
                "source": "vestad",
                "type": "user-presence",
                "interrupt": false,
                "message": "hello",
            })
        );
    }

    #[test]
    fn file_name_carries_kind_and_millisecond() {
        assert_eq!(file_name("user-timezone", 1_700_000_000_123), "user-timezone-1700000000123.json");
    }

    #[test]
    fn rename_carries_both_names_and_interrupts() {
        let payload = rename("old-bot", "new-bot").envelope(1_700_000_000).expect("payload");
        assert_eq!(payload["type"], "rename");
        assert_eq!(payload["interrupt"], true);
        assert_eq!(payload["old_name"], "old-bot");
        assert_eq!(payload["new_name"], "new-bot");
        let message = payload["message"].as_str().expect("message");
        assert!(message.contains("old-bot") && message.contains("new-bot"), "message: {message}");
    }

    #[test]
    fn user_presence_is_snoozed_and_names_the_client() {
        let payload = user_presence(crate::types::ClientKind::Web).envelope(1_700_000_000).expect("payload");
        assert_eq!(payload["type"], "user-presence");
        assert_eq!(payload["interrupt"], false);
        assert_eq!(payload["message"], "the user just opened your page on Vesta Web App and is here now.");
    }
}
