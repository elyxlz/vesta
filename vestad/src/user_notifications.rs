//! The one owner of user-facing notifications. Every notification, whoever produced it, goes
//! through `UserNotifier::notify`: the `user_notification` delta always fans to every connected
//! `/sync` client, the entry lands in the durable log, and each kind additionally reaches
//! backgrounded mobile as an Expo push when its effective setting says so: the user's per-kind
//! override from the gateway settings, or the kind's default in `MOBILE_PUSH_ROUTES`. That table
//! is the whole difference between kinds.

use std::collections::HashMap;
use std::sync::Arc;

use crate::docker::AgentStatus;
use crate::mobile_app::MobileApp;
use crate::sync::{SyncHub, UserNotification};
use crate::user_notification_log::UserNotificationLog;

/// A new agent reply; agent-injectable.
pub const KIND_MESSAGE: &str = "message";
/// The agent's task activity: a task or reminder added, done, or due. Agent-injectable.
pub const KIND_TASK: &str = "task";
/// The gateway updated itself. Gateway-owned: the agent-injected endpoint refuses it, so nothing
/// but a real update can produce one.
pub const KIND_GATEWAY_UPDATED: &str = "gateway_updated";
/// A newer gateway release is available. Gateway-owned, minted once per discovered version.
pub const KIND_UPDATE_AVAILABLE: &str = "update_available";
/// The agent needs the user: a state only the user can fix (set up, sign in again), or a rate
/// limit only the user can wait out or reconfigure. Injected by the agent for what it observes
/// itself and minted by the gateway from status transitions.
pub const KIND_NEEDS_USER: &str = "needs_user";
/// An agent's stable status really changed (stopped, died, recovered). Gateway-owned, minted from
/// the observed status transition.
pub const KIND_AGENT_STATUS: &str = "agent_status";
/// A device never seen before connected to the gateway. Gateway-owned.
pub const KIND_DEVICE_CONNECTED: &str = "device_connected";

/// How each kind reaches backgrounded mobile: the device subscription that carries it, the event
/// type it renders as (`mobile_app::render_push`), and whether it pushes by default. The user
/// overrides the default per kind via the gateway settings (`Settings::push_notifications`); the
/// delta to connected clients always fans regardless. Each kind rides a subscription registered
/// devices already hold, so adding one changes no device registration.
const MOBILE_PUSH_ROUTES: &[(&str, &str, &str, bool)] = &[
    (KIND_MESSAGE, "chat", "chat", true),
    (KIND_TASK, "status", "task", false),
    (KIND_GATEWAY_UPDATED, "status", "gateway_updated", true),
    (KIND_UPDATE_AVAILABLE, "status", "update_available", false),
    (KIND_NEEDS_USER, "status", "needs_user", true),
    (KIND_AGENT_STATUS, "status", "agent_status", true),
    (KIND_DEVICE_CONNECTED, "status", "device_connected", true),
];

/// Every kind with its effective push setting under `overrides`: the settings wire shape, so
/// clients render one toggle per kind without knowing the defaults.
pub fn effective_push_kinds(overrides: &HashMap<String, bool>) -> Vec<(&'static str, bool)> {
    MOBILE_PUSH_ROUTES
        .iter()
        .map(|(kind, _, _, default_on)| {
            (*kind, overrides.get(*kind).copied().unwrap_or(*default_on))
        })
        .collect()
}

/// Whether `kind` names a known user-notification kind (the settings PUT validates against this).
pub fn known_push_kind(kind: &str) -> bool {
    MOBILE_PUSH_ROUTES.iter().any(|(routed, _, _, _)| *routed == kind)
}

/// The kinds an agent may inject (`POST /agents/{me}/user-notification`), a closed set:
/// `message` (a new agent reply), `needs_user` (the agent needs the user), and `task` (task and
/// reminder activity). An unknown kind is rejected so the surface cannot drift open, and that
/// includes the gateway-owned kinds: only the gateway's own observations publish those, so no
/// agent can forge one.
pub fn agent_injectable_kind(kind: &str) -> bool {
    matches!(kind, KIND_MESSAGE | KIND_NEEDS_USER | KIND_TASK)
}

/// The delivery targets of one notification, bundled once per producer call site (built by
/// `AppState::user_notifier`, which reads the live push overrides).
pub struct UserNotifier {
    pub(crate) sync_hub: Arc<SyncHub>,
    pub(crate) mobile_app: MobileApp,
    pub(crate) log: Arc<UserNotificationLog>,
    pub(crate) push_overrides: HashMap<String, bool>,
}

impl UserNotifier {
    /// Deliver one user-facing notification: append it to the durable log, fan the
    /// `user_notification` delta to every `/sync` client, plus the mobile push when the kind's
    /// effective setting (the user's override, or the route's default) says so. A blank title
    /// takes the default from `effective_title`.
    pub fn notify(&self, agent: &str, kind: &str, title: String, body: String) {
        let title = effective_title(agent, title);
        let identity = self.log.append(agent, kind, &title, &body);
        self.fan(identity, agent, kind, title, body);
    }

    /// `notify`, delivered at most once ever: skipped when the durable log already holds an
    /// entry with this kind and title, so neither a restart nor a repeated check can re-deliver
    /// it (the update announcement).
    pub fn notify_once(&self, agent: &str, kind: &str, title: String, body: String) {
        let title = effective_title(agent, title);
        if let Some(identity) = self.log.append_once(agent, kind, &title, &body) {
            self.fan(identity, agent, kind, title, body);
        }
    }

    fn fan(&self, (id, at): (u64, u64), agent: &str, kind: &str, title: String, body: String) {
        tracing::info!(%agent, %kind, %title, "user notification");
        // The append just moved the feed's newest stamp, which rides the gateway branch: wake
        // sessions so their next gateway diff carries it.
        self.sync_hub.bump_user_feed();
        if let Some((_, subscription, event_type, default_on)) =
            MOBILE_PUSH_ROUTES.iter().find(|(routed, _, _, _)| *routed == kind)
        {
            if self.push_overrides.get(kind).copied().unwrap_or(*default_on) {
                self.mobile_app.push_event(
                    agent,
                    subscription,
                    serde_json::json!({ "type": event_type, "title": title, "body": body }),
                );
            }
        }
        self.sync_hub.publish_user_notification(UserNotification { id, at, agent: agent.to_string(), kind: kind.to_string(), title, body });
    }

    /// A device id's first sighting ever. The copy lives here beside the other gateway-minted
    /// producers; the sync handler only relays the sighting and the device's descriptor.
    pub fn notify_device_connected(&self, descriptor: Option<String>) {
        let label = descriptor.unwrap_or_else(|| "unknown device".to_string());
        self.notify(
            "",
            KIND_DEVICE_CONNECTED,
            format!("new device connected: {label}"),
            String::new(),
        );
    }

    /// A rate-limit window newly binding an alive agent: only the user can wait it out or
    /// reconfigure the provider, so it notifies as `needs_user`. Minted here from the roster
    /// overlay's transition (`observe_rate_limits`), never injected by the agent, so a dropped
    /// request cannot lose it and a restarted agent cannot repeat it.
    pub fn notify_rate_limited(&self, agent: &str, window: &crate::docker::RateLimitedWindow) {
        self.notify(
            agent,
            KIND_NEEDS_USER,
            format!("{agent} is rate limited"),
            rate_limited_body(window, crate::time_utils::now_epoch_secs()),
        );
    }

    /// Route one observed stable-status transition into exactly one notification: a status only
    /// the user can fix notifies as `needs_user`, every other real change as `agent_status`.
    pub fn notify_status_transition(&self, agent: &str, status: AgentStatus) {
        let (kind, title, body) =
            if let Some((title, body)) = needs_user_notification(agent, status) {
                (KIND_NEEDS_USER, title, body)
            } else {
                let (title, body) = status_notification(agent, status);
                (KIND_AGENT_STATUS, title, body)
            };
        self.notify(agent, kind, title, body);
    }
}

/// The one line every surface renders, so no notification may go out without one: a blank
/// title becomes the agent's name, or "Vesta" for the gateway's own notifications (they name
/// no agent).
fn effective_title(agent: &str, title: String) -> String {
    if title.trim().is_empty() {
        if agent.is_empty() { "Vesta".to_string() } else { agent.to_string() }
    } else {
        title
    }
}

/// The window names the agent's structured classification can carry; anything else (or a bare 429
/// with no classification) takes the generic line. Duplicated from the agent's own wording on
/// purpose: the two sides of this seam share no library.
fn rate_limited_body(window: &crate::docker::RateLimitedWindow, now_epoch_secs: u64) -> String {
    let name = match window.window.as_deref() {
        Some("five_hour") => "The 5-hour usage window is exhausted",
        Some("seven_day") => "The weekly usage window is exhausted",
        Some("seven_day_opus") => "The weekly Opus usage window is exhausted",
        Some("seven_day_sonnet") => "The weekly Sonnet usage window is exhausted",
        Some("overage") => "The extra usage budget is exhausted",
        _ => "The provider rejected new work",
    };
    let reset = window
        .resets_at
        .and_then(|resets_at| u64::try_from(resets_at).ok())
        .filter(|resets_at| *resets_at > now_epoch_secs)
        .map(|resets_at| {
            let remaining = resets_at - now_epoch_secs;
            let (hours, minutes) = (remaining / 3600, remaining % 3600 / 60);
            if hours > 0 {
                format!(", resets in {hours}h {minutes}m")
            } else {
                format!(", resets in {minutes}m")
            }
        })
        .unwrap_or_default();
    format!("{name}{reset}.")
}

/// The notification a status owes the user, if that status needs one at all.
fn needs_user_notification(agent: &str, status: AgentStatus) -> Option<(String, String)> {
    match status {
        AgentStatus::Unprovisioned => Some((
            format!("{agent} needs to be set up"),
            "Choose a provider and sign in.".to_string(),
        )),
        AgentStatus::NotAuthenticated => Some((
            format!("{agent} needs to sign in again"),
            "The provider sign-in was lost. Re-authenticate.".to_string(),
        )),
        _ => None,
    }
}

/// The status-news line for a stable status an agent just entered: the title is the whole
/// message and the body stays empty. The transient states never arrive here (the observation
/// map only advances on stable ones), so they take the generic line.
fn status_notification(agent: &str, status: AgentStatus) -> (String, String) {
    let title = match status {
        AgentStatus::Alive => "is back",
        AgentStatus::SettingUp => "is being set up",
        AgentStatus::Stopped => "stopped",
        AgentStatus::Dead => "hit a problem",
        AgentStatus::NotFound => "is unavailable",
        AgentStatus::Starting
        | AgentStatus::Restarting
        | AgentStatus::Rebuilding
        | AgentStatus::Unprovisioned
        | AgentStatus::NotAuthenticated => "changed status",
    };
    (format!("{agent} {title}"), String::new())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::device_registry::DeviceRegistry;
    use crate::mobile_app::MobileAppWorker;

    fn notifier(
        push_overrides: HashMap<String, bool>,
    ) -> (UserNotifier, Arc<SyncHub>, MobileAppWorker, tempfile::TempDir) {
        let directory = tempfile::tempdir().expect("tempdir");
        let (mobile_app, worker) = MobileApp::new(
            Arc::new(DeviceRegistry::load(directory.path())),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        let sync_hub = Arc::new(SyncHub::new());
        let log = Arc::new(UserNotificationLog::load(directory.path()));
        let delivery = UserNotifier { sync_hub: sync_hub.clone(), mobile_app, log, push_overrides };
        (delivery, sync_hub, worker, directory)
    }

    async fn drain_pushes(delivery: UserNotifier, mut worker: MobileAppWorker) -> Vec<(String, String)> {
        drop(delivery);
        let mut queued = Vec::new();
        while let Some(event) = worker.event_rx.recv().await {
            queued.push((
                event.event_type,
                event.event["type"].as_str().unwrap_or_default().to_string(),
            ));
        }
        queued
    }

    #[test]
    fn agent_injectable_kinds_are_a_closed_set() {
        assert!(agent_injectable_kind(KIND_MESSAGE));
        assert!(agent_injectable_kind(KIND_NEEDS_USER));
        assert!(agent_injectable_kind(KIND_TASK));
        for gateway_owned in [
            KIND_GATEWAY_UPDATED,
            KIND_UPDATE_AVAILABLE,
            KIND_AGENT_STATUS,
            KIND_DEVICE_CONNECTED,
        ] {
            assert!(
                !agent_injectable_kind(gateway_owned),
                "{gateway_owned} is gateway-owned; an agent cannot forge it"
            );
        }
        assert!(!agent_injectable_kind("rate_limited"));
        assert!(!agent_injectable_kind("chat"));
        assert!(!agent_injectable_kind("status"));
        assert!(!agent_injectable_kind(""));
    }

    #[tokio::test]
    async fn a_blank_title_defaults_to_the_agent_name_or_vesta_on_every_surface() {
        let (delivery, sync_hub, mut worker, _dir) = notifier(HashMap::new());
        let mut deltas = sync_hub.subscribe_user_notifications();

        delivery.notify("alex", KIND_MESSAGE, "  ".into(), "hi".into());
        delivery.notify("", KIND_GATEWAY_UPDATED, String::new(), "done".into());

        assert_eq!(deltas.try_recv().expect("agent delta").title, "alex");
        assert_eq!(deltas.try_recv().expect("gateway delta").title, "Vesta");
        drop(delivery);
        let event = worker.event_rx.recv().await.expect("queued push").event;
        assert_eq!(event["title"].as_str(), Some("alex"));
    }

    #[tokio::test]
    async fn every_notification_lands_in_the_durable_log() {
        let (delivery, _sync_hub, _worker, _dir) = notifier(HashMap::new());
        delivery.notify("alex", KIND_MESSAGE, "alex".into(), "hi".into());
        delivery.notify("", KIND_UPDATE_AVAILABLE, "gateway v0.3.0 available".into(), String::new());

        let logged = delivery.log.page(None, 10);
        assert_eq!(
            logged.iter().map(|entry| (entry.id, entry.kind.as_str())).collect::<Vec<_>>(),
            vec![(2, KIND_UPDATE_AVAILABLE), (1, KIND_MESSAGE)]
        );
    }

    #[tokio::test]
    async fn the_fanned_delta_carries_the_logged_entry_identity() {
        let (delivery, sync_hub, _worker, _dir) = notifier(HashMap::new());
        let mut deltas = sync_hub.subscribe_user_notifications();
        delivery.notify("alex", KIND_MESSAGE, "alex".into(), "hi".into());
        delivery.notify_once("", KIND_UPDATE_AVAILABLE, "gateway v0.3.0 available".into(), String::new());

        let logged = delivery.log.page(None, 10);
        let first = deltas.try_recv().expect("message delta");
        let second = deltas.try_recv().expect("update delta");
        assert_eq!((first.id, first.at), (logged[1].id, logged[1].at));
        assert_eq!((second.id, second.at), (logged[0].id, logged[0].at));
    }

    #[tokio::test]
    async fn notify_once_skips_a_kind_and_title_already_in_the_log() {
        let (delivery, sync_hub, _worker, _dir) = notifier(HashMap::new());
        let mut deltas = sync_hub.subscribe_user_notifications();

        let title = "gateway v0.3.0 available";
        delivery.notify_once("", KIND_UPDATE_AVAILABLE, title.into(), String::new());
        delivery.notify_once("", KIND_UPDATE_AVAILABLE, title.into(), String::new());
        delivery.notify_once("", KIND_UPDATE_AVAILABLE, "gateway v0.4.0 available".into(), String::new());

        assert_eq!(deltas.try_recv().expect("first delta").title, title);
        assert_eq!(deltas.try_recv().expect("new version delta").title, "gateway v0.4.0 available");
        assert!(deltas.try_recv().is_err(), "the repeated title fans no delta");
        assert_eq!(delivery.log.page(None, 10).len(), 2);
    }

    #[tokio::test]
    async fn a_push_override_flips_a_kind_on_or_off_without_touching_the_delta() {
        let overrides = HashMap::from([
            (KIND_MESSAGE.to_string(), false),
            (KIND_TASK.to_string(), true),
        ]);
        let (delivery, sync_hub, worker, _dir) = notifier(overrides);
        let mut deltas = sync_hub.subscribe_user_notifications();

        delivery.notify("alex", KIND_MESSAGE, "alex".into(), "hi".into());
        delivery.notify("alex", KIND_TASK, "task done: x".into(), "x".into());

        // Both deltas fan regardless; only the overridden-on kind pushes.
        assert_eq!(deltas.try_recv().expect("message delta").kind, KIND_MESSAGE);
        assert_eq!(deltas.try_recv().expect("task delta").kind, KIND_TASK);
        assert_eq!(
            drain_pushes(delivery, worker).await,
            vec![("status".to_string(), "task".to_string())]
        );
    }

    #[tokio::test]
    async fn every_kind_fans_the_delta_and_only_routed_kinds_push() {
        let (delivery, sync_hub, worker, _dir) = notifier(HashMap::new());
        let mut deltas = sync_hub.subscribe_user_notifications();

        delivery.notify("alex", KIND_MESSAGE, "alex".into(), "hi".into());
        delivery.notify("", KIND_GATEWAY_UPDATED, "Vesta".into(), "updated".into());
        delivery.notify("alex", KIND_NEEDS_USER, "alex needs to be set up".into(), "sign in".into());
        // A kind with no route fans the delta and never pushes.
        delivery.notify("alex", "toast_only", "alex".into(), "hello".into());

        let kinds: Vec<String> = (0..4).map(|_| deltas.try_recv().expect("delta").kind.clone()).collect();
        assert_eq!(kinds, vec![KIND_MESSAGE, KIND_GATEWAY_UPDATED, KIND_NEEDS_USER, "toast_only"]);
        assert_eq!(
            drain_pushes(delivery, worker).await,
            vec![
                ("chat".to_string(), "chat".to_string()),
                ("status".to_string(), "gateway_updated".to_string()),
                ("status".to_string(), "needs_user".to_string()),
            ]
        );
    }

    #[tokio::test]
    async fn a_binding_rate_limit_notifies_as_needs_user_with_the_window_and_reset() {
        let (delivery, sync_hub, worker, _dir) = notifier(HashMap::new());
        let mut deltas = sync_hub.subscribe_user_notifications();

        delivery.notify_rate_limited(
            "luna",
            &crate::docker::RateLimitedWindow {
                window: Some("seven_day".to_string()),
                resets_at: Some(i64::MAX),
            },
        );

        let delta = deltas.try_recv().expect("rate limit delta");
        assert_eq!(delta.kind, KIND_NEEDS_USER);
        assert_eq!(delta.title, "luna is rate limited");
        assert!(delta.body.starts_with("The weekly usage window is exhausted, resets in"));
        assert_eq!(
            drain_pushes(delivery, worker).await,
            vec![("status".to_string(), "needs_user".to_string())]
        );
    }

    #[test]
    fn rate_limited_body_names_the_window_and_omits_a_past_or_missing_reset() {
        let window = |name: Option<&str>, resets_at: Option<i64>| crate::docker::RateLimitedWindow {
            window: name.map(str::to_string),
            resets_at,
        };
        let now = 1_000_000;
        assert_eq!(
            rate_limited_body(&window(Some("five_hour"), Some(1_012_000)), now),
            "The 5-hour usage window is exhausted, resets in 3h 20m."
        );
        assert_eq!(
            rate_limited_body(&window(Some("seven_day"), None), now),
            "The weekly usage window is exhausted."
        );
        assert_eq!(
            rate_limited_body(&window(Some("overage"), Some(999_999)), now),
            "The extra usage budget is exhausted."
        );
        assert_eq!(rate_limited_body(&window(None, None), now), "The provider rejected new work.");
    }

    #[tokio::test]
    async fn a_transition_notifies_as_needs_user_or_agent_status_by_what_the_user_can_do() {
        let (delivery, sync_hub, worker, _dir) = notifier(HashMap::new());
        let mut deltas = sync_hub.subscribe_user_notifications();

        delivery.notify_status_transition("luna", AgentStatus::Unprovisioned);
        delivery.notify_status_transition("luna", AgentStatus::NotAuthenticated);
        delivery.notify_status_transition("luna", AgentStatus::Dead);
        delivery.notify_status_transition("luna", AgentStatus::Alive);

        let fanned: Vec<(String, String)> = (0..4)
            .map(|_| {
                let delta = deltas.try_recv().expect("delta");
                (delta.kind.clone(), delta.title.clone())
            })
            .collect();
        assert_eq!(
            fanned,
            vec![
                (KIND_NEEDS_USER.to_string(), "luna needs to be set up".to_string()),
                (KIND_NEEDS_USER.to_string(), "luna needs to sign in again".to_string()),
                (KIND_AGENT_STATUS.to_string(), "luna hit a problem".to_string()),
                (KIND_AGENT_STATUS.to_string(), "luna is back".to_string()),
            ]
        );
        assert_eq!(
            drain_pushes(delivery, worker).await,
            vec![
                ("status".to_string(), "needs_user".to_string()),
                ("status".to_string(), "needs_user".to_string()),
                ("status".to_string(), "agent_status".to_string()),
                ("status".to_string(), "agent_status".to_string()),
            ]
        );
    }
}
