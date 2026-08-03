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

/// After a return to focus is detected, wait this long before notifying the fleet: a return that
/// unfocuses inside the window was only a glance, so nothing is sent.
pub(crate) const PRESENCE_NOTIFY_DELAY: Duration = Duration::from_secs(5);

pub(crate) type ConnId = u64;

#[derive(Debug)]
struct PresenceState {
    contexts: HashMap<ConnId, ClientContext>,
    /// The last instant the user was online. A focused update refreshes it, and the final
    /// focused-to-unfocused edge records the departure time, so the debounce measures time away.
    /// Frozen while a return awaits confirmation: a glance that never survives the settle window
    /// must not consume the debounce.
    last_online_at: Option<Instant>,
    /// A debounced return has been detected and awaits its settle-window `confirm_return`.
    pending_return: bool,
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
            state: Mutex::new(PresenceState {
                contexts: HashMap::new(),
                last_online_at: None,
                pending_return: false,
            }),
            next_id: AtomicU64::new(0),
            any_focused_tx,
        }
    }

    pub(crate) fn connect(&self) -> ConnId {
        self.next_id.fetch_add(1, Ordering::Relaxed)
    }

    /// Whether this record is the debounced global return-to-focus, which the caller answers by
    /// scheduling a settle-window `confirm_return`. The `any_focused` fan-out rides the watch
    /// channel, so that edge is the only one a caller acts on.
    pub(crate) fn record(&self, id: ConnId, ctx: ClientContext, now: Instant) -> bool {
        let mut state = self.state.lock().expect("presence mutex");
        let was_present = Self::compute_any_focused(&state.contexts);
        let resync = ctx.resync;
        state.contexts.insert(id, ctx);
        let is_present = Self::compute_any_focused(&state.contexts);
        self.finish(&mut state, was_present, is_present, resync, now)
    }

    pub(crate) fn disconnect(&self, id: ConnId, now: Instant) {
        let mut state = self.state.lock().expect("presence mutex");
        let was_present = Self::compute_any_focused(&state.contexts);
        state.contexts.remove(&id);
        let is_present = Self::compute_any_focused(&state.contexts);
        self.finish(&mut state, was_present, is_present, false, now);
    }

    /// Consume a pending return once the settle window has elapsed: the kind of a still-focused
    /// client when the return is real, `None` when the user blurred inside the window. A glance
    /// leaves `last_online_at` at the pre-glance departure, so a later return still fires.
    pub(crate) fn confirm_return(&self, now: Instant) -> Option<ClientKind> {
        let mut state = self.state.lock().expect("presence mutex");
        if !state.pending_return {
            return None;
        }
        state.pending_return = false;
        let focused = state.contexts.values().find(|c| c.focused).map(|c| c.client);
        if focused.is_some() {
            state.last_online_at = Some(now);
        }
        focused
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

    /// Reconcile a presence change: publish `any_focused` if it flipped, and report whether a
    /// return to focus after a long-enough gap now awaits its settle-window confirmation.
    fn finish(
        &self,
        state: &mut PresenceState,
        was_present: bool,
        is_present: bool,
        resync: bool,
        now: Instant,
    ) -> bool {
        if is_present != was_present {
            // send_replace updates the stored value even with no live receivers (a plain send would
            // fail and leave any_focused() reading a stale value); sessions still get the changed() wake.
            self.any_focused_tx.send_replace(is_present);
        }
        // A resync frame (reconnect replay of cached focus) is not a fresh return, so it never
        // notifies, and a rise while a confirmation is already pending schedules nothing new.
        let starts_return = !was_present
            && is_present
            && !resync
            && !state.pending_return
            && state
                .last_online_at
                .is_none_or(|last| now.duration_since(last) >= PRESENCE_NOTIFY_DEBOUNCE);
        if starts_return {
            state.pending_return = true;
        }
        if !state.pending_return && (was_present || is_present) {
            state.last_online_at = Some(now);
        }
        starts_return
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
        let starts_return = presence.record(
            a,
            ClientContext {
                focused: true,
                client: ClientKind::Desktop,
                resync: true,
                ..Default::default()
            },
            Instant::now(),
        );
        assert!(!starts_return);
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
        assert!(presence.record(a, ctx(true), t0));
        assert_eq!(
            presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
        // Blur, then refocus within the debounce window: nothing.
        presence.record(a, ctx(false), t0 + Duration::from_secs(60));
        assert!(!presence.record(a, ctx(true), t0 + Duration::from_secs(120)));
        // Blur, then refocus after the debounce window: fires again, attributed at settle time.
        presence.record(a, ctx(false), t0 + Duration::from_secs(180));
        let return_at = t0 + Duration::from_secs(180) + PRESENCE_NOTIFY_DEBOUNCE;
        assert!(presence.record(
            a,
            ClientContext {
                focused: true,
                client: ClientKind::Mobile,
                resync: false,
                ..Default::default()
            },
            return_at,
        ));
        assert_eq!(
            presence.confirm_return(return_at + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Mobile)
        );
    }

    #[test]
    fn debounce_measures_time_away_not_time_since_focusing() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert!(presence.record(a, ctx(true), t0));
        assert_eq!(
            presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
        // A client reports only on a change, so a long focused session sends nothing between these
        // two frames: the gap has to run from the blur, never from the focus that opened the session.
        presence.record(a, ctx(false), t0 + Duration::from_mins(30));
        assert!(!presence.record(a, ctx(true), t0 + Duration::from_mins(31)));
    }

    #[test]
    fn disconnect_while_focused_starts_the_gap() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert!(presence.record(a, ctx(true), t0));
        assert_eq!(
            presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
        // Closing the app is leaving, so the gap runs from the disconnect, not from the last frame.
        presence.disconnect(a, t0 + Duration::from_mins(30));
        let b = presence.connect();
        assert!(!presence.record(b, ctx(true), t0 + Duration::from_mins(31)));
    }

    #[test]
    fn suppressed_glance_does_not_consume_the_return() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert!(presence.record(a, ctx(true), t0));
        // Blur inside the settle window: the return was only a glance, nothing is sent.
        presence.record(a, ctx(false), t0 + Duration::from_secs(2));
        assert_eq!(presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY), None);
        // The glance never counted as presence, so a return inside the debounce window
        // measured from the glance still notifies.
        assert!(presence.record(a, ctx(true), t0 + Duration::from_mins(8)));
        assert_eq!(
            presence.confirm_return(t0 + Duration::from_mins(8) + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
    }

    #[test]
    fn alt_tab_inside_settle_window_notifies_once() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert!(presence.record(a, ctx(true), t0));
        presence.record(a, ctx(false), t0 + Duration::from_secs(3));
        // A refocus while the settle task is armed schedules nothing new.
        assert!(!presence.record(a, ctx(true), t0 + Duration::from_secs(4)));
        assert_eq!(
            presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
        // The pending return is consumed, so a stray extra confirm sends nothing.
        assert_eq!(presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY), None);
    }

    #[test]
    fn confirm_attributes_the_client_focused_at_settle_time() {
        let presence = Presence::new();
        let mobile = presence.connect();
        let desktop = presence.connect();
        let t0 = Instant::now();
        let mobile_ctx = |focused| ClientContext {
            focused,
            client: ClientKind::Mobile,
            resync: false,
            ..Default::default()
        };
        assert!(presence.record(mobile, mobile_ctx(true), t0));
        presence.record(mobile, mobile_ctx(false), t0 + Duration::from_secs(2));
        presence.record(
            desktop,
            ClientContext {
                focused: true,
                client: ClientKind::Desktop,
                resync: false,
                ..Default::default()
            },
            t0 + Duration::from_secs(3),
        );
        assert_eq!(
            presence.confirm_return(t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Desktop)
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
