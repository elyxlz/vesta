//! Server-side business logic for the native mobile app.
//!
//! `vestad` observes every live agent event through its existing internal WebSocket,
//! then this module owns the complete remote-notification path: device registration,
//! subscription policy, persistence, payload rendering, queueing, and Expo delivery.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::{extract::State, http::StatusCode, Json};
use futures_util::{stream, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, Semaphore};

use crate::device_registry::{DeviceRegistry, PushSubscription};
use crate::docker::{AgentStatus, ListEntry};
use crate::state::{err_response, ok_json, SharedState};
use crate::time_utils::now_epoch_secs;
use crate::types::MobilePlatform;

const EXPO_PUSH_URL: &str = "https://exp.host/--/api/v2/push/send";
const MAX_INSTALLATION_ID_LENGTH: usize = 128;
const MAX_PUSH_TOKEN_LENGTH: usize = 512;
const MAX_EVENT_TYPES: usize = 32;
const MAX_PUSH_ATTEMPTS: usize = 3;
const MOBILE_EVENT_QUEUE_CAPACITY: usize = 256;
const MAX_CONCURRENT_EVENT_DELIVERIES: usize = 6;
const PUSHABLE_EVENT_TYPES: &[&str] = &["chat", "status"];
const MAX_CONCURRENT_PUSH_REQUESTS: usize = 6;

#[derive(Debug, Deserialize)]
pub(crate) struct RegisterMobileDevice {
    installation_id: String,
    token: String,
    platform: MobilePlatform,
    #[serde(default)]
    gateway: Option<String>,
    event_types: Vec<String>,
    #[serde(default)]
    previews: bool,
}

#[derive(Debug, Deserialize)]
pub(crate) struct DeleteMobileDevice {
    token: String,
}

#[derive(Debug)]
struct QueuedAgentEvent {
    agent: String,
    event_type: String,
    event: serde_json::Value,
}

#[derive(Clone, Debug)]
struct DeliveryContext {
    registry: Arc<DeviceRegistry>,
    http_client: reqwest::Client,
    push_slots: Arc<Semaphore>,
    presence: Arc<crate::sync::Presence>,
}

#[derive(Clone, Debug)]
pub(crate) struct MobileApp {
    registry: Arc<DeviceRegistry>,
    event_tx: mpsc::Sender<QueuedAgentEvent>,
    /// Each agent's last stable status: the one source of lifecycle pushes. It advances only
    /// when the agent is observed in a stable state with no planned operation covering it, so
    /// probe noise, boots, and vestad's own work can never masquerade as agent news, while a
    /// real change (died, stopped, signed out, recovered) pushes exactly once. An agent's
    /// first stable observation seeds silently, which is what keeps every boot quiet.
    stable_statuses: Arc<Mutex<HashMap<String, AgentStatus>>>,
    /// Whether lifecycle observation is live. It runs between the two ends of vestad's own agent
    /// work: the boot reconcile stops, starts, and restarts agents as planned work (new agent
    /// code, desired-run state) and the shutdown stops every one of them, and the map above lives
    /// only in memory, so observing across either would report vestad's own cycle ("is available",
    /// "needs you to sign in", "stopped") as agent news on every restart.
    observing: Arc<AtomicBool>,
}

#[derive(Debug)]
pub(crate) struct MobileAppWorker {
    context: DeliveryContext,
    event_rx: mpsc::Receiver<QueuedAgentEvent>,
}

#[derive(Clone, Debug, Serialize)]
struct ExpoPushMessage {
    to: String,
    title: String,
    body: String,
    sound: &'static str,
    priority: &'static str,
    #[serde(rename = "channelId")]
    channel_id: &'static str,
    data: serde_json::Value,
}

#[derive(Debug, Deserialize)]
struct ExpoPushResponse {
    #[serde(default)]
    data: Vec<ExpoPushTicket>,
}

#[derive(Debug, Deserialize)]
struct ExpoPushTicket {
    details: Option<ExpoPushErrorDetails>,
}

#[derive(Debug, Deserialize)]
struct ExpoPushErrorDetails {
    error: Option<String>,
}

fn valid_expo_token(token: &str) -> bool {
    token.len() <= MAX_PUSH_TOKEN_LENGTH
        && ((token.starts_with("ExponentPushToken[") && token.ends_with(']'))
            || (token.starts_with("ExpoPushToken[") && token.ends_with(']')))
}

fn valid_installation_id(installation_id: &str) -> bool {
    !installation_id.is_empty()
        && installation_id.len() <= MAX_INSTALLATION_ID_LENGTH
        && installation_id.bytes().all(|character| {
            character.is_ascii_alphanumeric() || character == b'-' || character == b'_'
        })
}

fn valid_event_type(event_type: &str) -> bool {
    !event_type.is_empty()
        && event_type.len() <= 64
        && event_type.bytes().all(|character| {
            character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || character == b'_'
                || character == b'-'
        })
}

fn normalize_gateway_identity(value: Option<String>) -> Result<Option<String>, ()> {
    let Some(value) = value else {
        return Ok(None);
    };
    let gateway = value.trim().trim_end_matches('/').to_string();
    if gateway.is_empty() {
        return Ok(None);
    }
    let url = reqwest::Url::parse(&gateway).map_err(|_| ())?;
    if gateway.len() > 2048
        || url.scheme() != "https"
        || url.origin().ascii_serialization() != gateway
    {
        return Err(());
    }
    Ok(Some(gateway))
}

fn pushable_event_type(event_type: &str) -> bool {
    PUSHABLE_EVENT_TYPES.contains(&event_type)
}

impl MobileApp {
    pub(crate) fn new(
        registry: Arc<DeviceRegistry>,
        http_client: reqwest::Client,
        presence: Arc<crate::sync::Presence>,
    ) -> (Self, MobileAppWorker) {
        let push_slots = Arc::new(Semaphore::new(MAX_CONCURRENT_PUSH_REQUESTS));
        let (event_tx, event_rx) = mpsc::channel(MOBILE_EVENT_QUEUE_CAPACITY);
        let delivery_context = DeliveryContext {
            registry: registry.clone(),
            http_client,
            push_slots,
            presence,
        };
        (
            Self {
                registry,
                event_tx,
                stable_statuses: Arc::new(Mutex::new(HashMap::new())),
                observing: Arc::new(AtomicBool::new(false)),
            },
            MobileAppWorker {
                context: delivery_context,
                event_rx,
            },
        )
    }

    /// Enqueue a mobile push for a user notification. Each pushable kind rides the device
    /// subscription that already covers it, so registered devices need no change: a new agent reply
    /// is `chat`, and the gateway announcing its own update is a `status` change. A `rate_limited`
    /// user notification toasts on connected clients and never pushes.
    pub(crate) fn push_user_notification(&self, agent: &str, kind: &str, title: &str, body: &str) {
        let (subscription, event_type) = match kind {
            "message" => ("chat", "chat"),
            crate::update::UPDATED_NOTIFICATION_KIND => ("status", "gateway_updated"),
            _ => return,
        };
        self.queue_event(
            agent,
            subscription,
            serde_json::json!({"type": event_type, "title": title, "body": body}),
        );
    }

    /// Advance each agent's last stable status from a fresh poll and enqueue a push per real
    /// change. An agent in a transient state, covered by a planned operation, or momentarily
    /// off the list does not move; an agent observed for the first time seeds silently.
    pub(crate) fn observe_agent_statuses(
        &self,
        agents: &[ListEntry],
        operated: &HashSet<String>,
        gateway_operation_running: bool,
    ) {
        if !self.observing.load(Ordering::Relaxed) {
            return;
        }
        let transitions: Vec<(String, AgentStatus, AgentStatus)> = {
            let mut stable = self
                .stable_statuses
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let mut transitions = Vec::new();
            for agent in agents {
                // Operations are keyed by normalized name, exactly as the roster joins them.
                if gateway_operation_running
                    || operated.contains(&crate::docker::normalize_name(&agent.name))
                {
                    continue;
                }
                if !agent.status.is_stable() {
                    continue;
                }
                match stable.insert(agent.name.clone(), agent.status) {
                    Some(before) if before != agent.status => {
                        transitions.push((agent.name.clone(), before, agent.status));
                    }
                    _ => {}
                }
            }
            transitions
        };
        for (agent, previous_status, status) in transitions {
            self.queue_event(
                &agent,
                "status",
                serde_json::json!({
                    "type": "status",
                    "previousState": previous_status,
                    "state": status,
                }),
            );
        }
    }

    pub(crate) fn begin_observing(&self) {
        self.observing.store(true, Ordering::Relaxed);
    }

    pub(crate) fn stop_observing(&self) {
        self.observing.store(false, Ordering::Relaxed);
    }

    /// Drop a destroyed agent's last stable status, so a later agent created under the same
    /// name seeds silently instead of diffing against its predecessor.
    pub(crate) fn forget_agent(&self, agent: &str) {
        self.stable_statuses
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(agent);
    }

    fn queue_event(&self, agent: &str, event_type: &str, event: serde_json::Value) {
        let queued = QueuedAgentEvent {
            agent: agent.to_string(),
            event_type: event_type.to_string(),
            event,
        };
        if let Err(error) = self.event_tx.try_send(queued) {
            tracing::warn!(%error, %agent, "mobile app event queue unavailable; dropping push");
        }
    }

    async fn register_device(
        &self,
        input: RegisterMobileDevice,
    ) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
        let installation_id = input.installation_id.trim().to_string();
        if !valid_installation_id(&installation_id) {
            return Err(err_response(
                StatusCode::BAD_REQUEST,
                "invalid mobile installation ID",
            ));
        }
        let token = input.token.trim().to_string();
        if !valid_expo_token(&token) {
            return Err(err_response(
                StatusCode::BAD_REQUEST,
                "invalid Expo push token",
            ));
        }
        let gateway = normalize_gateway_identity(input.gateway).map_err(|()| {
            err_response(StatusCode::BAD_REQUEST, "invalid mobile gateway identity")
        })?;
        if input.event_types.len() > MAX_EVENT_TYPES
            || input
                .event_types
                .iter()
                .any(|event_type| !valid_event_type(event_type) || !pushable_event_type(event_type))
        {
            return Err(err_response(
                StatusCode::BAD_REQUEST,
                "invalid mobile event subscriptions",
            ));
        }
        let mut event_types = input.event_types;
        event_types.sort();
        event_types.dedup();
        let push = PushSubscription {
            token: token.clone(),
            platform: input.platform,
            gateway,
            event_types,
            previews: input.previews,
            registered_at: now_epoch_secs(),
        };
        // Register in memory, then flush so the 200 means durable. On a flush failure roll the
        // registration back out of memory, keeping the old "failure registers nothing" contract.
        self.registry.upsert_push(&installation_id, push);
        if let Err(error) = self.registry.flush_now().await {
            self.registry.clear_push_by_token(&token);
            tracing::error!(%error, "could not persist mobile device registration");
            return Err(err_response(
                StatusCode::INTERNAL_SERVER_ERROR,
                "could not persist mobile device registration",
            ));
        }
        Ok(())
    }

    async fn delete_device(
        &self,
        token: &str,
    ) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
        self.registry.clear_push_by_token(token);
        self.registry.flush_now().await.map_err(|error| {
            tracing::error!(%error, "could not persist mobile device removal");
            err_response(
                StatusCode::INTERNAL_SERVER_ERROR,
                "could not persist mobile device removal",
            )
        })
    }
}

impl MobileAppWorker {
    pub(crate) async fn run(self) {
        run_delivery_queue(self.context, self.event_rx).await;
    }
}

async fn run_delivery_queue(
    context: DeliveryContext,
    mut receiver: mpsc::Receiver<QueuedAgentEvent>,
) {
    let mut in_flight = futures_util::stream::FuturesUnordered::new();
    loop {
        tokio::select! {
            event = receiver.recv(), if in_flight.len() < MAX_CONCURRENT_EVENT_DELIVERIES => {
                let Some(event) = event else {
                    break;
                };
                in_flight.push(deliver_agent_event(context.clone(), event));
            }
            _ = in_flight.next(), if !in_flight.is_empty() => {}
        }
    }
    while in_flight.next().await.is_some() {}
}

pub(crate) async fn register_device_handler(
    State(state): State<SharedState>,
    Json(input): Json<RegisterMobileDevice>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    state.mobile_app.register_device(input).await?;
    Ok(ok_json())
}

pub(crate) async fn delete_device_handler(
    State(state): State<SharedState>,
    Json(input): Json<DeleteMobileDevice>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    state.mobile_app.delete_device(&input.token).await?;
    Ok(ok_json())
}

fn text_field<'a>(event: &'a serde_json::Value, key: &str) -> Option<&'a str> {
    event.get(key).and_then(serde_json::Value::as_str)
}

/// Render one queued event as its push. The event's own `type` says what happened and decides the
/// text; `event_type` is the subscription that carried it, which only decided who receives it.
fn message_for(
    device: &PushSubscription,
    agent: &str,
    event_type: &str,
    event: &serde_json::Value,
) -> ExpoPushMessage {
    let (title, body, route) = match text_field(event, "type") {
        Some("gateway_updated") => (
            // The gateway decides its own text: there is no agent to name and nowhere to navigate.
            text_field(event, "title").unwrap_or("Vesta").to_string(),
            text_field(event, "body").unwrap_or("Your gateway updated.").to_string(),
            "/".to_string(),
        ),
        Some("chat") => {
            let title = text_field(event, "title").unwrap_or(agent).to_string();
            let body = match text_field(event, "body") {
                Some(text) if device.previews && !text.is_empty() => text.to_string(),
                _ => format!("{agent} sent a new message."),
            };
            (title, body, format!("/agent/{agent}/chat"))
        }
        Some("status") => {
            let state = text_field(event, "state").unwrap_or("updated");
            let body = match state {
                "alive" => format!("{agent} is available."),
                "setting_up" => format!("{agent} is being set up."),
                "starting" => format!("{agent} is starting."),
                "not_authenticated" => format!("{agent} needs you to sign in."),
                "unprovisioned" => format!("{agent} needs to be set up."),
                "rebuilding" => format!("{agent} is rebuilding."),
                "stopped" => format!("{agent} stopped."),
                "dead" => format!("{agent} encountered a problem."),
                "not_found" => format!("{agent} is unavailable."),
                _ => format!("{agent}'s status changed."),
            };
            ("Vesta".to_string(), body, format!("/agent/{agent}"))
        }
        _ => (
            "Vesta".to_string(),
            format!("{agent} has an update."),
            format!("/agent/{agent}"),
        ),
    };
    ExpoPushMessage {
        to: device.token.clone(),
        title,
        body,
        sound: "default",
        priority: "high",
        channel_id: "vesta",
        data: serde_json::json!({
            "agent": agent,
            "eventType": event_type,
            "gateway": device.gateway,
            "route": route,
        }),
    }
}

fn retryable_status(status: reqwest::StatusCode) -> bool {
    status == reqwest::StatusCode::TOO_MANY_REQUESTS || status.is_server_error()
}

fn unregistered_tokens(chunk: &[ExpoPushMessage], response: &ExpoPushResponse) -> Vec<String> {
    chunk
        .iter()
        .zip(&response.data)
        .filter(|(_, ticket)| {
            ticket
                .details
                .as_ref()
                .and_then(|details| details.error.as_deref())
                == Some("DeviceNotRegistered")
        })
        .map(|(message, _)| message.to.clone())
        .collect()
}

async fn send_push_chunk(
    client: &reqwest::Client,
    slots: std::sync::Arc<Semaphore>,
    chunk: &[ExpoPushMessage],
    agent: &str,
    event_type: &str,
) -> Vec<String> {
    for attempt in 0..MAX_PUSH_ATTEMPTS {
        let Ok(permit) = slots.clone().acquire_owned().await else {
            return Vec::new();
        };
        let result = client
            .post(EXPO_PUSH_URL)
            .header("Accept", "application/json")
            .header("Accept-Encoding", "gzip, deflate")
            .json(chunk)
            .timeout(Duration::from_secs(10))
            .send()
            .await;
        drop(permit);

        match result {
            Ok(response) if response.status().is_success() => {
                return match response.json::<ExpoPushResponse>().await {
                    Ok(payload) => unregistered_tokens(chunk, &payload),
                    Err(error) => {
                        tracing::warn!(%error, %agent, event_type, "invalid Expo push response");
                        Vec::new()
                    }
                };
            }
            Ok(response)
                if retryable_status(response.status()) && attempt + 1 < MAX_PUSH_ATTEMPTS => {}
            Ok(response) => {
                tracing::warn!(status = %response.status(), %agent, event_type, "mobile event delivery was rejected");
                return Vec::new();
            }
            Err(_) if attempt + 1 < MAX_PUSH_ATTEMPTS => {}
            Err(error) => {
                tracing::warn!(%error, %agent, event_type, "mobile event delivery failed");
                return Vec::new();
            }
        }

        tokio::time::sleep(Duration::from_secs(1 << attempt)).await;
    }
    Vec::new()
}

async fn deliver_agent_event(context: DeliveryContext, event: QueuedAgentEvent) {
    if context.presence.any_focused() {
        tracing::debug!(agent = %event.agent, "client focused; suppressing push");
        return;
    }
    let messages: Vec<ExpoPushMessage> = context
        .registry
        .push_targets(&event.event_type)
        .iter()
        .map(|device| message_for(device, &event.agent, &event.event_type, &event.event))
        .collect();
    // Every push funnels through here, so this line is the journal's only record that one left the
    // gateway; logging failures alone leaves a spurious push untraceable.
    if !messages.is_empty() {
        tracing::info!(
            agent = %event.agent,
            event_type = %event.event_type,
            state = text_field(&event.event, "state").unwrap_or(""),
            devices = messages.len(),
            "delivering mobile push"
        );
    }
    // Own each batch before it enters the spawned delivery worker. Borrowing
    // `messages.chunks()` through the buffered async stream makes the worker
    // future non-`'static`, which `tokio::spawn` correctly rejects.
    let batches: Vec<Vec<ExpoPushMessage>> = messages.chunks(100).map(<[_]>::to_vec).collect();
    let invalid_tokens: HashSet<String> = stream::iter(batches)
        .map(|chunk| {
            let client = context.http_client.clone();
            let slots = context.push_slots.clone();
            let agent = event.agent.clone();
            let event_type = event.event_type.clone();
            async move { send_push_chunk(&client, slots, &chunk, &agent, &event_type).await }
        })
        .buffer_unordered(MAX_CONCURRENT_PUSH_REQUESTS)
        .collect::<Vec<_>>()
        .await
        .into_iter()
        .flatten()
        .collect();
    if !invalid_tokens.is_empty() {
        let tokens: Vec<String> = invalid_tokens.into_iter().collect();
        context.registry.prune_push_tokens(&tokens);
        if let Err(error) = context.registry.flush_now().await {
            tracing::warn!(%error, "could not persist invalid mobile token removal");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn registration(token: &str) -> RegisterMobileDevice {
        RegisterMobileDevice {
            installation_id: "12880dc7-27c8-4ca7-9742-760a98e602e8".to_string(),
            token: token.to_string(),
            platform: MobilePlatform::Ios,
            gateway: Some("https://first.vesta.run".to_string()),
            event_types: vec!["chat".to_string()],
            previews: false,
        }
    }

    fn device(previews: bool, event_types: &[&str]) -> PushSubscription {
        PushSubscription {
            token: "ExponentPushToken[test]".to_string(),
            platform: MobilePlatform::Ios,
            gateway: Some("https://first.vesta.run".to_string()),
            event_types: event_types
                .iter()
                .map(|value| (*value).to_string())
                .collect(),
            previews,
            registered_at: 0,
        }
    }

    fn registry(dir: &std::path::Path) -> Arc<DeviceRegistry> {
        Arc::new(DeviceRegistry::load(dir))
    }

    #[test]
    fn private_chat_push_does_not_contain_message_text() {
        let event = serde_json::json!({"type": "chat", "title": "alex", "body": "Private reply"});
        let message = message_for(&device(false, &["chat"]), "alex", "chat", &event);
        assert_eq!(message.title, "alex");
        assert_eq!(message.body, "alex sent a new message.");
        assert!(!message.body.contains("Private"));
    }

    #[test]
    fn preview_chat_push_contains_bounded_message_text() {
        let event = serde_json::json!({"type": "chat", "title": "alex", "body": "Hello from Vesta"});
        let message = message_for(&device(true, &["chat"]), "alex", "chat", &event);
        assert_eq!(message.body, "Hello from Vesta");
        assert_eq!(message.data["eventType"], "chat");
    }

    #[test]
    fn subscription_names_are_extensible_but_bounded() {
        assert!(valid_event_type("chat"));
        assert!(valid_event_type("goal-complete"));
        assert!(!valid_event_type("Goal complete"));
        assert!(!valid_event_type(""));
        assert!(pushable_event_type("chat"));
        assert!(pushable_event_type("status"));
        assert!(!pushable_event_type("notification"));
    }

    #[test]
    fn lifecycle_status_copy_uses_gateway_status() {
        let event = serde_json::json!({
            "type": "status",
            "previousState": AgentStatus::Starting,
            "state": AgentStatus::Alive,
        });
        let message = message_for(&device(false, &["status"]), "alex", "status", &event);
        assert_eq!(message.body, "alex is available.");
        assert_eq!(message.data["eventType"], "status");
    }

    #[test]
    fn a_gateway_update_push_carries_the_gateway_s_own_text() {
        let event = serde_json::json!({
            "type": "gateway_updated",
            "title": "Updated to v0.1.190",
            "body": "Your gateway updated to v0.1.190.",
        });
        // No previews opt-in and no agent to name: the gateway's copy carries nothing private.
        let message = message_for(&device(false, &["status"]), "", "status", &event);
        assert_eq!(message.title, "Updated to v0.1.190");
        assert_eq!(message.body, "Your gateway updated to v0.1.190.");
        assert_eq!(message.data["route"], "/");
    }

    #[tokio::test]
    async fn each_pushable_kind_rides_the_subscription_that_already_covers_it() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, mut worker) = MobileApp::new(
            registry(directory.path()),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        app.push_user_notification("alex", "message", "alex", "hi");
        app.push_user_notification("", crate::update::UPDATED_NOTIFICATION_KIND, "Updated to v0.1.190", "done");
        // Never a push: it toasts on connected clients only.
        app.push_user_notification("alex", "rate_limited", "alex", "slow down");
        drop(app);

        let mut queued = Vec::new();
        while let Some(event) = worker.event_rx.recv().await {
            queued.push((event.event_type, event.event["type"].as_str().unwrap_or_default().to_string()));
        }
        assert_eq!(
            queued,
            vec![
                ("chat".to_string(), "chat".to_string()),
                ("status".to_string(), "gateway_updated".to_string()),
            ]
        );
    }

    fn lifecycle_entry(name: &str, status: AgentStatus) -> ListEntry {
        ListEntry {
            name: name.to_string(),
            status,
            ws_port: 4200,
            booting: false,
            started_at: None,
        }
    }

    fn lifecycle_app() -> (MobileApp, MobileAppWorker, tempfile::TempDir) {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, worker) = MobileApp::new(
            registry(directory.path()),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        app.begin_observing();
        (app, worker, directory)
    }

    fn observe(app: &MobileApp, agents: &[ListEntry]) {
        app.observe_agent_statuses(agents, &HashSet::new(), false);
    }

    async fn drain_status_events(
        app: MobileApp,
        mut worker: MobileAppWorker,
    ) -> Vec<(String, String, String)> {
        drop(app);
        let mut queued = Vec::new();
        while let Some(event) = worker.event_rx.recv().await {
            queued.push((
                event.agent,
                event.event["previousState"].as_str().unwrap_or_default().to_string(),
                event.event["state"].as_str().unwrap_or_default().to_string(),
            ));
        }
        queued
    }

    #[tokio::test]
    async fn a_stable_change_of_an_unoperated_agent_pushes_exactly_once() {
        let (app, worker, _dir) = lifecycle_app();
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Stopped)]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Stopped)]);
        assert_eq!(
            drain_status_events(app, worker).await,
            vec![("luna".to_string(), "alive".to_string(), "stopped".to_string())]
        );
    }

    #[tokio::test]
    async fn a_forgotten_agents_successor_seeds_silently_under_the_old_name() {
        let (app, worker, _dir) = lifecycle_app();
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        // Destroyed, then recreated under the same name: the fresh agent's first stable state
        // must seed like any first sighting, not diff against the dead predecessor.
        app.forget_agent("luna");
        observe(&app, &[lifecycle_entry("luna", AgentStatus::SettingUp)]);
        assert!(drain_status_events(app, worker).await.is_empty());
    }

    #[tokio::test]
    async fn first_stable_observations_seed_silently_so_boots_are_quiet() {
        let (app, worker, _dir) = lifecycle_app();
        // A boot: agents come up through starting, then land alive. Nothing is news.
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Starting)]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        assert!(drain_status_events(app, worker).await.is_empty());
    }

    #[tokio::test]
    async fn the_boot_reconciles_own_agent_cycle_never_pushes() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, worker) = MobileApp::new(
            registry(directory.path()),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        // The post-restart poll observes the shutdown-stopped agents before the boot reconcile
        // brings them up (the 5am self-update incident). None of it is agent news.
        observe(&app, &[lifecycle_entry("apollo", AgentStatus::Stopped)]);
        observe(&app, &[lifecycle_entry("apollo", AgentStatus::Alive)]);
        observe(&app, &[lifecycle_entry("athena", AgentStatus::Stopped)]);
        observe(&app, &[lifecycle_entry("athena", AgentStatus::NotAuthenticated)]);
        // Reconcile settles: the world as it stands seeds silently, and only a later real
        // change pushes.
        app.begin_observing();
        observe(&app, &[lifecycle_entry("apollo", AgentStatus::Alive)]);
        observe(&app, &[lifecycle_entry("athena", AgentStatus::NotAuthenticated)]);
        observe(&app, &[lifecycle_entry("apollo", AgentStatus::Dead)]);
        assert_eq!(
            drain_status_events(app, worker).await,
            vec![("apollo".to_string(), "alive".to_string(), "dead".to_string())]
        );
    }

    #[tokio::test]
    async fn the_shutdown_that_stops_every_agent_never_pushes() {
        let (app, worker, _dir) = lifecycle_app();
        observe(&app, &[lifecycle_entry("apollo", AgentStatus::Alive)]);
        // vestad stops every agent on its way out, and the poll keeps running while it does.
        app.stop_observing();
        observe(&app, &[lifecycle_entry("apollo", AgentStatus::Stopped)]);
        assert!(drain_status_events(app, worker).await.is_empty());
    }

    #[tokio::test]
    async fn transient_states_and_absence_never_move_the_stable_status() {
        let (app, worker, _dir) = lifecycle_app();
        // The backup-storm regression: a healthy agent flaps through probe noise (starting,
        // momentarily off the list) and back. Its stable status never moved, so no push.
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Starting)]);
        observe(&app, &[]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Restarting)]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Starting)]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        assert!(drain_status_events(app, worker).await.is_empty());
    }

    #[tokio::test]
    async fn an_operated_agents_planned_cycle_is_silent_but_a_real_death_reports() {
        let (app, worker, _dir) = lifecycle_app();
        let operated: HashSet<String> = HashSet::from(["luna".to_string()]);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        // A planned restart: the stop and recovery under the operation never move the map.
        app.observe_agent_statuses(&[lifecycle_entry("luna", AgentStatus::Stopped)], &operated, false);
        app.observe_agent_statuses(&[lifecycle_entry("luna", AgentStatus::Starting)], &operated, false);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        // A backup that killed the agent: once the operation clears, dead is real news.
        app.observe_agent_statuses(&[lifecycle_entry("luna", AgentStatus::Dead)], &operated, false);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Dead)]);
        assert_eq!(
            drain_status_events(app, worker).await,
            vec![("luna".to_string(), "alive".to_string(), "dead".to_string())]
        );
    }

    #[tokio::test]
    async fn a_running_gateway_operation_covers_every_agent() {
        let (app, worker, _dir) = lifecycle_app();
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        app.observe_agent_statuses(&[lifecycle_entry("luna", AgentStatus::Stopped)], &HashSet::new(), true);
        observe(&app, &[lifecycle_entry("luna", AgentStatus::Alive)]);
        assert!(drain_status_events(app, worker).await.is_empty());
    }

    #[test]
    fn validates_only_bounded_expo_tokens() {
        assert!(valid_expo_token("ExponentPushToken[abc]"));
        assert!(valid_expo_token("ExpoPushToken[abc]"));
        assert!(!valid_expo_token("apns-token"));
    }

    #[test]
    fn validates_bounded_installation_ids() {
        assert!(valid_installation_id(
            "12880dc7-27c8-4ca7-9742-760a98e602e8"
        ));
        assert!(!valid_installation_id(""));
        assert!(!valid_installation_id("installation id"));
    }

    #[test]
    fn validates_and_normalizes_gateway_identity() {
        assert_eq!(
            normalize_gateway_identity(Some(" https://first.vesta.run/ ".to_string())),
            Ok(Some("https://first.vesta.run".to_string()))
        );
        assert!(normalize_gateway_identity(Some("http://first.vesta.run".to_string())).is_err());
        assert!(
            normalize_gateway_identity(Some("https://first.vesta.run/path".to_string())).is_err()
        );
    }

    #[test]
    fn presence_gate_reports_focused_after_a_focused_client_record() {
        let presence = Arc::new(crate::sync::Presence::new());
        let conn = presence.connect();
        presence.record(
            conn,
            crate::sync::protocol::ClientContext {
                focused: true,
                client: crate::types::ClientKind::Mobile,
                resync: false,
                ..Default::default()
            },
            tokio::time::Instant::now(),
        );
        assert!(presence.any_focused());
    }

    #[test]
    fn constructor_does_not_spawn_or_require_a_runtime() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (_app, _worker) = MobileApp::new(
            registry(directory.path()),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
    }

    #[tokio::test]
    async fn registration_is_durable_before_it_becomes_visible() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, _worker) = MobileApp::new(
            registry(directory.path()),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        app.register_device(registration("ExponentPushToken[durable]"))
            .await
            .expect("registration");

        // Durable: a registry rebuilt from disk still has the push subscription.
        let reloaded = DeviceRegistry::load(directory.path());
        let targets = reloaded.push_targets("chat");
        assert_eq!(targets.len(), 1);
        assert_eq!(targets[0].token, "ExponentPushToken[durable]");
    }

    #[tokio::test]
    async fn registration_replaces_the_token_for_an_installation() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, _worker) = MobileApp::new(
            registry(directory.path()),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        app.register_device(registration("ExponentPushToken[first]"))
            .await
            .expect("first registration");
        app.register_device(registration("ExponentPushToken[rotated]"))
            .await
            .expect("rotated registration");

        let reloaded = DeviceRegistry::load(directory.path());
        let targets = reloaded.push_targets("chat");
        assert_eq!(targets.len(), 1);
        assert_eq!(targets[0].token, "ExponentPushToken[rotated]");
    }

    #[tokio::test]
    async fn registration_failure_rolls_back_out_of_memory() {
        let directory = tempfile::tempdir().expect("tempdir");
        let missing = directory.path().join("missing");
        let registry = registry(&missing);
        let (app, _worker) = MobileApp::new(
            registry.clone(),
            reqwest::Client::new(),
            Arc::new(crate::sync::Presence::new()),
        );
        let error = app
            .register_device(registration("ExponentPushToken[not-durable]"))
            .await
            .expect_err("missing directory must fail persistence");
        assert_eq!(error.0, StatusCode::INTERNAL_SERVER_ERROR);
        assert!(registry.snapshot().is_empty());
    }

    #[test]
    fn prunes_tokens_rejected_by_expo() {
        let messages = vec![
            message_for(
                &device(false, &["chat"]),
                "alex",
                "chat",
                &serde_json::json!({"type": "chat"}),
            ),
            ExpoPushMessage {
                to: "ExponentPushToken[healthy]".to_string(),
                ..message_for(
                    &device(false, &["chat"]),
                    "alex",
                    "chat",
                    &serde_json::json!({"type": "chat"}),
                )
            },
        ];
        let response = ExpoPushResponse {
            data: vec![
                ExpoPushTicket {
                    details: Some(ExpoPushErrorDetails {
                        error: Some("DeviceNotRegistered".to_string()),
                    }),
                },
                ExpoPushTicket { details: None },
            ],
        };
        assert_eq!(
            unregistered_tokens(&messages, &response),
            vec!["ExponentPushToken[test]".to_string()]
        );
    }
}
