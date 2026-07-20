use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde_json::Value;
use tokio::sync::{broadcast, watch};

use super::events::{NotificationChange, PendingNotifications};

/// Buffer for the always-on alert fan-out. Alerts are ephemeral toasts; a session that falls this
/// far behind simply drops the intervening ones, which is acceptable by design.
const ALERT_BROADCAST_CAPACITY: usize = 256;

/// One user-facing alert fanned out to every `/sync` session: the source agent plus the notify
/// triple (`kind` in `message`/`rate_limited`, a title, and a body). Injected by the agent through
/// `POST /agents/{name}/notify`; the client routes the toast on `kind`.
#[derive(Clone, Debug)]
pub(crate) struct LiveAlert {
    pub agent: String,
    pub kind: String,
    pub title: String,
    pub body: String,
}

/// The aggregator's shared fan-out state. The tap (in `agent_status.rs`) seeds each agent's pending
/// notifications here; `/sync` connections read the notifications projection and subscribe to the
/// always-on alert edge. One instance lives on `AppState`.
pub(crate) struct SyncHub {
    agents: Mutex<HashMap<String, PendingNotifications>>,
    notifications_tx: watch::Sender<u64>,
    notifications_rx: watch::Receiver<u64>,
    alerts_tx: broadcast::Sender<Arc<LiveAlert>>,
}

impl Default for SyncHub {
    fn default() -> Self {
        Self::new()
    }
}

impl SyncHub {
    pub fn new() -> Self {
        let (notifications_tx, notifications_rx) = watch::channel(0);
        let (alerts_tx, _alerts_rx) = broadcast::channel(ALERT_BROADCAST_CAPACITY);
        Self { agents: Mutex::new(HashMap::new()), notifications_tx, notifications_rx, alerts_tx }
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

    /// Subscribe to the always-on alert edge shared by every `/sync` session. Every session forwards
    /// every alert to its client; the edge is not scoped to any agent.
    pub fn subscribe_alerts(&self) -> broadcast::Receiver<Arc<LiveAlert>> {
        self.alerts_tx.subscribe()
    }

    /// Fan a user-facing alert out to every `/sync` session. A send with no subscribers, or one
    /// dropped by a lagging receiver, is an accepted no-op: alerts are ephemeral.
    pub fn publish_alert(&self, agent: &str, kind: String, title: String, body: String) {
        let _ = self.alerts_tx.send(Arc::new(LiveAlert { agent: agent.to_string(), kind, title, body }));
    }

    fn bump_notifications(&self) {
        self.notifications_tx.send_modify(|v| *v = v.wrapping_add(1));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn an_alert_fans_out_to_every_session() {
        let hub = SyncHub::new();
        let mut first = hub.subscribe_alerts();
        let mut second = hub.subscribe_alerts();
        hub.publish_alert("scout", "message".into(), "scout".into(), "hi".into());
        for rx in [&mut first, &mut second] {
            let alert = rx.recv().await.expect("alert");
            assert_eq!(alert.agent, "scout");
            assert_eq!(alert.kind, "message");
            assert_eq!(alert.title, "scout");
            assert_eq!(alert.body, "hi");
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
