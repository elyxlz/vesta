use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tokio::sync::watch;
use tokio::time::Instant;

use super::protocol::ClientContext;
use crate::types::ClientKind;

/// The user must have been away this long before a return-to-focus notifies the agent fleet, so
/// glances and alt-tabs never spam it.
pub(crate) const PRESENCE_NOTIFY_DEBOUNCE: Duration = Duration::from_mins(10);

pub(crate) type ConnId = u64;

#[derive(Debug)]
struct PresenceState {
    contexts: HashMap<ConnId, ClientContext>,
    /// The last instant the user was online. A focused update refreshes it, and the final
    /// focused-to-unfocused edge records the departure time, so the debounce measures time away.
    last_online_at: Option<Instant>,
}

/// Per-connection client presence. The socket lifecycle owns an entry (connect/disconnect), so there
/// is no heartbeat or TTL: a dropped socket clears its presence. `any_focused` is fanned to every
/// `/sync` session through a watch channel.
#[derive(Debug)]
pub(crate) struct Presence {
    state: Mutex<PresenceState>,
    next_id: AtomicU64,
    any_focused_tx: watch::Sender<bool>,
}

impl Presence {
    pub(crate) fn new() -> Self {
        let (any_focused_tx, _rx) = watch::channel(false);
        Self {
            state: Mutex::new(PresenceState { contexts: HashMap::new(), last_online_at: None }),
            next_id: AtomicU64::new(0),
            any_focused_tx,
        }
    }

    pub(crate) fn connect(&self) -> ConnId {
        self.next_id.fetch_add(1, Ordering::Relaxed)
    }

    /// The client kind when this record is the debounced global return-to-focus. The
    /// `any_focused` fan-out rides the watch channel, so that edge is the only one a caller acts on.
    pub(crate) fn record(
        &self,
        id: ConnId,
        ctx: ClientContext,
        now: Instant,
    ) -> Option<ClientKind> {
        let mut state = self.state.lock().expect("presence mutex");
        let was_present = Self::compute_any_focused(&state.contexts);
        let resync = ctx.resync;
        let client = ctx.client;
        state.contexts.insert(id, ctx);
        let is_present = Self::compute_any_focused(&state.contexts);
        self.finish(&mut state, was_present, is_present, resync, client, now)
    }

    pub(crate) fn disconnect(&self, id: ConnId, now: Instant) {
        let mut state = self.state.lock().expect("presence mutex");
        let was_present = Self::compute_any_focused(&state.contexts);
        state.contexts.remove(&id);
        let is_present = Self::compute_any_focused(&state.contexts);
        self.finish(
            &mut state,
            was_present,
            is_present,
            false,
            ClientKind::Unknown,
            now,
        );
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

    /// Reconcile a presence change: publish `any_focused` if it flipped, and report a return to
    /// focus when the aggregate rose to focused after a long-enough gap.
    fn finish(
        &self,
        state: &mut PresenceState,
        was_present: bool,
        is_present: bool,
        resync: bool,
        client: ClientKind,
        now: Instant,
    ) -> Option<ClientKind> {
        if is_present != was_present {
            // send_replace updates the stored value even with no live receivers (a plain send would
            // fail and leave any_focused() reading a stale value); sessions still get the changed() wake.
            self.any_focused_tx.send_replace(is_present);
        }
        // A record that raises the aggregate to present can only be the just-recorded client turning
        // focused; disconnect never raises it, so a false->true edge always means "this client, focused".
        // A resync frame (reconnect replay of cached focus) is not a fresh return, so it never notifies.
        let became_present = (!was_present
            && is_present
            && !resync
            && state
                .last_online_at
                .is_none_or(|last| now.duration_since(last) >= PRESENCE_NOTIFY_DEBOUNCE))
        .then_some(client);
        if was_present || is_present {
            state.last_online_at = Some(now);
        }
        became_present
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use tokio::time::Instant;

    fn ctx(focused: bool) -> ClientContext {
        ClientContext { focused, client: ClientKind::Web, resync: false, ..Default::default() }
    }

    #[test]
    fn resync_context_does_not_emit_became_present() {
        let presence = Presence::new();
        let a = presence.connect();
        // A reconnect replay (resync) that re-establishes focus is not a fresh return: no notification,
        // but presence still becomes true so suppression works.
        let became_present = presence.record(
            a,
            ClientContext {
                focused: true,
                client: ClientKind::Desktop,
                resync: true,
                ..Default::default()
            },
            Instant::now(),
        );
        assert_eq!(became_present, None);
        assert!(presence.any_focused());
    }

    #[test]
    fn any_focused_reflects_connections() {
        let presence = Presence::new();
        let a = presence.connect();
        assert!(!presence.any_focused());
        presence.record(a, ctx(true), Instant::now());
        assert!(presence.any_focused());
        presence.record(a, ctx(false), Instant::now());
        assert!(!presence.any_focused());
    }

    #[test]
    fn disconnect_clears_focus() {
        let presence = Presence::new();
        let a = presence.connect();
        presence.record(a, ctx(true), Instant::now());
        assert!(presence.any_focused());
        presence.disconnect(a, Instant::now());
        assert!(!presence.any_focused());
    }

    #[test]
    fn became_present_fires_after_debounce() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        // Cold start: first genuine app focus is a return to focus.
        assert_eq!(presence.record(a, ctx(true), t0), Some(ClientKind::Web));
        // Blur, then refocus within the debounce window: nothing.
        presence.record(a, ctx(false), t0 + Duration::from_secs(60));
        assert_eq!(
            presence.record(a, ctx(true), t0 + Duration::from_secs(120)),
            None
        );
        // Blur, then refocus after the debounce window: fires again.
        presence.record(a, ctx(false), t0 + Duration::from_secs(180));
        assert_eq!(
            presence.record(
                a,
                ClientContext {
                    focused: true,
                    client: ClientKind::Mobile,
                    resync: false,
                    ..Default::default()
                },
                t0 + Duration::from_secs(180) + PRESENCE_NOTIFY_DEBOUNCE,
            ),
            Some(ClientKind::Mobile)
        );
    }

    #[test]
    fn debounce_measures_time_away_not_time_since_focusing() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, ctx(true), t0), Some(ClientKind::Web));
        // A client reports only on a change, so a long focused session sends nothing between these
        // two frames: the gap has to run from the blur, never from the focus that opened the session.
        presence.record(a, ctx(false), t0 + Duration::from_mins(30));
        assert_eq!(
            presence.record(a, ctx(true), t0 + Duration::from_mins(31)),
            None
        );
    }

    #[test]
    fn disconnect_while_focused_starts_the_gap() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, ctx(true), t0), Some(ClientKind::Web));
        // Closing the app is leaving, so the gap runs from the disconnect, not from the last frame.
        presence.disconnect(a, t0 + Duration::from_mins(30));
        let b = presence.connect();
        assert_eq!(
            presence.record(b, ctx(true), t0 + Duration::from_mins(31)),
            None
        );
    }

    #[tokio::test]
    async fn subscribe_any_focused_sees_changes() {
        let presence = Presence::new();
        let mut rx = presence.subscribe_any_focused();
        assert!(!*rx.borrow_and_update());
        let a = presence.connect();
        presence.record(a, ctx(true), Instant::now());
        rx.changed().await.expect("focus change");
        assert!(*rx.borrow());
    }
}
