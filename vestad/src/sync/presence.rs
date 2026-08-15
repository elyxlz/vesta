use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tokio::sync::watch;
use tokio::time::Instant;

use super::protocol::ClientContext;
use crate::types::ClientKind;

/// The user must have been away from an agent this long before opening its page notifies it, so
/// glances and quick re-opens never spam it.
pub(crate) const PRESENCE_NOTIFY_DEBOUNCE: Duration = Duration::from_mins(10);

/// After an agent's page is opened, wait this long before notifying it: a return that navigates
/// away inside the window was only a glance, so nothing is sent.
pub(crate) const PRESENCE_NOTIFY_DELAY: Duration = Duration::from_secs(45);

pub(crate) type ConnId = u64;

#[derive(Debug)]
struct PresenceState {
    contexts: HashMap<ConnId, ClientContext>,
    /// Per agent, the last instant it was viewed. A frame that views it refreshes it, and the edge
    /// where it leaves the viewed set records the departure time, so the debounce measures time
    /// away from that agent. Frozen for an agent while it awaits confirmation: a glance that never
    /// survives the settle window must not consume its debounce.
    last_viewed_at: HashMap<String, Instant>,
    /// Agents whose page-open has been detected and awaits its settle-window `confirm_return`.
    pending: HashSet<String>,
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
                last_viewed_at: HashMap::new(),
                pending: HashSet::new(),
            }),
            next_id: AtomicU64::new(0),
            any_focused_tx,
        }
    }

    pub(crate) fn connect(&self) -> ConnId {
        self.next_id.fetch_add(1, Ordering::Relaxed)
    }

    /// The agent whose page-open this frame just detected, if any: the caller answers it by
    /// scheduling a settle-window `confirm_return` for that agent. The `any_focused` fan-out rides
    /// the watch channel, so that edge is the only one a caller acts on.
    pub(crate) fn record(&self, id: ConnId, ctx: ClientContext, now: Instant) -> Option<String> {
        let mut state = self.state.lock().expect("presence mutex");
        let was_focused = Self::compute_any_focused(&state.contexts);
        let old_viewed = Self::viewed_agents(&state.contexts);
        let resync = ctx.resync;
        state.contexts.insert(id, ctx);
        self.finish(&mut state, was_focused, &old_viewed, resync, now)
    }

    pub(crate) fn disconnect(&self, id: ConnId, now: Instant) {
        let mut state = self.state.lock().expect("presence mutex");
        let was_focused = Self::compute_any_focused(&state.contexts);
        let old_viewed = Self::viewed_agents(&state.contexts);
        state.contexts.remove(&id);
        // A disconnect only shrinks the viewed set, so it never starts a return; the result is dropped.
        self.finish(&mut state, was_focused, &old_viewed, false, now);
    }

    /// Consume `agent`'s pending page-open once the settle window has elapsed: the kind of a client
    /// still viewing it when the open is real, `None` when the user navigated away inside the
    /// window. A glance leaves `last_viewed_at[agent]` at the pre-glance value, so a later open
    /// still fires.
    pub(crate) fn confirm_return(&self, agent: &str, now: Instant) -> Option<ClientKind> {
        let mut state = self.state.lock().expect("presence mutex");
        if !state.pending.remove(agent) {
            return None;
        }
        let client = Self::viewing_client(&state.contexts, agent)?;
        state.last_viewed_at.insert(agent.to_string(), now);
        Some(client)
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

    /// Every agent some connection currently reports viewing. The client reports `viewing` only
    /// while its window is focused, so this is the set of pages the user is looking at now.
    fn viewed_agents(contexts: &HashMap<ConnId, ClientContext>) -> HashSet<String> {
        contexts.values().filter_map(|c| c.viewing.clone()).collect()
    }

    /// The kind of some client currently viewing `agent`; which one is unspecified when several are.
    fn viewing_client(contexts: &HashMap<ConnId, ClientContext>, agent: &str) -> Option<ClientKind> {
        contexts
            .values()
            .find(|c| c.viewing.as_deref() == Some(agent))
            .map(|c| c.client)
    }

    /// Reconcile a presence change: publish `any_focused` if it flipped, refresh each viewed agent's
    /// timeline, and report the one agent (if any) whose page-open after a long-enough gap now awaits
    /// its settle-window confirmation. At most one agent enters the viewed set per frame (a single
    /// connection carries a single `viewing`), so a single return is exact.
    fn finish(
        &self,
        state: &mut PresenceState,
        was_focused: bool,
        old_viewed: &HashSet<String>,
        resync: bool,
        now: Instant,
    ) -> Option<String> {
        let is_focused = Self::compute_any_focused(&state.contexts);
        let new_viewed = Self::viewed_agents(&state.contexts);
        if is_focused != was_focused {
            // send_replace updates the stored value even with no live receivers (a plain send would
            // fail and leave any_focused() reading a stale value); sessions still get the changed() wake.
            self.any_focused_tx.send_replace(is_focused);
        }
        let mut started = None;
        for agent in new_viewed.difference(old_viewed) {
            // A resync frame (reconnect replay of cached context) is not a fresh open, so it never
            // notifies, and an open while a confirmation is already pending schedules nothing new.
            let fresh = state
                .last_viewed_at
                .get(agent)
                .is_none_or(|last| now.duration_since(*last) >= PRESENCE_NOTIFY_DEBOUNCE);
            if !resync && !state.pending.contains(agent) && fresh {
                state.pending.insert(agent.clone());
                started = Some(agent.clone());
            } else if !state.pending.contains(agent) {
                state.last_viewed_at.insert(agent.clone(), now);
            }
        }
        // Refresh agents still viewed and stamp the departure of those leaving, unless frozen while
        // pending. This is what makes the debounce measure time away from the agent.
        for agent in new_viewed.intersection(old_viewed).chain(old_viewed.difference(&new_viewed)) {
            if !state.pending.contains(agent) {
                state.last_viewed_at.insert(agent.clone(), now);
            }
        }
        started
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use tokio::time::Instant;

    /// A focused client viewing `agent`'s page.
    fn view(agent: &str, client: ClientKind) -> ClientContext {
        ClientContext {
            focused: true,
            client,
            resync: false,
            viewing: Some(agent.into()),
            ..Default::default()
        }
    }

    /// A focused client on no agent page (roster/home).
    fn roster(client: ClientKind) -> ClientContext {
        ClientContext { focused: true, client, ..Default::default() }
    }

    /// A blurred client: reports neither focus nor a viewed agent.
    fn blurred() -> ClientContext {
        ClientContext::default()
    }

    #[test]
    fn opening_an_agent_page_fires_after_settle() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        assert_eq!(
            presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
    }

    #[test]
    fn opening_one_agent_does_not_notify_another() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        // A different agent was never opened, so it has no pending return to confirm.
        assert_eq!(presence.confirm_return("apollo", t0 + PRESENCE_NOTIFY_DELAY), None);
    }

    #[test]
    fn switching_agents_notifies_the_newly_opened_one() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY);
        // Switching to apollo shortly after opens it fresh: apollo has its own timeline.
        let t1 = t0 + Duration::from_secs(60);
        assert_eq!(presence.record(a, view("apollo", ClientKind::Web), t1), Some("apollo".into()));
        // Switching back to scout inside its debounce window is silent.
        let t2 = t1 + Duration::from_secs(60);
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t2), None);
    }

    #[test]
    fn reopen_within_debounce_is_silent_then_fires_after_it() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY);
        // Leave the page, reopen within the debounce window: nothing.
        presence.record(a, roster(ClientKind::Web), t0 + Duration::from_secs(60));
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0 + Duration::from_secs(120)), None);
        // Leave, reopen after the debounce window: fires again, attributed at settle time.
        presence.record(a, roster(ClientKind::Web), t0 + Duration::from_secs(180));
        let reopen = t0 + Duration::from_secs(180) + PRESENCE_NOTIFY_DEBOUNCE;
        assert_eq!(presence.record(a, view("scout", ClientKind::Mobile), reopen), Some("scout".into()));
        assert_eq!(
            presence.confirm_return("scout", reopen + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Mobile)
        );
    }

    #[test]
    fn debounce_measures_time_away_not_time_since_opening() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY);
        // A long dwell on the page sends nothing between frames: the gap runs from leaving, never
        // from the open that started the session.
        presence.record(a, roster(ClientKind::Web), t0 + Duration::from_mins(30));
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0 + Duration::from_mins(31)), None);
    }

    #[test]
    fn disconnect_while_viewing_starts_the_gap() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY);
        // Closing the app is leaving, so the gap runs from the disconnect, not from the last frame.
        presence.disconnect(a, t0 + Duration::from_mins(30));
        let b = presence.connect();
        assert_eq!(presence.record(b, view("scout", ClientKind::Web), t0 + Duration::from_mins(31)), None);
    }

    #[test]
    fn glance_does_not_consume_the_debounce() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        // Navigate away inside the settle window: the open was only a glance, nothing is sent.
        presence.record(a, roster(ClientKind::Web), t0 + Duration::from_secs(2));
        assert_eq!(presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY), None);
        // The glance never stamped the timeline, so a reopen inside the window measured from it fires.
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0 + Duration::from_mins(8)), Some("scout".into()));
        assert_eq!(
            presence.confirm_return("scout", t0 + Duration::from_mins(8) + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
    }

    #[test]
    fn reopen_inside_settle_window_notifies_once() {
        let presence = Presence::new();
        let a = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0), Some("scout".into()));
        presence.record(a, roster(ClientKind::Web), t0 + Duration::from_secs(3));
        // A reopen while the settle task is armed schedules nothing new.
        assert_eq!(presence.record(a, view("scout", ClientKind::Web), t0 + Duration::from_secs(4)), None);
        assert_eq!(
            presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Web)
        );
        // The pending return is consumed, so a stray extra confirm sends nothing.
        assert_eq!(presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY), None);
    }

    #[test]
    fn resync_context_does_not_start_a_return() {
        let presence = Presence::new();
        let a = presence.connect();
        // A reconnect replay (resync) re-establishing a viewed page is not a fresh open.
        let started = presence.record(
            a,
            ClientContext {
                focused: true,
                client: ClientKind::Desktop,
                resync: true,
                viewing: Some("scout".into()),
                ..Default::default()
            },
            Instant::now(),
        );
        assert_eq!(started, None);
        assert!(presence.any_focused());
    }

    #[test]
    fn confirm_attributes_the_client_viewing_at_settle_time() {
        let presence = Presence::new();
        let mobile = presence.connect();
        let desktop = presence.connect();
        let t0 = Instant::now();
        assert_eq!(presence.record(mobile, view("scout", ClientKind::Mobile), t0), Some("scout".into()));
        presence.record(mobile, roster(ClientKind::Mobile), t0 + Duration::from_secs(2));
        presence.record(desktop, view("scout", ClientKind::Desktop), t0 + Duration::from_secs(3));
        assert_eq!(
            presence.confirm_return("scout", t0 + PRESENCE_NOTIFY_DELAY),
            Some(ClientKind::Desktop)
        );
    }

    #[test]
    fn any_focused_is_independent_of_viewing() {
        let presence = Presence::new();
        let a = presence.connect();
        assert!(!presence.any_focused());
        // Focused on the roster (no viewed agent) still counts as app focus.
        presence.record(a, roster(ClientKind::Web), Instant::now());
        assert!(presence.any_focused());
        presence.record(a, blurred(), Instant::now());
        assert!(!presence.any_focused());
    }

    #[test]
    fn disconnect_clears_focus() {
        let presence = Presence::new();
        let a = presence.connect();
        presence.record(a, view("scout", ClientKind::Web), Instant::now());
        assert!(presence.any_focused());
        presence.disconnect(a, Instant::now());
        assert!(!presence.any_focused());
    }

    #[tokio::test]
    async fn subscribe_any_focused_sees_changes() {
        let presence = Presence::new();
        let mut rx = presence.subscribe_any_focused();
        assert!(!*rx.borrow_and_update());
        let a = presence.connect();
        presence.record(a, roster(ClientKind::Web), Instant::now());
        rx.changed().await.expect("focus change");
        assert!(*rx.borrow());
    }
}
