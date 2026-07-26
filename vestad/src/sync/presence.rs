use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tokio::sync::watch;
use tokio::time::Instant;

use super::protocol::ClientContext;

/// The user must have been away this long before a return-to-focus re-notifies the active agent, so
/// glances and alt-tabs never spam it.
pub(crate) const PRESENCE_NOTIFY_DEBOUNCE: Duration = Duration::from_secs(600);

pub(crate) type ConnId = u64;

/// An aggregate-presence edge worth acting on. `any_focused` fan-out rides the watch channel, so the
/// only returned event is the debounced return-to-focus that targets an agent notification.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum PresenceEvent {
    BecamePresent { agent: String },
}

struct PresenceState {
    contexts: HashMap<ConnId, ClientContext>,
    /// The last instant any client was focused; seeds the debounce gap on the next return-to-focus.
    last_present_at: Option<Instant>,
}

/// Per-connection client presence. The socket lifecycle owns an entry (connect/disconnect), so there
/// is no heartbeat or TTL: a dropped socket clears its presence. `any_focused` is fanned to every
/// `/sync` session through a watch channel.
pub(crate) struct Presence {
    state: Mutex<PresenceState>,
    next_id: AtomicU64,
    any_focused_tx: watch::Sender<bool>,
}

impl Presence {
    pub(crate) fn new() -> Self {
        let (any_focused_tx, _rx) = watch::channel(false);
        Self {
            state: Mutex::new(PresenceState { contexts: HashMap::new(), last_present_at: None }),
            next_id: AtomicU64::new(0),
            any_focused_tx,
        }
    }

    pub(crate) fn connect(&self) -> ConnId {
        self.next_id.fetch_add(1, Ordering::Relaxed)
    }

    pub(crate) fn record(&self, id: ConnId, ctx: ClientContext, now: Instant) -> Vec<PresenceEvent> {
        let mut state = self.state.lock().expect("presence mutex");
        let was_present = Self::compute_any_focused(&state.contexts);
        let active_agent = ctx.active_agent.clone();
        let focused = ctx.focused;
        state.contexts.insert(id, ctx);
        let is_present = Self::compute_any_focused(&state.contexts);
        self.finish(&mut state, was_present, is_present, focused, active_agent, now)
    }

    pub(crate) fn disconnect(&self, id: ConnId, now: Instant) {
        let mut state = self.state.lock().expect("presence mutex");
        let was_present = Self::compute_any_focused(&state.contexts);
        state.contexts.remove(&id);
        let is_present = Self::compute_any_focused(&state.contexts);
        let _ = self.finish(&mut state, was_present, is_present, false, None, now);
    }

    pub(crate) fn any_focused(&self) -> bool {
        *self.any_focused_tx.borrow()
    }

    pub(crate) fn subscribe_any_focused(&self) -> watch::Receiver<bool> {
        self.any_focused_tx.subscribe()
    }

    fn compute_any_focused(contexts: &HashMap<ConnId, ClientContext>) -> bool {
        contexts.values().any(|c| c.focused)
    }

    /// Reconcile a presence change: publish `any_focused` if it flipped, and emit a debounced
    /// `BecamePresent` when the aggregate rose to focused after a long-enough gap with an active agent.
    fn finish(
        &self,
        state: &mut PresenceState,
        was_present: bool,
        is_present: bool,
        focused: bool,
        active_agent: Option<String>,
        now: Instant,
    ) -> Vec<PresenceEvent> {
        let mut events = Vec::new();
        if is_present != was_present {
            let _ = self.any_focused_tx.send(is_present);
        }
        if !was_present && is_present && focused {
            let long_gap = state
                .last_present_at
                .is_none_or(|last| now.duration_since(last) >= PRESENCE_NOTIFY_DEBOUNCE);
            if long_gap {
                if let Some(agent) = active_agent {
                    events.push(PresenceEvent::BecamePresent { agent });
                }
            }
        }
        if is_present {
            state.last_present_at = Some(now);
        }
        events
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use tokio::time::Instant;

    fn ctx(focused: bool, agent: Option<&str>) -> ClientContext {
        ClientContext { focused, active_agent: agent.map(str::to_string) }
    }

    #[test]
    fn any_focused_reflects_connections() {
        let presence = Presence::new();
        let a = presence.connect();
        assert!(!presence.any_focused());
        presence.record(a, ctx(true, Some("scout")), Instant::now());
        assert!(presence.any_focused());
        presence.record(a, ctx(false, Some("scout")), Instant::now());
        assert!(!presence.any_focused());
    }

    #[test]
    fn disconnect_clears_focus() {
        let presence = Presence::new();
        let a = presence.connect();
        presence.record(a, ctx(true, None), Instant::now());
        assert!(presence.any_focused());
        presence.disconnect(a, Instant::now());
        assert!(!presence.any_focused());
    }

    #[test]
    fn became_present_fires_after_debounce_with_active_agent() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        // Cold start: first focus emits BecamePresent for the active agent.
        let events = presence.record(a, ctx(true, Some("scout")), t0);
        assert_eq!(events, vec![PresenceEvent::BecamePresent { agent: "scout".into() }]);
        // Blur, then refocus within the debounce window: no event.
        presence.record(a, ctx(false, Some("scout")), t0 + Duration::from_secs(60));
        let quick = presence.record(a, ctx(true, Some("scout")), t0 + Duration::from_secs(120));
        assert!(quick.is_empty());
        // Blur, then refocus after the debounce window: fires again.
        presence.record(a, ctx(false, Some("scout")), t0 + Duration::from_secs(180));
        let slow = presence.record(a, ctx(true, Some("scout")), t0 + PRESENCE_NOTIFY_DEBOUNCE + Duration::from_secs(200));
        assert_eq!(slow, vec![PresenceEvent::BecamePresent { agent: "scout".into() }]);
    }

    #[test]
    fn became_present_needs_an_active_agent() {
        let presence = Presence::new();
        let a = presence.connect();
        let events = presence.record(a, ctx(true, None), Instant::now());
        assert!(events.is_empty());
    }

    #[tokio::test]
    async fn subscribe_any_focused_sees_changes() {
        let presence = Presence::new();
        let mut rx = presence.subscribe_any_focused();
        assert!(!*rx.borrow_and_update());
        let a = presence.connect();
        presence.record(a, ctx(true, None), Instant::now());
        rx.changed().await.expect("focus change");
        assert!(*rx.borrow());
    }
}
