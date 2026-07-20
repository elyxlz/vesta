use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde_json::Value;
use tokio::sync::{broadcast, watch};

use super::events::{NotificationChange, PendingNotifications};

/// Buffer for the always-on user-notification fan-out. User notifications are ephemeral toasts; a
/// session that falls this far behind simply drops the intervening ones, which is acceptable by design.
const USER_NOTIFICATION_BROADCAST_CAPACITY: usize = 256;

/// One user-facing notification fanned out to every `/sync` session: the source agent plus the
/// display triple (`kind` in `message`/`rate_limited`, a title, and a body). Injected by the agent
/// through `POST /agents/{name}/user-notification`; the client routes the toast on `kind`.
#[derive(Clone, Debug)]
pub(crate) struct UserNotification {
    pub agent: String,
    pub kind: String,
    pub title: String,
    pub body: String,
}

/// The aggregator's shared fan-out state. The tap (in `agent_status.rs`) seeds each agent's pending
/// notifications here; `/sync` connections read the notifications projection and subscribe to the
/// always-on user-notification edge. One instance lives on `AppState`.
pub(crate) struct SyncHub {
    agents: Mutex<HashMap<String, PendingNotifications>>,
    notifications_tx: watch::Sender<u64>,
    notifications_rx: watch::Receiver<u64>,
    user_notifications_tx: broadcast::Sender<Arc<UserNotification>>,
}

impl Default for SyncHub {
    fn default() -> Self {
        Self::new()
    }
}

impl SyncHub {
    pub fn new() -> Self {
        let (notifications_tx, notifications_rx) = watch::channel(0);
        let (user_notifications_tx, _user_notifications_rx) = broadcast::channel(USER_NOTIFICATION_BROADCAST_CAPACITY);
        Self { agents: Mutex::new(HashMap::new()), notifications_tx, notifications_rx, user_notifications_tx }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, PendingNotifications>> {
        self.agents.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Reconcile an agent's pending notifications to the snapshot's authoritative id set; wakes
    /// `/sync` loops only on a real change.
    pub fn seed_notifications(&self, agent: &str, ids: &[String]) {
        let changed = self.lock().entry(agent.to_string()).or_default().seed(ids);
        if changed {
            self.bump_notifications();
        }
    }

    pub fn apply_notification(&self, agent: &str, change: NotificationChange) {
        let changed = self.lock().entry(agent.to_string()).or_default().apply(change);
        if changed {
            self.bump_notifications();
        }
    }

    /// Drop all pending state for an agent that left the alive set. The `/sync` handler emits
    /// `agent_removed` from the roster diff.
    pub fn forget_agent(&self, agent: &str) {
        if self.lock().remove(agent).is_some() {
            self.bump_notifications();
        }
    }

    /// The current pending list for every agent: the connect snapshot's notification branches and
    /// the notifications diff loop both read this.
    pub fn pending_all(&self) -> HashMap<String, Vec<Value>> {
        self.lock().iter().map(|(name, pending)| (name.clone(), pending.render())).collect()
    }

    pub fn subscribe_notifications(&self) -> watch::Receiver<u64> {
        self.notifications_rx.clone()
    }

    /// Subscribe to the always-on user-notification edge shared by every `/sync` session. Every
    /// session forwards every user notification to its client; the edge is not scoped to any agent.
    pub fn subscribe_user_notifications(&self) -> broadcast::Receiver<Arc<UserNotification>> {
        self.user_notifications_tx.subscribe()
    }

    /// Fan a user-facing notification out to every `/sync` session. A send with no subscribers, or one
    /// dropped by a lagging receiver, is an accepted no-op: user notifications are ephemeral.
    pub fn publish_user_notification(&self, agent: &str, kind: String, title: String, body: String) {
        let _ = self.user_notifications_tx.send(Arc::new(UserNotification { agent: agent.to_string(), kind, title, body }));
    }

    fn bump_notifications(&self) {
        self.notifications_tx.send_modify(|v| *v = v.wrapping_add(1));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn a_user_notification_fans_out_to_every_session() {
        let hub = SyncHub::new();
        let mut first = hub.subscribe_user_notifications();
        let mut second = hub.subscribe_user_notifications();
        hub.publish_user_notification("scout", "message".into(), "scout".into(), "hi".into());
        for rx in [&mut first, &mut second] {
            let notification = rx.recv().await.expect("user notification");
            assert_eq!(notification.agent, "scout");
            assert_eq!(notification.kind, "message");
            assert_eq!(notification.title, "scout");
            assert_eq!(notification.body, "hi");
        }
    }

    #[test]
    fn notifications_seed_and_apply_render_the_branch() {
        let hub = SyncHub::new();
        hub.seed_notifications("scout", &["a".into()]);
        assert_eq!(hub.pending_all()["scout"].len(), 1);
        hub.apply_notification("scout", NotificationChange::Cleared { notif_id: "a".into() });
        assert!(hub.pending_all()["scout"].is_empty());
    }
}
