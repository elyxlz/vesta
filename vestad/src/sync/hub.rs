use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde_json::Value;
use tokio::sync::{broadcast, mpsc, watch};

use super::events::{NotificationChange, PendingNotifications};

/// Per-agent live-edge buffer. A watcher that falls this far behind is dropped with a `resync`
/// delta (today's `EventBus` eviction contract, scoped to one subscription instead of the socket).
const AGENT_BROADCAST_CAPACITY: usize = 256;

/// One live-edge message for an agent's watchers. `Resync` tells a watcher its live edge had a gap
/// (a tap reconnect); a lagging receiver is turned into the same resync by the handler.
#[derive(Clone, Debug)]
pub(crate) enum LiveMessage {
    Event(Arc<Value>),
    Resync,
}

struct AgentChannel {
    events: broadcast::Sender<LiveMessage>,
    writer: Option<mpsc::Sender<String>>,
    pending: PendingNotifications,
}

impl AgentChannel {
    fn new() -> Self {
        let (events, _rx) = broadcast::channel(AGENT_BROADCAST_CAPACITY);
        Self { events, writer: None, pending: PendingNotifications::default() }
    }
}

/// The aggregator's shared fan-out state. The tap (in `agent_status.rs`) publishes live events,
/// seeds notifications, and registers a write-half here; `/sync` connections subscribe for the live
/// edge and read the notifications projection. One instance lives on `AppState`.
pub(crate) struct SyncHub {
    agents: Mutex<HashMap<String, AgentChannel>>,
    notifications_tx: watch::Sender<u64>,
    notifications_rx: watch::Receiver<u64>,
}

/// Send-message relay failed because the agent's tap is down (restarting, evicted). Retryable: the
/// client keeps its composer state and retries; an ack means the agent's intake accepted it.
#[derive(Debug)]
pub(crate) struct TapUnavailable;

impl std::fmt::Display for TapUnavailable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("agent tap is unavailable; retry")
    }
}

impl std::error::Error for TapUnavailable {}

impl Default for SyncHub {
    fn default() -> Self {
        Self::new()
    }
}

impl SyncHub {
    pub fn new() -> Self {
        let (notifications_tx, notifications_rx) = watch::channel(0);
        Self { agents: Mutex::new(HashMap::new()), notifications_tx, notifications_rx }
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

    pub fn install_writer(&self, agent: &str, writer: mpsc::Sender<String>) {
        self.lock().entry(agent.to_string()).or_insert_with(AgentChannel::new).writer = Some(writer);
    }

    pub fn clear_writer(&self, agent: &str) {
        if let Some(channel) = self.lock().get_mut(agent) {
            channel.writer = None;
        }
    }

    /// Relay a send-message frame over the agent's tap write-half. Errors (retryable) when the tap is
    /// down or its relay queue is full.
    pub fn send_message(&self, agent: &str, frame: String) -> Result<(), TapUnavailable> {
        let agents = self.lock();
        let writer = agents.get(agent).and_then(|c| c.writer.as_ref()).ok_or(TapUnavailable)?;
        writer.try_send(frame).map_err(|_| TapUnavailable)
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

    fn bump_notifications(&self) {
        self.notifications_tx.send_modify(|v| *v = v.wrapping_add(1));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn send_message_without_a_writer_is_retryable() {
        let hub = SyncHub::new();
        let error = hub.send_message("ghost", "{}".into()).expect_err("no tap => retryable error");
        assert_eq!(error.to_string(), "agent tap is unavailable; retry");
    }

    #[tokio::test]
    async fn installed_writer_receives_the_relayed_frame() {
        let hub = SyncHub::new();
        let (tx, mut rx) = mpsc::channel::<String>(4);
        hub.install_writer("scout", tx);
        hub.send_message("scout", r#"{"type":"message","text":"hi"}"#.into()).expect("relay");
        assert_eq!(rx.recv().await.expect("frame"), r#"{"type":"message","text":"hi"}"#);
    }

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

    #[test]
    fn notifications_seed_and_apply_render_the_branch() {
        let hub = SyncHub::new();
        hub.seed_notifications("scout", &["a".into()]);
        assert_eq!(hub.pending_all()["scout"].len(), 1);
        hub.apply_notification("scout", NotificationChange::Cleared { notif_id: "a".into() });
        assert!(hub.pending_all()["scout"].is_empty());
    }
}
