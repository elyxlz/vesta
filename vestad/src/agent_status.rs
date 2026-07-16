use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use bollard::Docker;
use futures_util::StreamExt;
use tokio::sync::watch;

use crate::docker::{self, ListEntry};
use crate::settings::ServiceEntry;

const POLL_INTERVAL_SECS: u64 = 3;

// --- High-level status queries (used by serve.rs handlers and the poll task) ---

pub async fn get_status(
    docker: &Docker,
    http_client: &reqwest::Client,
    name: &str,
    agents_dir: &std::path::Path,
    rebuilding: &docker::RebuildTracker,
) -> Result<docker::StatusJson, docker::DockerError> {
    docker::validate_name(name)?;
    let cname = docker::container_name(name);
    let info = docker::inspect_container(docker, &cname, Some(agents_dir)).await;

    let status = if rebuilding.is_rebuilding(name) {
        docker::AgentStatus::Rebuilding
    } else {
        combined_status(http_client, agents_dir, &cname, &info).await
    };
    Ok(docker::StatusJson {
        name: name.to_string(),
        status,
        id: info.id,
        ws_port: info.port.unwrap_or(0),
    })
}

pub async fn list_agents(
    docker: &Docker,
    http_client: &reqwest::Client,
    agents_dir: &std::path::Path,
    rebuilding: &docker::RebuildTracker,
) -> Vec<ListEntry> {
    let agents = docker::list_managed_agents(docker).await;
    let mut entries = Vec::new();
    for docker::ManagedAgent { cname, agent_name } in &agents {
        let info = docker::inspect_container(docker, cname, Some(agents_dir)).await;
        entries.push(ListEntry {
            name: agent_name.clone(),
            status: combined_status(http_client, agents_dir, cname, &info).await,
            ws_port: info.port.unwrap_or(0),
            started_at: info.started_at.clone(),
        });
    }
    apply_rebuilding(entries, rebuilding.names())
}

/// Overlay live rebuild state onto the docker-derived listing: a mid-rebuild agent reports
/// `Rebuilding`, and one whose container is momentarily removed (between the rebuild's remove
/// and create steps) stays listed instead of vanishing. Names are sorted so the merged list is
/// deterministic across polls (the watch channel diffs on equality).
fn apply_rebuilding(mut entries: Vec<ListEntry>, mut rebuilding: Vec<String>) -> Vec<ListEntry> {
    rebuilding.sort();
    for name in rebuilding {
        match entries.iter_mut().find(|entry| entry.name == name) {
            Some(entry) => entry.status = docker::AgentStatus::Rebuilding,
            None => entries.push(ListEntry {
                name,
                status: docker::AgentStatus::Rebuilding,
                ws_port: 0,
                started_at: None,
            }),
        }
    }
    entries
}

async fn combined_status(
    http_client: &reqwest::Client,
    agents_dir: &std::path::Path,
    cname: &str,
    info: &docker::ContainerInfo,
) -> docker::AgentStatus {
    match info.status {
        docker::ContainerStatus::Running => {
            // WS port not yet bound → agent still booting.
            if !info.port.is_some_and(is_agent_ready) {
                return docker::AgentStatus::Starting;
            }
            // Agent's own GET /config is the source of truth for provider auth.
            // If the WS server is up but /config isn't responding yet (transient
            // mid-boot state), treat as Starting; the next ~3s poll will resolve.
            let agent_name = docker::name_from_cname(cname);
            let provider = crate::agent_provider::AgentProvider::new(http_client, agents_dir, agent_name);
            match provider.status().await {
                Ok(s) => status_from_readiness(s.authed, s.setup_complete, s.provider_configured),
                Err(_) => docker::AgentStatus::Starting,
            }
        }
        docker::ContainerStatus::Dead => docker::AgentStatus::Dead,
        docker::ContainerStatus::Stopped => docker::AgentStatus::Stopped,
        docker::ContainerStatus::NotFound => docker::AgentStatus::NotFound,
    }
}

/// Map the agent's `GET /status` readiness slice to its `AgentStatus`. An authenticated agent is
/// `SettingUp` until first-start finishes, then `Alive`; a not-authenticated agent is `Unprovisioned`
/// when it has no provider chosen at all, else `NotAuthenticated` (a chosen credential is invalid).
fn status_from_readiness(authed: bool, setup_complete: bool, provider_configured: bool) -> docker::AgentStatus {
    match (authed, setup_complete, provider_configured) {
        (true, true, _) => docker::AgentStatus::Alive,
        (true, false, _) => docker::AgentStatus::SettingUp,
        (false, _, true) => docker::AgentStatus::NotAuthenticated,
        (false, _, false) => docker::AgentStatus::Unprovisioned,
    }
}

/// The agent binds its WS port only once it's ready to serve requests.
const AGENT_READY_TIMEOUT_MS: u64 = 200;

fn is_agent_ready(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(AGENT_READY_TIMEOUT_MS),
    )
    .is_ok()
}

/// Invoked with the fresh agent list whenever the polled list actually changes
/// (the daemon persists it into `status.json` for the `vestad status` banner).
pub type OnAgentsChanged = Arc<dyn Fn(&[ListEntry]) + Send + Sync>;

/// Cached agent list + activity states, updated by a background task.
/// WS handlers subscribe via the watch receivers.
pub struct AgentStatusCache {
    agents_tx: watch::Sender<Vec<ListEntry>>,
    agents_rx: watch::Receiver<Vec<ListEntry>>,
    activity_tx: watch::Sender<HashMap<String, String>>,
    activity_rx: watch::Receiver<HashMap<String, String>>,
    /// Per-agent IANA timezone (agent name -> zone), reported on each agent's connect snapshot.
    /// The auto-update scheduler reads it to aim the fleet restart at each agent's local quiet window.
    timezones_tx: watch::Sender<HashMap<String, String>>,
    timezones_rx: watch::Receiver<HashMap<String, String>>,
    services_tx: watch::Sender<HashMap<String, HashMap<String, ServiceEntry>>>,
    services_rx: watch::Receiver<HashMap<String, HashMap<String, ServiceEntry>>>,
    /// Notification-only channel -- wakes WS loops when any invalidation occurs.
    invalidations_tx: watch::Sender<()>,
    invalidations_rx: watch::Receiver<()>,
    /// Monotonic per-service revision counters (agent -> service -> rev).
    /// Bumped when a service's state changes; clients refetch on a higher rev.
    revs: Mutex<HashMap<String, HashMap<String, u64>>>,
}

impl AgentStatusCache {
    pub fn new() -> Self {
        let (agents_tx, agents_rx) = watch::channel(Vec::new());
        let (activity_tx, activity_rx) = watch::channel(HashMap::new());
        let (timezones_tx, timezones_rx) = watch::channel(HashMap::new());
        let (services_tx, services_rx) = watch::channel(HashMap::new());
        let (invalidations_tx, invalidations_rx) = watch::channel(());
        Self {
            agents_tx,
            agents_rx,
            activity_tx,
            activity_rx,
            timezones_tx,
            timezones_rx,
            services_tx,
            services_rx,
            invalidations_tx,
            invalidations_rx,
            revs: Mutex::new(HashMap::new()),
        }
    }

    pub fn subscribe_agents(&self) -> watch::Receiver<Vec<ListEntry>> {
        self.agents_rx.clone()
    }

    /// Snapshot of the current agent listing (name, status, port).
    pub fn agents(&self) -> Vec<ListEntry> {
        self.agents_rx.borrow().clone()
    }

    pub fn subscribe_activity(&self) -> watch::Receiver<HashMap<String, String>> {
        self.activity_rx.clone()
    }

    /// Snapshot of each alive agent's IANA timezone, as last reported on its connect snapshot.
    pub fn timezones(&self) -> HashMap<String, String> {
        self.timezones_rx.borrow().clone()
    }

    pub fn subscribe_services(
        &self,
    ) -> watch::Receiver<HashMap<String, HashMap<String, ServiceEntry>>> {
        self.services_rx.clone()
    }

    /// Notify subscribers that services changed for an agent.
    pub fn update_services(&self, all_services: &HashMap<String, HashMap<String, ServiceEntry>>) {
        self.services_tx.send_if_modified(|current| {
            if *current == *all_services {
                return false;
            }
            current.clone_from(all_services);
            true
        });
    }

    pub fn subscribe_invalidations(&self) -> watch::Receiver<()> {
        self.invalidations_rx.clone()
    }

    /// Bump the monotonic revision for a service, signalling clients to refetch it.
    pub fn invalidate_service(&self, agent: &str, service: &str) {
        {
            let mut revs = self.revs.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            *revs
                .entry(agent.to_string())
                .or_default()
                .entry(service.to_string())
                .or_insert(0) += 1;
        }
        // Wake all WS loops.
        let _ = self.invalidations_tx.send(());
    }

    /// Current revision for each agent+service.
    pub fn service_revs(&self) -> HashMap<String, HashMap<String, u64>> {
        self.revs.lock().unwrap_or_else(std::sync::PoisonError::into_inner).clone()
    }
}

/// Spawns the background polling loop that keeps the cache fresh and manages
/// internal WebSocket connections to alive agents for activity state relay.
pub fn spawn_agent_status_task(
    cache: Arc<AgentStatusCache>,
    docker: Docker,
    http_client: reqwest::Client,
    agents_dir: PathBuf,
    on_agents_changed: OnAgentsChanged,
    rebuilding: docker::RebuildTracker,
) {
    tokio::spawn(async move {
        let mut agent_ws_handles: HashMap<String, AgentWsHandle> = HashMap::new();
        let (activity_event_tx, mut activity_event_rx) =
            tokio::sync::mpsc::channel::<(String, AgentUpdate)>(64);

        loop {
            // Poll agent list via async bollard
            let agents = list_agents(&docker, &http_client, &agents_dir, &rebuilding).await;

            // Update the agents watch channel (only notifies if changed)
            let changed = cache.agents_tx.send_if_modified(|current| {
                if *current == agents {
                    return false;
                }
                current.clone_from(&agents);
                true
            });
            if changed {
                on_agents_changed(&agents);
            }

            // Reconcile internal WS connections for activity state
            let alive_agents: HashMap<String, u16> = agents
                .iter()
                .filter(|a| a.status == docker::AgentStatus::Alive)
                .map(|a| (a.name.clone(), a.ws_port))
                .collect();

            // Close connections for agents that are no longer alive
            agent_ws_handles.retain(|name, handle| {
                if alive_agents.contains_key(name) {
                    true
                } else {
                    handle.abort_handle.abort();
                    // Clear activity + timezone state for dead agents
                    cache.activity_tx.send_modify(|states| {
                        states.remove(name);
                    });
                    cache.timezones_tx.send_modify(|zones| {
                        zones.remove(name);
                    });
                    false
                }
            });

            // Open connections for newly alive agents
            for (name, ws_port) in &alive_agents {
                if agent_ws_handles.contains_key(name) {
                    continue;
                }
                let agent_name = name.clone();
                let port = *ws_port;
                let tx = activity_event_tx.clone();
                let dir = agents_dir.clone();

                let join_handle = tokio::spawn(async move {
                    agent_activity_listener(agent_name, port, dir, tx).await;
                });

                agent_ws_handles.insert(
                    name.clone(),
                    AgentWsHandle {
                        abort_handle: join_handle.abort_handle(),
                    },
                );
            }

            // Drain any pending agent updates before sleeping
            while let Ok((name, update)) = activity_event_rx.try_recv() {
                apply_agent_update(&cache, name, update);
            }

            // Wait for next poll interval OR an agent update
            tokio::select! {
                () = tokio::time::sleep(std::time::Duration::from_secs(POLL_INTERVAL_SECS)) => {}
                Some((name, update)) = activity_event_rx.recv() => {
                    apply_agent_update(&cache, name, update);
                }
            }
        }
    });
}

struct AgentWsHandle {
    abort_handle: tokio::task::AbortHandle,
}

/// A change relayed from an agent's WS: its live activity state, or its IANA timezone (sent once
/// per connect on the snapshot). Multiplexed over one channel so the listener needs no second wire.
enum AgentUpdate {
    Activity(String),
    Timezone(String),
}

fn apply_agent_update(cache: &AgentStatusCache, name: String, update: AgentUpdate) {
    match update {
        AgentUpdate::Activity(state) => cache.activity_tx.send_modify(|states| {
            states.insert(name, state);
        }),
        AgentUpdate::Timezone(zone) => cache.timezones_tx.send_modify(|zones| {
            zones.insert(name, zone);
        }),
    }
}

/// Connects to a single agent's WebSocket and relays activity state changes
/// back through the mpsc channel. Reconnects on failure.
async fn agent_activity_listener(
    name: String,
    ws_port: u16,
    agents_dir: PathBuf,
    tx: tokio::sync::mpsc::Sender<(String, AgentUpdate)>,
) {
    const RECONNECT_BASE_MS: u64 = 1000;
    const RECONNECT_MAX_MS: u64 = 15000;
    let mut delay_ms = RECONNECT_BASE_MS;

    loop {
        // Read the agent token fresh each attempt (it may rotate)
        let agent_name = name.clone();
        let dir = agents_dir.clone();
        let token = tokio::task::spawn_blocking(move || {
            let (_port, token) = docker::read_agent_port_and_token(&agent_name, &dir);
            token
        })
        .await
        .ok()
        .flatten();

        let url = match &token {
            Some(t) => format!("ws://localhost:{ws_port}/ws?agent_token={t}"),
            None => format!("ws://localhost:{ws_port}/ws"),
        };

        match tokio_tungstenite::connect_async(&url).await {
            Ok((ws, _)) => {
                delay_ms = RECONNECT_BASE_MS;
                let (_write, mut read) = ws.split();

                while let Some(Ok(msg)) = read.next().await {
                    let text = match &msg {
                        tokio_tungstenite::tungstenite::Message::Text(t) => t.as_str(),
                        _ => continue,
                    };
                    let parsed: serde_json::Value = match serde_json::from_str(text) {
                        Ok(v) => v,
                        Err(_) => continue,
                    };
                    let msg_type = parsed.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    // `state` is top-level on both the live `status` event and the connect `snapshot`.
                    if msg_type == "status" || msg_type == "snapshot" {
                        if let Some(state) = parsed.get("state").and_then(|v| v.as_str()) {
                            let _ = tx.send((name.clone(), AgentUpdate::Activity(state.to_string()))).await;
                        }
                    }
                    // The agent's IANA timezone rides the connect snapshot under `config`.
                    if msg_type == "snapshot" {
                        if let Some(zone) = parsed
                            .get("config")
                            .and_then(|config| config.get("timezone"))
                            .and_then(|value| value.as_str())
                        {
                            let _ = tx.send((name.clone(), AgentUpdate::Timezone(zone.to_string()))).await;
                        }
                    }
                }

                // Connection lost -- reset to idle so the frontend doesn't
                // stay stuck on the last activity state (e.g. "thinking").
                let _ = tx.send((name.clone(), AgentUpdate::Activity("idle".into()))).await;
            }
            Err(err) => {
                tracing::debug!(agent = %name, port = ws_port, error = %err, "agent activity ws connect failed");
            }
        }

        tokio::time::sleep(std::time::Duration::from_millis(delay_ms)).await;
        delay_ms = (delay_ms * 2).min(RECONNECT_MAX_MS);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn apply_rebuilding_overrides_status_and_keeps_missing_agents_listed() {
        let entries = vec![
            ListEntry {
                name: "apollo".into(),
                status: docker::AgentStatus::Stopped,
                ws_port: 4200,
                started_at: None,
            },
            ListEntry {
                name: "hera".into(),
                status: docker::AgentStatus::Alive,
                ws_port: 4201,
                started_at: Some("2026-01-01T00:00:00Z".into()),
            },
        ];
        // apollo is mid-rebuild with its container still present; zeus is mid-rebuild
        // with its container removed (it dropped out of the docker listing entirely).
        let merged = apply_rebuilding(entries, vec!["apollo".into(), "zeus".into()]);
        assert_eq!(merged.len(), 3);
        assert_eq!(merged[0].name, "apollo");
        assert_eq!(merged[0].status, docker::AgentStatus::Rebuilding);
        assert_eq!(merged[0].ws_port, 4200);
        assert_eq!(merged[1].name, "hera");
        assert_eq!(merged[1].status, docker::AgentStatus::Alive);
        assert_eq!(merged[2].name, "zeus");
        assert_eq!(merged[2].status, docker::AgentStatus::Rebuilding);
        assert_eq!(merged[2].ws_port, 0);
        assert_eq!(merged[2].started_at, None);
    }

    #[test]
    fn status_from_readiness_distinguishes_unprovisioned_from_unauthenticated() {
        use docker::AgentStatus::*;
        // (authed, setup_complete, provider_configured) -> AgentStatus
        assert_eq!(status_from_readiness(true, true, true), Alive);
        assert_eq!(status_from_readiness(true, false, true), SettingUp);
        assert_eq!(status_from_readiness(false, false, true), NotAuthenticated);
        assert_eq!(status_from_readiness(false, false, false), Unprovisioned);
    }

    #[test]
    fn invalidate_bumps_rev() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("agent1", "dashboard");
        assert_eq!(cache.service_revs()["agent1"]["dashboard"], 1);
    }

    #[test]
    fn invalidate_multiple_bumps_rev_incrementally() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "voice");
        cache.invalidate_service("a", "voice");
        assert_eq!(cache.service_revs()["a"]["voice"], 2);
    }

    #[test]
    fn tracks_multiple_agents_and_services() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a1", "voice");
        cache.invalidate_service("a2", "dashboard");
        let revs = cache.service_revs();
        assert_eq!(revs["a1"]["voice"], 1);
        assert_eq!(revs["a2"]["dashboard"], 1);
    }

    #[test]
    fn empty_revs_when_nothing_invalidated() {
        let cache = AgentStatusCache::new();
        assert!(cache.service_revs().is_empty());
    }
}
