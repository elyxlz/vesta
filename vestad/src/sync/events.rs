use std::collections::HashMap;

use serde_json::Value;

/// The agent's live activity state, present on both a `status` event and the connect `snapshot`
/// frame (top-level `state`). Keeps the roster's activityState fresh.
pub(crate) fn activity_state(frame: &Value) -> Option<String> {
    frame.get("state")?.as_str().map(str::to_string)
}

/// A change to an agent's pending-notification set derived from a live event. `notification` adds
/// (or refreshes) a pending entry; `notification_cleared` removes one. Any other type yields None.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum NotificationChange {
    Added { notif_id: String, event: Value },
    Cleared { notif_id: String },
}

pub(crate) fn notification_change(event: &Value) -> Option<NotificationChange> {
    match event.get("type")?.as_str()? {
        "notification" => Some(NotificationChange::Added {
            notif_id: event.get("notif_id")?.as_str()?.to_string(),
            event: event.clone(),
        }),
        "notification_cleared" => Some(NotificationChange::Cleared {
            notif_id: event.get("notif_id")?.as_str()?.to_string(),
        }),
        _ => None,
    }
}

/// A per-agent pending-notification projection. Membership is authoritative from the agent's connect
/// snapshot (a list of file-stem ids); richness (full event fields) comes from live `notification`
/// events observed over the tap. An id present in the snapshot but never seen live is represented by
/// a minimal stub so the tree's `pending` is always a list of notification-shaped objects, each with
/// an id.
#[derive(Debug, Default, Clone)]
pub(crate) struct PendingNotifications {
    known: HashMap<String, Value>,
    order: Vec<String>,
}

const STUB_NOTIFICATION_ID: i64 = 0;

impl PendingNotifications {
    /// Reconcile membership to exactly `ids` (the snapshot's authoritative pending set), preserving
    /// known full events and stubbing ids not yet observed live. Returns whether the rendered list
    /// changed, so the caller emits a delta only on a real change.
    pub fn seed(&mut self, ids: &[String]) -> bool {
        let before = self.render();
        self.order = ids.to_vec();
        self.known.retain(|id, _| ids.contains(id));
        for id in ids {
            self.known.entry(id.clone()).or_insert_with(|| stub_notification(id));
        }
        self.render() != before
    }

    /// Apply a live add/clear. Returns whether the rendered list changed.
    pub fn apply(&mut self, change: NotificationChange) -> bool {
        let before = self.render();
        match change {
            NotificationChange::Added { notif_id, event } => {
                if !self.order.contains(&notif_id) {
                    self.order.push(notif_id.clone());
                }
                self.known.insert(notif_id, event);
            }
            NotificationChange::Cleared { notif_id } => {
                self.order.retain(|id| id != &notif_id);
                self.known.remove(&notif_id);
            }
        }
        self.render() != before
    }

    pub fn render(&self) -> Vec<Value> {
        self.order.iter().filter_map(|id| self.known.get(id).cloned()).collect()
    }
}

fn stub_notification(notif_id: &str) -> Value {
    serde_json::json!({
        "id": STUB_NOTIFICATION_ID,
        "type": "notification",
        "notif_id": notif_id,
        "source": "",
        "summary": "",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Loads the committed tap-read fixture. Returns None (test no-ops) in a standalone vestad checkout
    /// without the sibling `agent/` tree, mirroring `sync_fixture_file`'s skip-when-absent rule.
    fn union_fixture() -> Option<Value> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../agent/tests/fixtures/event-union.json");
        let raw = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&raw).ok()
    }

    #[test]
    fn every_union_event_yields_meta_with_the_right_id_sign() {
        let Some(fixture) = union_fixture() else { return };
        let events = fixture["events"].as_array().expect("events array");
        assert_eq!(events.len(), 4, "the fixture covers the tap-read subset");
        for event in events {
            let id = event.get("id").and_then(Value::as_i64).expect("every event carries an id");
            let kind = event.get("type").and_then(Value::as_str).expect("every event carries a type");
            let live = kind == "status" || kind == "model_access" || kind == "notification_cleared";
            if live {
                assert!(id < 0, "live-only {kind} uses a negative id");
            } else {
                assert!(id > 0, "persisted {kind} uses a positive rowid");
            }
        }
    }

    #[test]
    fn classifies_notification_variants_from_the_seam() {
        let Some(fixture) = union_fixture() else { return };
        let events = fixture["events"].as_array().expect("events array");
        let added = events.iter().filter_map(notification_change).filter(|c| matches!(c, NotificationChange::Added { .. })).count();
        let cleared = events.iter().filter_map(notification_change).filter(|c| matches!(c, NotificationChange::Cleared { .. })).count();
        assert_eq!(added, 1, "one notification variant in the union");
        assert_eq!(cleared, 1, "one notification_cleared variant in the union");
    }

    #[test]
    fn snapshot_activity_state_is_readable() {
        let Some(fixture) = union_fixture() else { return };
        assert_eq!(activity_state(&fixture["snapshot"]).as_deref(), Some("idle"));
    }

    #[test]
    fn seed_stubs_unknown_ids_and_keeps_known_events() {
        let mut pending = PendingNotifications::default();
        assert!(pending.seed(&["a".into(), "b".into()]));
        let rendered = pending.render();
        assert_eq!(rendered.len(), 2);
        assert_eq!(rendered[0]["notif_id"], serde_json::json!("a"));
        // A live event enriches an already-pending id in place, keeping membership.
        let changed = pending.apply(NotificationChange::Added {
            notif_id: "a".into(),
            event: serde_json::json!({"id": 7, "type": "notification", "notif_id": "a", "source": "sms", "summary": "hi"}),
        });
        assert!(changed);
        assert_eq!(pending.render()[0]["source"], serde_json::json!("sms"));
    }

    #[test]
    fn reseed_drops_ids_cleared_while_disconnected_and_a_clear_removes_membership() {
        let mut pending = PendingNotifications::default();
        pending.seed(&["a".into(), "b".into()]);
        // On tap reconnect the fresh snapshot no longer lists "b": it is dropped.
        assert!(pending.seed(&["a".into()]));
        assert_eq!(pending.render().len(), 1);
        // An explicit clear of "a" empties the branch.
        assert!(pending.apply(NotificationChange::Cleared { notif_id: "a".into() }));
        assert!(pending.render().is_empty());
        // A no-op reseed to the same set reports no change.
        assert!(!pending.seed(&[]));
    }
}
