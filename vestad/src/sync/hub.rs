use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde_json::Value;
use tokio::sync::{broadcast, watch};

use super::events::{NotificationChange, PendingNotifications};

/// Per-agent live-edge buffer. A watcher that falls this far behind is dropped with a `resync`
/// delta (today's `EventBus` eviction contract, scoped to one subscription instead of the socket).
const AGENT_BROADCAST_CAPACITY: usize = 256;

/// Buffer for the always-on alert fan-out. Alerts are ephemeral toasts; a session that falls this
/// far behind simply drops the intervening ones (no resync), which is acceptable by design.
const ALERT_BROADCAST_CAPACITY: usize = 256;

/// One live-edge message for an agent's watchers. `Resync` tells a watcher its live edge had a gap
/// (a tap reconnect); a lagging receiver is turned into the same resync by the handler.
#[derive(Clone, Debug)]
pub(crate) enum LiveMessage {
    Event(Arc<Value>),
    Resync,
}

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

struct AgentChannel {
    events: broadcast::Sender<LiveMessage>,
    pending: PendingNotifications,
}

impl AgentChannel {
    fn new() -> Self {
        let (events, _rx) = broadcast::channel(AGENT_BROADCAST_CAPACITY);
        Self { events, pending: PendingNotifications::default() }
    }
}

/// The aggregator's shared fan-out state. The tap (in `agent_status.rs`) publishes live events and
/// seeds notifications here; `/sync` connections subscribe for the live edge and read the
/// notifications projection. One instance lives on `AppState`.
pub(crate) struct SyncHub {
    agents: Mutex<HashMap<String, AgentChannel>>,
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

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, AgentChannel>> {
        self.agents.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Subscribe to an agent's live edge, creating the channel if the agent has not materialized yet
    /// (watch-before-create: the receiver simply waits until the tap publishes).
    pub fn subscribe_events(&self, agent: &str) -> broadcast::Receiver<LiveMessage> {
        self.lock().entry(agent.to_string()).or_insert_with(AgentChannel::new).events.subscribe()
    }

    /// Publish a live event to an agent's watchers. Backlog (the connect snapshot) is never
    /// published; only the live edge is. A send with no receivers is a no-op.
    pub fn publish_event(&self, agent: &str, event: Arc<Value>) {
        let mut agents = self.lock();
        let channel = agents.entry(agent.to_string()).or_insert_with(AgentChannel::new);
        let _ = channel.events.send(LiveMessage::Event(event));
    }

    /// Tell an agent's watchers their live edge had a gap; each re-watches and refetches the tail by
    /// id. Used on tap reconnect.
    pub fn publish_resync(&self, agent: &str) {
        if let Some(channel) = self.lock().get(agent) {
            let _ = channel.events.send(LiveMessage::Resync);
        }
    }

    /// Reconcile an agent's pending notifications to the snapshot's authoritative id set; wakes
    /// `/sync` loops only on a real change.
    pub fn seed_notifications(&self, agent: &str, ids: &[String]) {
        let changed = self.lock().entry(agent.to_string()).or_insert_with(AgentChannel::new).pending.seed(ids);
        if changed {
            self.bump_notifications();
        }
    }

    pub fn apply_notification(&self, agent: &str, change: NotificationChange) {
        let changed = self.lock().entry(agent.to_string()).or_insert_with(AgentChannel::new).pending.apply(change);
        if changed {
            self.bump_notifications();
        }
    }

    /// Drop all fan-out state for an agent that left the alive set. Watchers' receivers close; the
    /// `/sync` handler emits `agent_removed` from the roster diff.
    pub fn forget_agent(&self, agent: &str) {
        if self.lock().remove(agent).is_some() {
            self.bump_notifications();
        }
    }

    /// The current pending list for every agent: the connect snapshot's notification branches and
    /// the notifications diff loop both read this.
    pub fn pending_all(&self) -> HashMap<String, Vec<Value>> {
        self.lock().iter().map(|(name, c)| (name.clone(), c.pending.render())).collect()
    }

    pub fn subscribe_notifications(&self) -> watch::Receiver<u64> {
        self.notifications_rx.clone()
    }

    /// Subscribe to the always-on alert edge shared by every `/sync` session. Independent of watches:
    /// a session forwards every alert regardless of which agents it is watching.
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
    async fn watch_before_create_then_publish_delivers() {
        let hub = SyncHub::new();
        // Subscribe before the agent's tap ever created the channel.
        let mut rx = hub.subscribe_events("late");
        hub.publish_event("late", Arc::new(serde_json::json!({"id": 1, "type": "chat", "text": "hi"})));
        match rx.recv().await.expect("event") {
            LiveMessage::Event(event) => assert_eq!(event["text"], serde_json::json!("hi")),
            LiveMessage::Resync => panic!("expected an event, got resync"),
        }
    }

    #[tokio::test]
    async fn a_lagging_watcher_reads_lagged() {
        let hub = SyncHub::new();
        let mut rx = hub.subscribe_events("chatty");
        // Overflow the per-agent buffer without receiving; the next recv reports the drop, which the
        // handler turns into a resync.
        for i in 0..(AGENT_BROADCAST_CAPACITY as i64 + 1) {
            hub.publish_event("chatty", Arc::new(serde_json::json!({"id": i, "type": "chat", "text": ""})));
        }
        assert!(matches!(rx.recv().await, Err(broadcast::error::RecvError::Lagged(_))));
    }

    #[tokio::test]
    async fn an_alert_fans_out_to_every_session_regardless_of_watches() {
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
