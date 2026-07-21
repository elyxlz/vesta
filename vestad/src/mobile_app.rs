//! Server-side business logic for the native mobile app.
//!
//! `vestad` observes every live agent event through its existing internal WebSocket,
//! then this module owns the complete remote-notification path: device registration,
//! subscription policy, persistence, payload rendering, queueing, and Expo delivery.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use axum::{extract::State, http::StatusCode, Json};
use futures_util::{stream, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, Mutex, Semaphore};

use crate::docker::{AgentStatus, ListEntry};
use crate::state::{err_response, ok_json, SharedState};

const EXPO_PUSH_URL: &str = "https://exp.host/--/api/v2/push/send";
const MAX_INSTALLATION_ID_LENGTH: usize = 128;
const MAX_PUSH_TOKEN_LENGTH: usize = 512;
const MAX_EVENT_TYPES: usize = 32;
const MAX_PUSH_ATTEMPTS: usize = 3;
const MOBILE_EVENT_QUEUE_CAPACITY: usize = 256;
const MAX_CONCURRENT_EVENT_DELIVERIES: usize = 6;
const PUSHABLE_EVENT_TYPES: &[&str] = &["chat", "status"];
const MAX_CONCURRENT_PUSH_REQUESTS: usize = 6;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum MobilePlatform {
    Ios,
    Android,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
struct MobileDevice {
    installation_id: String,
    token: String,
    platform: MobilePlatform,
    #[serde(default)]
    gateway: Option<String>,
    event_types: Vec<String>,
    previews: bool,
    registered_at: u64,
}

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
    devices: Arc<Mutex<Vec<MobileDevice>>>,
    update_lock: Arc<Mutex<()>>,
    config_dir: PathBuf,
    http_client: reqwest::Client,
    push_slots: Arc<Semaphore>,
}

#[derive(Clone, Debug)]
pub(crate) struct MobileApp {
    devices: Arc<Mutex<Vec<MobileDevice>>>,
    update_lock: Arc<Mutex<()>>,
    config_dir: PathBuf,
    event_tx: mpsc::Sender<QueuedAgentEvent>,
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

fn store_path(config_dir: &Path) -> PathBuf {
    config_dir.join("mobile-devices.json")
}

fn load_devices(config_dir: &Path) -> Vec<MobileDevice> {
    let path = store_path(config_dir);
    match std::fs::read(&path) {
        Ok(bytes) => match serde_json::from_slice(&bytes) {
            Ok(devices) => devices,
            Err(error) => {
                tracing::error!(%error, path = %path.display(), "mobile device registry is corrupt");
                Vec::new()
            }
        },
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(error) => {
            tracing::error!(%error, path = %path.display(), "could not read mobile device registry");
            Vec::new()
        }
    }
}

async fn persist_devices(config_dir: &Path, devices: &[MobileDevice]) -> Result<(), String> {
    let json = serde_json::to_vec(devices)
        .map_err(|error| format!("could not serialize mobile device registry: {error}"))?;
    let path = store_path(config_dir);
    let temporary = path.with_extension("json.tmp");
    tokio::fs::write(&temporary, json)
        .await
        .map_err(|error| format!("could not write {}: {error}", temporary.display()))?;
    if let Err(error) = tokio::fs::rename(&temporary, &path).await {
        let _ = tokio::fs::remove_file(&temporary).await;
        return Err(format!("could not replace {}: {error}", path.display()));
    }
    Ok(())
}

async fn update_devices(
    devices: &Arc<Mutex<Vec<MobileDevice>>>,
    update_lock: &Arc<Mutex<()>>,
    config_dir: &Path,
    update: impl FnOnce(&mut Vec<MobileDevice>),
) -> Result<(), String> {
    // Serialize mutations without holding the device read lock across filesystem
    // IO. Readers continue using the last durable snapshot until the new one has
    // been atomically persisted.
    let _update_guard = update_lock.lock().await;
    let mut next = devices.lock().await.clone();
    update(&mut next);
    persist_devices(config_dir, &next).await?;
    *devices.lock().await = next;
    Ok(())
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

fn agent_status_changes(
    previous: &[ListEntry],
    current: &[ListEntry],
) -> Vec<(String, AgentStatus, AgentStatus)> {
    current
        .iter()
        .filter_map(|agent| {
            let old = previous.iter().find(|old| old.name == agent.name)?;
            (old.status != agent.status).then(|| (agent.name.clone(), old.status, agent.status))
        })
        .collect()
}

impl MobileApp {
    pub(crate) fn new(
        config_dir: PathBuf,
        http_client: reqwest::Client,
    ) -> (Self, MobileAppWorker) {
        let devices = Arc::new(Mutex::new(load_devices(&config_dir)));
        let update_lock = Arc::new(Mutex::new(()));
        let push_slots = Arc::new(Semaphore::new(MAX_CONCURRENT_PUSH_REQUESTS));
        let (event_tx, event_rx) = mpsc::channel(MOBILE_EVENT_QUEUE_CAPACITY);
        let delivery_context = DeliveryContext {
            devices: devices.clone(),
            update_lock: update_lock.clone(),
            config_dir: config_dir.clone(),
            http_client,
            push_slots,
        };
        (
            Self {
                devices,
                update_lock,
                config_dir,
                event_tx,
            },
            MobileAppWorker {
                context: delivery_context,
                event_rx,
            },
        )
    }

    /// Enqueue a mobile push for an agent-injected user notification (`POST /agents/{name}/user-notification`).
    /// Only a new message pushes: it reuses the existing `chat` device subscription, so registered
    /// devices need no change. A `rate_limited` user notification toasts on connected clients but is
    /// never a mobile push, so it is skipped here (chat-only device subscriptions dropped it before too).
    pub(crate) fn push_user_notification(&self, agent: &str, kind: &str, title: &str, body: &str) {
        if kind != "message" {
            return;
        }
        self.queue_event(agent, "chat", serde_json::json!({"type": "chat", "title": title, "body": body}));
    }

    /// Compare two gateway-owned lifecycle snapshots and enqueue only real status
    /// transitions. Agents absent from either side are ignored: this suppresses the
    /// initial vestad snapshot and avoids treating creation/deletion as a transition.
    pub(crate) fn observe_agent_status_changes(
        &self,
        previous: &[ListEntry],
        current: &[ListEntry],
    ) {
        for (agent, previous_status, status) in agent_status_changes(previous, current) {
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
        let device = MobileDevice {
            installation_id: installation_id.clone(),
            token: token.clone(),
            platform: input.platform,
            gateway,
            event_types,
            previews: input.previews,
            registered_at: crate::time_utils::now_epoch_secs(),
        };
        update_devices(
            &self.devices,
            &self.update_lock,
            &self.config_dir,
            move |devices| {
                devices.retain(|existing| {
                    existing.installation_id != installation_id && existing.token != token
                });
                devices.push(device);
            },
        )
        .await
        .map_err(|error| {
            tracing::error!(%error, "could not persist mobile device registration");
            err_response(
                StatusCode::INTERNAL_SERVER_ERROR,
                "could not persist mobile device registration",
            )
        })
    }

    async fn delete_device(
        &self,
        token: &str,
    ) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
        let token = token.to_string();
        update_devices(
            &self.devices,
            &self.update_lock,
            &self.config_dir,
            move |devices| devices.retain(|device| device.token != token),
        )
        .await
        .map_err(|error| {
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

fn message_for(
    device: &MobileDevice,
    agent: &str,
    event_type: &str,
    event: &serde_json::Value,
) -> ExpoPushMessage {
    let (title, body, route) = match event_type {
        "chat" => {
            let title = text_field(event, "title").unwrap_or(agent).to_string();
            let body = match text_field(event, "body") {
                Some(text) if device.previews && !text.is_empty() => text.to_string(),
                _ => format!("{agent} sent a new message."),
            };
            (title, body, format!("/agent/{agent}/chat"))
        }
        "status" => {
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
    let devices = context.devices.lock().await.clone();
    let messages: Vec<ExpoPushMessage> = devices
        .iter()
        .filter(|device| {
            device
                .event_types
                .iter()
                .any(|candidate| candidate == &event.event_type)
        })
        .map(|device| message_for(device, &event.agent, &event.event_type, &event.event))
        .collect();
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
        if let Err(error) = update_devices(
            &context.devices,
            &context.update_lock,
            &context.config_dir,
            move |devices| {
                devices.retain(|device| !invalid_tokens.contains(&device.token));
            },
        )
        .await
        {
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

    fn device(previews: bool, event_types: &[&str]) -> MobileDevice {
        MobileDevice {
            installation_id: "12880dc7-27c8-4ca7-9742-760a98e602e8".to_string(),
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
    fn lifecycle_diff_ignores_initial_agents_and_activity_only_changes() {
        let entry = |name: &str, status: AgentStatus, ws_port: u16| ListEntry {
            name: name.to_string(),
            status,
            ws_port,
            started_at: None,
        };
        let initial = vec![entry("alex", AgentStatus::Alive, 4200)];
        assert!(agent_status_changes(&[], &initial).is_empty());

        let same_status = vec![entry("alex", AgentStatus::Alive, 4300)];
        assert!(agent_status_changes(&initial, &same_status).is_empty());

        let stopped = vec![entry("alex", AgentStatus::Stopped, 0)];
        assert_eq!(
            agent_status_changes(&initial, &stopped),
            vec![("alex".to_string(), AgentStatus::Alive, AgentStatus::Stopped,)]
        );
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
    fn constructor_does_not_spawn_or_require_a_runtime() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (_app, _worker) =
            MobileApp::new(directory.path().to_path_buf(), reqwest::Client::new());
    }

    #[tokio::test]
    async fn registration_is_durable_before_it_becomes_visible() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, _worker) = MobileApp::new(directory.path().to_path_buf(), reqwest::Client::new());
        app.register_device(registration("ExponentPushToken[durable]"))
            .await
            .expect("registration");

        let stored = load_devices(directory.path());
        assert_eq!(stored.len(), 1);
        assert_eq!(
            stored[0].installation_id,
            "12880dc7-27c8-4ca7-9742-760a98e602e8"
        );
        assert_eq!(stored[0].token, "ExponentPushToken[durable]");
        assert_eq!(app.devices.lock().await.as_slice(), stored.as_slice());
    }

    #[tokio::test]
    async fn registration_replaces_the_token_for_an_installation() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (app, _worker) = MobileApp::new(directory.path().to_path_buf(), reqwest::Client::new());
        app.register_device(registration("ExponentPushToken[first]"))
            .await
            .expect("first registration");
        app.register_device(registration("ExponentPushToken[rotated]"))
            .await
            .expect("rotated registration");

        let stored = load_devices(directory.path());
        assert_eq!(stored.len(), 1);
        assert_eq!(stored[0].token, "ExponentPushToken[rotated]");
    }

    #[tokio::test]
    async fn registration_failure_does_not_mutate_memory() {
        let directory = tempfile::tempdir().expect("tempdir");
        let missing = directory.path().join("missing");
        let (app, _worker) = MobileApp::new(missing, reqwest::Client::new());
        let error = app
            .register_device(registration("ExponentPushToken[not-durable]"))
            .await
            .expect_err("missing directory must fail persistence");
        assert_eq!(error.0, StatusCode::INTERNAL_SERVER_ERROR);
        assert!(app.devices.lock().await.is_empty());
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
