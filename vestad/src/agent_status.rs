use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use bollard::Docker;
use futures_util::StreamExt;
use tokio::sync::watch;

use crate::docker::{self, ListEntry};
use crate::mobile_app::MobileApp;
use crate::settings::ServiceEntry;
use crate::state::{err_response, ok_json, SharedState};
use crate::sync::{activity_state, notification_change, SyncHub};

const POLL_INTERVAL_SECS: u64 = 3;

pub async fn invalidate_service_handler(
    State(state): State<SharedState>,
    Path((name, service_name)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let settings = state.settings.read().await;
    let exists = settings
        .services
        .get(&name)
        .is_some_and(|s| s.contains_key(&service_name));
    if !exists {
        return Err(err_response(
            StatusCode::NOT_FOUND,
            &format!("service '{service_name}' not registered for agent '{name}'"),
        ));
    }
    drop(settings);

    state
        .agent_status_cache
        .invalidate_service(&name, &service_name);
    tracing::debug!(agent = %name, service = %service_name, "service invalidated");
    Ok(ok_json())
}

// --- High-level status queries (used by serve.rs handlers and the poll task) ---

pub async fn get_status(
    docker: &Docker,
    http_client: &reqwest::Client,
    cache: &AgentStatusCache,
    name: &str,
    agents_dir: &std::path::Path,
    rebuilding: &docker::RebuildTracker,
) -> Result<docker::StatusJson, docker::DockerError> {
    docker::validate_name(name)?;
    let cname = docker::container_name(name);
    let info = docker::inspect_container(docker, &cname, Some(agents_dir)).await;

    let status = if rebuilding.is_rebuilding(name) {
        docker::AgentStatus::Rebuilding
    } else if cache.operation(name) == Some(docker::AgentOperation::Restarting) {
        docker::AgentStatus::Restarting
    } else {
        combined_status(docker, http_client, agents_dir, cache, &cname, &info).await
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
    cache: &AgentStatusCache,
    agents_dir: &std::path::Path,
    rebuilding: &docker::RebuildTracker,
) -> Vec<ListEntry> {
    let agents = docker::list_managed_agents(docker).await;
    let mut entries = Vec::new();
    for docker::ManagedAgent { cname, agent_name } in &agents {
        let info = docker::inspect_container(docker, cname, Some(agents_dir)).await;
        let status = combined_status(docker, http_client, agents_dir, cache, cname, &info).await;
        entries.push(ListEntry {
            name: agent_name.clone(),
            status,
            ws_port: info.port.unwrap_or(0),
            booting: status == docker::AgentStatus::Alive
                && cache.readiness(agent_name).is_some_and(|r| !r.boot_complete),
            started_at: info.started_at.clone(),
        });
    }
    let entries = overlay_status(
        entries,
        restarting_names(cache.operations()),
        docker::AgentStatus::Restarting,
    );
    overlay_status(entries, rebuilding.names(), docker::AgentStatus::Rebuilding)
}

/// The agents whose in-flight operation projects a status of its own. Only a restart does: it owns
/// the whole stop/start cycle, while a backup or restore rides the roster's `operation` field and
/// leaves the container's own status alone.
fn restarting_names(operations: HashMap<String, docker::AgentOperation>) -> Vec<String> {
    operations
        .into_iter()
        .filter(|(_, operation)| *operation == docker::AgentOperation::Restarting)
        .map(|(name, _)| name)
        .collect()
}

/// Overlay a transitional status onto the docker-derived listing: a named agent takes the status,
/// and one whose container is momentarily removed (mid-rebuild, or recreated by a restart) stays
/// listed instead of vanishing, so clients render one deliberate action rather than a gone agent.
/// Both sides join on the normalized name, and names are sorted so the merged list is
/// deterministic across polls (the watch channel diffs on equality).
fn overlay_status(
    mut entries: Vec<ListEntry>,
    mut names: Vec<String>,
    status: docker::AgentStatus,
) -> Vec<ListEntry> {
    names.sort();
    for name in names {
        match entries
            .iter_mut()
            .find(|entry| docker::normalize_name(&entry.name) == name)
        {
            Some(entry) => entry.status = status,
            None => entries.push(ListEntry {
                name,
                status,
                ws_port: 0,
                booting: false,
                started_at: None,
            }),
        }
    }
    entries
}

async fn combined_status(
    docker: &Docker,
    http_client: &reqwest::Client,
    agents_dir: &std::path::Path,
    cache: &AgentStatusCache,
    cname: &str,
    info: &docker::ContainerInfo,
) -> docker::AgentStatus {
    match info.status {
        docker::ContainerStatus::Running => {
            let agent_name = docker::name_from_cname(cname);
            // Resolve the agent's address before anything can return: the tap dial loop reads
            // the cached address and never resolves one itself, so a status that returned first
            // would deadlock it (no address, so no tap, so no address).
            let host = cache.bridge_ip_or_resolve(docker, cname, &agent_name).await;
            // The held tap connection is the liveness truth: it rides through backup pauses
            // and IO load that make one-shot probes flap, and the listener redials until the
            // agent's API genuinely serves. Running without a tap is the one meaning of
            // `Starting`: booting, or actually stalled.
            if !cache.tap_connected(&agent_name) {
                return docker::AgentStatus::Starting;
            }
            // Refresh the readiness flags best-effort: a fetch that fails under load keeps
            // the last known flags rather than demoting a connected agent.
            if let Some(host) = host {
                let provider = crate::agent_provider::AgentProvider::new(
                    http_client,
                    agents_dir,
                    agent_name.clone(),
                    host,
                );
                if let Ok(s) = provider.status().await {
                    cache.set_readiness(
                        &agent_name,
                        Readiness {
                            status: status_from_readiness(s.authed, s.setup_complete, s.provider_configured),
                            boot_complete: s.boot_complete,
                        },
                    );
                }
            }
            match cache.readiness(&agent_name) {
                Some(r) => r.status,
                None => docker::AgentStatus::Starting,
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
fn status_from_readiness(
    authed: bool,
    setup_complete: bool,
    provider_configured: bool,
) -> docker::AgentStatus {
    match (authed, setup_complete, provider_configured) {
        (true, true, _) => docker::AgentStatus::Alive,
        (true, false, _) => docker::AgentStatus::SettingUp,
        (false, _, true) => docker::AgentStatus::NotAuthenticated,
        (false, _, false) => docker::AgentStatus::Unprovisioned,
    }
}

/// Publishes an agent's in-flight operation on the roster for as long as it is held, clearing it on
/// drop so an early `?` return cannot strand the agent looking busy forever. The lifecycle push
/// also reads the operations registry: an operated agent's status changes are planned work, not news.
pub struct PublishedOperation {
    cache: Arc<AgentStatusCache>,
    name: String,
}

impl PublishedOperation {
    pub fn new(cache: Arc<AgentStatusCache>, name: &str, operation: docker::AgentOperation) -> Self {
        let normalized = docker::normalize_name(name);
        cache.set_operation(&normalized, operation);
        Self {
            cache,
            name: normalized,
        }
    }
}

impl Drop for PublishedOperation {
    fn drop(&mut self) {
        self.cache.clear_operation(&self.name);
    }
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
    /// Per-agent presence-notification preference (agent name -> enabled), reported on each agent's
    /// connect snapshot. The push path reads it to suppress a push when the user is focused.
    presence_notifications_tx: watch::Sender<HashMap<String, bool>>,
    presence_notifications_rx: watch::Receiver<HashMap<String, bool>>,
    services_tx: watch::Sender<HashMap<String, HashMap<String, ServiceEntry>>>,
    services_rx: watch::Receiver<HashMap<String, HashMap<String, ServiceEntry>>>,
    /// Notification-only channel -- wakes WS loops when any invalidation occurs.
    invalidations_tx: watch::Sender<()>,
    invalidations_rx: watch::Receiver<()>,
    /// Monotonic per-service revision counters (agent -> service -> rev).
    /// Bumped when a service's state changes; clients refetch on a higher rev.
    revs: Mutex<HashMap<String, HashMap<String, u64>>>,
    /// Coarse, in-flight build phase per agent, keyed by normalized name. Written by the create
    /// handler as `create_agent` progresses; the roster unions these in so onboarding shows the
    /// phase even before the container exists (Pulling/Building run first). Entries exist only for
    /// the duration of a create and are removed when it settles.
    build_phases: Mutex<HashMap<String, docker::BuildPhase>>,
    /// Each agent's address on its own private bridge network. Cached because the proxy needs
    /// it per request and a live Docker lookup there would cost a round trip each time; the WS
    /// tap and the config/provider relay read it too.
    bridge_ips: Mutex<HashMap<String, String>>,
    /// In-flight long-running operation per agent, keyed by normalized name. Written by the backup
    /// and restore handlers for the duration of the work, so every connected client sees it and not
    /// just the one holding the SSE stream.
    operations: Mutex<HashMap<String, docker::AgentOperation>>,
    /// Agents whose WS tap is currently connected. The tap is the liveness primitive: a held
    /// connection rides through backup pauses and IO load that make per-poll probes flap, so a
    /// running container is `Starting` exactly while its tap is down and never in between.
    tap_connected: Mutex<HashSet<String>>,
    /// Each agent's last successfully fetched readiness flags. Status derivation reads these
    /// while the tap is connected, so a flags fetch that fails under load keeps the last known
    /// answer instead of demoting a live agent.
    readiness: Mutex<HashMap<String, Readiness>>,
}

/// What the last successful `GET /status` fetch resolved to: the readiness-derived reachable
/// state, plus the boot-progress flag the roster labels with.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Readiness {
    pub status: docker::AgentStatus,
    pub boot_complete: bool,
}

impl AgentStatusCache {
    pub fn new() -> Self {
        let (agents_tx, agents_rx) = watch::channel(Vec::new());
        let (activity_tx, activity_rx) = watch::channel(HashMap::new());
        let (timezones_tx, timezones_rx) = watch::channel(HashMap::new());
        let (presence_notifications_tx, presence_notifications_rx) = watch::channel(HashMap::new());
        let (services_tx, services_rx) = watch::channel(HashMap::new());
        let (invalidations_tx, invalidations_rx) = watch::channel(());
        Self {
            agents_tx,
            agents_rx,
            activity_tx,
            activity_rx,
            timezones_tx,
            timezones_rx,
            presence_notifications_tx,
            presence_notifications_rx,
            services_tx,
            services_rx,
            invalidations_tx,
            invalidations_rx,
            revs: Mutex::new(HashMap::new()),
            build_phases: Mutex::new(HashMap::new()),
            bridge_ips: Mutex::new(HashMap::new()),
            operations: Mutex::new(HashMap::new()),
            tap_connected: Mutex::new(HashSet::new()),
            readiness: Mutex::new(HashMap::new()),
        }
    }

    /// Record whether `name`'s WS tap is connected; the listener writes this on every connect
    /// and disconnect, and status derivation reads it as the liveness truth.
    pub fn set_tap_connected(&self, name: &str, connected: bool) {
        let mut taps = self
            .tap_connected
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if connected {
            taps.insert(name.to_string());
        } else {
            taps.remove(name);
        }
    }

    pub fn tap_connected(&self, name: &str) -> bool {
        self.tap_connected
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .contains(name)
    }

    fn set_readiness(&self, name: &str, readiness: Readiness) {
        self.readiness
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(name.to_string(), readiness);
    }

    fn readiness(&self, name: &str) -> Option<Readiness> {
        self.readiness
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(name)
            .copied()
    }

    /// Drop a destroyed agent's observation state (readiness, tap mark), so a later agent
    /// created under the same name starts from nothing instead of its predecessor's flags.
    pub fn forget_agent(&self, name: &str) {
        let normalized = docker::normalize_name(name);
        self.readiness
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&normalized);
        self.set_tap_connected(&normalized, false);
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

    /// Whether every alive agent is currently idle. Gates the maintenance pass so snapshots and a
    /// pending update land between turns; an agent with no reported activity counts as idle (the
    /// tap resets activity to idle on disconnect).
    pub fn all_alive_idle(&self) -> bool {
        let states = self.activity_rx.borrow();
        self.agents_rx
            .borrow()
            .iter()
            .filter(|entry| entry.status == docker::AgentStatus::Alive)
            .all(|entry| states.get(&entry.name).is_none_or(|state| state == "idle"))
    }

    /// Snapshot of each alive agent's IANA timezone, as last reported on its connect snapshot.
    pub fn timezones(&self) -> HashMap<String, String> {
        self.timezones_rx.borrow().clone()
    }

    /// Whether the agent wants presence notifications, as last reported on its connect snapshot.
    /// Absent (never reported) defaults to enabled, matching the config default.
    pub fn presence_notifications_enabled(&self, agent: &str) -> bool {
        self.presence_notifications_rx.borrow().get(agent).copied().unwrap_or(true)
    }

    /// Whether a presence notification should reach `agent`: it serves its WS tap now (so vestad
    /// holds its real preference) and that preference is enabled. An agent whose tap is down reads
    /// as enabled by default, so gating on the live tap is what keeps a mid-restart opt-out honored.
    pub fn presence_notification_target(&self, agent: &str) -> bool {
        let serving = self.agents_rx.borrow().iter().any(|entry| entry.name == agent && entry.status.serves_ws());
        serving && self.presence_notifications_enabled(agent)
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
            let mut revs = self
                .revs
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            *revs
                .entry(agent.to_string())
                .or_default()
                .entry(service.to_string())
                .or_insert(0) += 1;
        }
        // Wake all WS loops.
        let _ = self.invalidations_tx.send(());
    }

    /// Record the current build phase for `name` (normalized) and wake WS loops so the transition
    /// reaches onboarding within a tick. Lock poisoning is recovered in place: a panic mid-build
    /// must not wedge later creates.
    pub fn set_build_phase(&self, name: &str, phase: docker::BuildPhase) {
        self.build_phases
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(name.to_string(), phase);
        let _ = self.invalidations_tx.send(());
    }

    /// Drop the build-phase entry for `name` once a create settles (success or error) and wake WS
    /// loops so the synthetic mid-build row retires promptly.
    pub fn clear_build_phase(&self, name: &str) {
        self.build_phases
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(name);
        let _ = self.invalidations_tx.send(());
    }

    /// Snapshot of every in-flight build phase (normalized name -> phase).
    pub fn build_phases(&self) -> HashMap<String, docker::BuildPhase> {
        self.build_phases
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// Record the long-running operation now running against `name` and wake WS loops so every
    /// client picks it up within a tick.
    pub fn set_operation(&self, name: &str, operation: docker::AgentOperation) {
        self.operations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(name.to_string(), operation);
        let _ = self.invalidations_tx.send(());
    }

    /// Drop the operation entry for `name` once the work settles, success or error.
    pub fn clear_operation(&self, name: &str) {
        self.operations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(name);
        let _ = self.invalidations_tx.send(());
    }

    /// One agent's in-flight operation, joined on the normalized name the registry is keyed by.
    pub fn operation(&self, name: &str) -> Option<docker::AgentOperation> {
        self.operations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(&docker::normalize_name(name))
            .copied()
    }

    /// Snapshot of every in-flight operation (normalized name -> operation).
    pub fn operations(&self) -> HashMap<String, docker::AgentOperation> {
        self.operations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// Current revision for each agent+service.
    pub fn service_revs(&self) -> HashMap<String, HashMap<String, u64>> {
        self.revs
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// Record the resolved bridge IP for `agent`, replacing any prior value. Private: the cache
    /// fills itself in `bridge_ip_or_resolve`, so no caller needs to push an address in.
    fn set_bridge_ip(&self, agent: &str, ip: String) {
        self.bridge_ips
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(agent.to_string(), ip);
    }

    /// The agent's current bridge IP, if resolved.
    pub fn bridge_ip(&self, agent: &str) -> Option<String> {
        self.bridge_ips
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(agent)
            .cloned()
    }

    /// Drop the cached bridge IP (agent removed, or a resolve failed and the caller wants a
    /// clean retry next time rather than an indefinitely stale address).
    pub fn clear_bridge_ip(&self, agent: &str) {
        self.bridge_ips
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(agent);
    }

    /// The agent's bridge IP: cached if already resolved, otherwise a live Docker resolve that
    /// populates the cache on success. Every caller that needs this address hits the same narrow
    /// race (a request landing between container start and the one-shot resolve that follows
    /// it), so they share one retry policy here instead of each inventing its own.
    pub async fn bridge_ip_or_resolve(
        &self,
        docker: &Docker,
        cname: &str,
        agent: &str,
    ) -> Option<String> {
        if let Some(ip) = self.bridge_ip(agent) {
            return Some(ip);
        }
        let ip = docker::resolve_bridge_ip(docker, cname, agent).await?;
        self.set_bridge_ip(agent, ip.clone());
        Some(ip)
    }
}

/// The collaborators the agent-status poll task owns for its lifetime: the shared cache, a docker
/// handle and HTTP client for polling, and the roster/rebuild/mobile/sync collaborators it
/// reconciles each tick.
pub struct AgentStatusTaskDeps {
    pub cache: Arc<AgentStatusCache>,
    pub docker: Docker,
    pub http_client: reqwest::Client,
    pub agents_dir: PathBuf,
    pub on_agents_changed: OnAgentsChanged,
    pub rebuilding: docker::RebuildTracker,
    pub mobile_app: MobileApp,
    pub sync_hub: Arc<SyncHub>,
    /// The gateway's one operation slot, read per poll: while an operation (an update) runs,
    /// every agent's lifecycle churn is that operation's doing, not agent news.
    pub gateway_operation: Arc<crate::operation::OperationSlot>,
}

/// The agents the poll loop keeps a WS tap open to, and the port each is dialed on: every agent
/// with a running (or transitionally running) container, whose port is known. A dialable agent
/// whose port is not readable yet (a transiently unreadable env file) is left for a later poll
/// rather than dialed at zero, because a listener captures its port once and would redial zero
/// forever, wedging the agent at `Starting`.
fn tappable_agents(agents: &[ListEntry]) -> HashMap<String, u16> {
    agents
        .iter()
        .filter(|agent| agent.status.dialable() && agent.ws_port != 0)
        .map(|agent| (agent.name.clone(), agent.ws_port))
        .collect()
}

/// Spawns the background polling loop that keeps the cache fresh and manages
/// internal WebSocket connections to observe live events from alive agents.
pub fn spawn_agent_status_task(deps: AgentStatusTaskDeps) {
    let AgentStatusTaskDeps {
        cache,
        docker,
        http_client,
        agents_dir,
        on_agents_changed,
        rebuilding,
        mobile_app,
        sync_hub,
        gateway_operation,
    } = deps;
    tokio::spawn(async move {
        let mut agent_ws_handles: HashMap<String, AgentWsHandle> = HashMap::new();
        let (activity_event_tx, mut activity_event_rx) =
            tokio::sync::mpsc::channel::<(String, AgentUpdate)>(64);

        loop {
            // Poll agent list via async bollard
            let agents = list_agents(&docker, &http_client, &cache, &agents_dir, &rebuilding).await;

            // Mobile lifecycle notifications come from vestad's authoritative agent list,
            // never the agent EventBus's thinking/idle activity.
            mobile_app.observe_agent_statuses(
                &agents,
                &cache.operations().into_keys().collect(),
                gateway_operation.running_phase().is_some(),
            );

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

            // Reconcile internal WS connections (the tap: liveness, activity, and the sync live
            // edge) for every agent with a running container, `Starting` included: the dial
            // loop connecting is what ends `Starting`, never a one-shot probe.
            let tappable_agents = tappable_agents(&agents);

            // Close connections for agents whose container is no longer running
            agent_ws_handles.retain(|name, handle| {
                if tappable_agents.contains_key(name) {
                    true
                } else {
                    handle.abort_handle.abort();
                    // An aborted listener runs no cleanup of its own, so clear its liveness
                    // mark and activity + timezone state here.
                    cache.set_tap_connected(name, false);
                    cache.activity_tx.send_modify(|states| {
                        states.remove(name);
                    });
                    cache.timezones_tx.send_modify(|zones| {
                        zones.remove(name);
                    });
                    cache.presence_notifications_tx.send_modify(|map| {
                        map.remove(name);
                    });
                    sync_hub.forget_agent(name);
                    false
                }
            });

            // Open connections for newly reachable agents
            for (name, ws_port) in &tappable_agents {
                if agent_ws_handles.contains_key(name) {
                    continue;
                }
                let agent_name = name.clone();
                let port = *ws_port;
                let tx = activity_event_tx.clone();
                let dir = agents_dir.clone();
                let hub = sync_hub.clone();
                let listener_cache = cache.clone();

                let join_handle = tokio::spawn(async move {
                    agent_event_listener(agent_name, port, dir, tx, hub, listener_cache).await;
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

/// A change relayed from an agent's WS: its live activity state, or a value sent once per connect on
/// the snapshot (its IANA timezone, its presence-notifications toggle). Multiplexed over one channel
/// so the listener needs no second wire.
enum AgentUpdate {
    Activity(String),
    Timezone(String),
    PresenceNotificationsEnabled(bool),
}

fn apply_agent_update(cache: &AgentStatusCache, name: String, update: AgentUpdate) {
    match update {
        AgentUpdate::Activity(state) => cache.activity_tx.send_modify(|states| {
            states.insert(name, state);
        }),
        AgentUpdate::Timezone(zone) => cache.timezones_tx.send_modify(|zones| {
            zones.insert(name, zone);
        }),
        AgentUpdate::PresenceNotificationsEnabled(enabled) => cache.presence_notifications_tx.send_modify(|map| {
            map.insert(name, enabled);
        }),
    }
}

/// Connects to a single agent's WebSocket as a read-only tap, relays activity/timezone to the cache,
/// and feeds the sync hub's notifications projection. Reconnects on failure.
async fn agent_event_listener(
    name: String,
    ws_port: u16,
    agents_dir: PathBuf,
    tx: tokio::sync::mpsc::Sender<(String, AgentUpdate)>,
    hub: Arc<SyncHub>,
    cache: Arc<AgentStatusCache>,
) {
    const RECONNECT_BASE_MS: u64 = 1000;
    const RECONNECT_MAX_MS: u64 = 15000;
    let mut delay_ms = RECONNECT_BASE_MS;

    loop {
        // Read the agent token fresh each attempt (it may rotate).
        let agent_name = name.clone();
        let dir = agents_dir.clone();
        let token = tokio::task::spawn_blocking(move || {
            let (_port, token) = docker::read_agent_port_and_token(&agent_name, &dir);
            token
        })
        .await
        .ok()
        .flatten();

        // Read fresh each attempt: a container recreated between attempts (a rebuild, a network
        // reattach) comes back on a different address, and this loop is what picks it up.
        let Some(host) = cache.bridge_ip(&name) else {
            tracing::debug!(agent = %name, "bridge IP not yet resolved; will retry");
            tokio::time::sleep(std::time::Duration::from_millis(delay_ms)).await;
            delay_ms = (delay_ms * 2).min(RECONNECT_MAX_MS);
            continue;
        };

        let url = match &token {
            Some(t) => format!("ws://{host}:{ws_port}/ws?agent_token={t}"),
            None => format!("ws://{host}:{ws_port}/ws"),
        };

        match tokio_tungstenite::connect_async(&url).await {
            Ok((ws, _)) => {
                delay_ms = RECONNECT_BASE_MS;
                cache.set_tap_connected(&name, true);
                let (_, mut read) = ws.split();

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
                        if let Some(state) = activity_state(&parsed) {
                            let _ = tx.send((name.clone(), AgentUpdate::Activity(state))).await;
                        }
                    }

                    if msg_type == "snapshot" {
                        // Timezone rides the snapshot's `config` (unchanged behavior).
                        if let Some(zone) = parsed
                            .get("config")
                            .and_then(|config| config.get("timezone"))
                            .and_then(|value| value.as_str())
                        {
                            let _ = tx.send((name.clone(), AgentUpdate::Timezone(zone.to_string()))).await;
                        }
                        if let Some(enabled) = parsed
                            .get("config")
                            .and_then(|config| config.get("presence_notifications_enabled"))
                            .and_then(serde_json::Value::as_bool)
                        {
                            let _ = tx.send((name.clone(), AgentUpdate::PresenceNotificationsEnabled(enabled))).await;
                        }
                        // Reseed pending notifications from the snapshot's authoritative id set,
                        // deduped by id against later live changes.
                        hub.seed_notifications(&name, &pending_ids(&parsed));
                        continue;
                    }

                    // A live event: feed the notifications projection. User notifications + mobile push
                    // no longer ride the tap; they come from the agent's user-notification primitive
                    // (POST /agents/{name}/user-notification), which fans a `user_notification` delta and an Expo push.
                    if let Some(change) = notification_change(&parsed) {
                        hub.apply_notification(&name, change);
                    }
                }

                // Connection lost: the agent is unreachable again (restarting, or genuinely
                // stalled), and activity resets to idle so the frontend does not stay stuck on
                // the last state.
                cache.set_tap_connected(&name, false);
                let _ = tx.send((name.clone(), AgentUpdate::Activity("idle".into()))).await;
            }
            Err(err) => {
                tracing::debug!(agent = %name, port = ws_port, error = %err, "agent tap connect failed");
            }
        }

        tokio::time::sleep(std::time::Duration::from_millis(delay_ms)).await;
        delay_ms = (delay_ms * 2).min(RECONNECT_MAX_MS);
    }
}

/// The pending notification ids on a connect snapshot (`notifications.pending`, file stems).
fn pending_ids(snapshot: &serde_json::Value) -> Vec<String> {
    snapshot
        .get("notifications")
        .and_then(|n| n.get("pending"))
        .and_then(|p| p.as_array())
        .map(|items| items.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bridge_ip_round_trips_and_clears() {
        let cache = AgentStatusCache::new();
        assert_eq!(cache.bridge_ip("ada"), None);

        cache.set_bridge_ip("ada", "172.20.0.5".to_string());
        assert_eq!(cache.bridge_ip("ada"), Some("172.20.0.5".to_string()));

        cache.set_bridge_ip("ada", "172.20.0.9".to_string());
        assert_eq!(cache.bridge_ip("ada"), Some("172.20.0.9".to_string()));

        cache.clear_bridge_ip("ada");
        assert_eq!(cache.bridge_ip("ada"), None);
    }

    #[test]
    fn all_alive_idle_reads_alive_agents_only() {
        let cache = AgentStatusCache::new();
        // No agents at all: vacuously idle.
        assert!(cache.all_alive_idle());

        cache.agents_tx.send_replace(vec![
            ListEntry {
                name: "apollo".into(),
                status: docker::AgentStatus::Alive,
                ws_port: 4200,
                booting: false,
                started_at: None,
            },
            ListEntry {
                name: "hera".into(),
                status: docker::AgentStatus::Stopped,
                ws_port: 4201,
                booting: false,
                started_at: None,
            },
        ]);
        // Alive agent with no reported activity counts as idle; stopped agents never count.
        assert!(cache.all_alive_idle());

        cache.activity_tx.send_replace(HashMap::from([("apollo".to_string(), "thinking".to_string())]));
        assert!(!cache.all_alive_idle());

        cache.activity_tx.send_replace(HashMap::from([
            ("apollo".to_string(), "idle".to_string()),
            ("hera".to_string(), "thinking".to_string()),
        ]));
        // A busy state on a non-alive agent (stale tap residue) does not block maintenance.
        assert!(cache.all_alive_idle());
    }

    #[test]
    fn overlay_status_overrides_status_and_keeps_missing_agents_listed() {
        let entries = vec![
            ListEntry {
                name: "apollo".into(),
                status: docker::AgentStatus::Stopped,
                ws_port: 4200,
                booting: false,
                started_at: None,
            },
            ListEntry {
                name: "hera".into(),
                status: docker::AgentStatus::Alive,
                ws_port: 4201,
                booting: false,
                started_at: Some("2026-01-01T00:00:00Z".into()),
            },
        ];
        // apollo is mid-rebuild with its container still present; zeus is mid-rebuild
        // with its container removed (it dropped out of the docker listing entirely).
        let merged = overlay_status(
            entries,
            vec!["apollo".into(), "zeus".into()],
            docker::AgentStatus::Rebuilding,
        );
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
    fn tappable_agents_dials_running_agents_with_a_known_port_only() {
        let entry = |name: &str, status: docker::AgentStatus, ws_port: u16| ListEntry {
            name: name.into(),
            status,
            ws_port,
            booting: false,
            started_at: None,
        };
        let dialed = tappable_agents(&[
            // Dialed: alive and starting are both running-container states with a known port.
            entry("alive", docker::AgentStatus::Alive, 4200),
            entry("booting", docker::AgentStatus::Starting, 4201),
            // Not dialed: a stopped container has nothing to tap.
            entry("stopped", docker::AgentStatus::Stopped, 4202),
            // Not dialed: dialable but its port is not readable yet, so it waits for a later poll
            // rather than being dialed at zero and wedged (the deadlock class this guards).
            entry("portless", docker::AgentStatus::Alive, 0),
        ]);
        assert_eq!(dialed.len(), 2);
        assert_eq!(dialed.get("alive"), Some(&4200));
        assert_eq!(dialed.get("booting"), Some(&4201));
        assert!(!dialed.contains_key("stopped"));
        assert!(!dialed.contains_key("portless"));
    }

    #[test]
    fn a_planned_restart_projects_its_cycle_even_through_a_recreate() {
        let entries = vec![
            ListEntry {
                name: "apollo".into(),
                status: docker::AgentStatus::Stopped,
                ws_port: 4200,
                booting: false,
                started_at: None,
            },
            ListEntry {
                name: "hera".into(),
                status: docker::AgentStatus::Alive,
                ws_port: 4201,
                booting: false,
                started_at: None,
            },
        ];
        // apollo is mid-restart with its container stopped; zeus is mid-restart with its
        // container momentarily recreated (off the docker listing); hera's backup must not
        // touch its status, because the roster's operation field already carries it.
        let operations = HashMap::from([
            ("apollo".to_string(), docker::AgentOperation::Restarting),
            ("zeus".to_string(), docker::AgentOperation::Restarting),
            ("hera".to_string(), docker::AgentOperation::BackingUp),
        ]);
        let merged = overlay_status(
            entries,
            restarting_names(operations),
            docker::AgentStatus::Restarting,
        );
        assert_eq!(merged.len(), 3);
        assert_eq!(merged[0].status, docker::AgentStatus::Restarting);
        assert_eq!(merged[1].status, docker::AgentStatus::Alive);
        assert_eq!(merged[2].name, "zeus");
        assert_eq!(merged[2].status, docker::AgentStatus::Restarting);
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

    #[test]
    fn presence_notifications_default_enabled_until_reported() {
        let cache = AgentStatusCache::new();
        assert!(cache.presence_notifications_enabled("scout"));
        cache.presence_notifications_tx.send_modify(|m| {
            m.insert("scout".into(), false);
        });
        assert!(!cache.presence_notifications_enabled("scout"));
    }

    #[test]
    fn presence_notification_target_requires_a_serving_enabled_agent() {
        let cache = AgentStatusCache::new();
        cache.agents_tx.send_modify(|agents| {
            agents.extend([
                ListEntry { name: "scout".into(), status: docker::AgentStatus::Alive, ws_port: 1, booting: false, started_at: None },
                ListEntry { name: "quiet".into(), status: docker::AgentStatus::Alive, ws_port: 2, booting: false, started_at: None },
                ListEntry { name: "asleep".into(), status: docker::AgentStatus::Stopped, ws_port: 3, booting: false, started_at: None },
                // Mid-restart: its tap is down, so its preference reads as the enabled default.
                ListEntry { name: "booting".into(), status: docker::AgentStatus::Starting, ws_port: 4, booting: false, started_at: None },
            ]);
        });
        cache.presence_notifications_tx.send_modify(|preferences| {
            preferences.insert("quiet".into(), false);
        });

        assert!(cache.presence_notification_target("scout"));
        // Opted out: enabled is false even though it serves.
        assert!(!cache.presence_notification_target("quiet"));
        // Stopped: cannot receive it.
        assert!(!cache.presence_notification_target("asleep"));
        // Mid-restart: tap down, so a true opt-out could not be read; do not notify.
        assert!(!cache.presence_notification_target("booting"));
        // Unknown agent: not serving.
        assert!(!cache.presence_notification_target("ghost"));
    }

    use crate::sync::SyncHub;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as WsMessage;

    /// A fake agent WS server: on connect it sends a snapshot (one pending id) and one live chat
    /// event. Returns its bound port.
    async fn fake_agent() -> u16 {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let port = listener.local_addr().expect("addr").port();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.expect("accept");
            let ws = tokio_tungstenite::accept_async(stream).await.expect("handshake");
            let (mut write, _read) = ws.split();
            let snapshot = serde_json::json!({
                "type": "snapshot", "state": "idle",
                "notifications": {"pending": ["n1"]},
                "config": {"timezone": "America/New_York"},
            });
            let chat = serde_json::json!({"id": 5, "type": "chat", "text": "live"});
            write.send(WsMessage::Text(snapshot.to_string().into())).await.expect("send snapshot");
            write.send(WsMessage::Text(chat.to_string().into())).await.expect("send chat");
        });
        port
    }

    #[tokio::test]
    async fn tap_seeds_pending_from_the_snapshot() {
        let hub = std::sync::Arc::new(SyncHub::new());
        let dir = tempfile::tempdir().expect("tempdir");
        let port = fake_agent().await;
        let cache = std::sync::Arc::new(AgentStatusCache::new());
        cache.set_bridge_ip("fake", "127.0.0.1".to_string());

        let listener = tokio::spawn({
            let hub = hub.clone();
            let (tx, _rx) = tokio::sync::mpsc::channel::<(String, AgentUpdate)>(16);
            let dir = dir.path().to_path_buf();
            let cache = cache.clone();
            async move { agent_event_listener("fake".into(), port, dir, tx, hub, cache).await }
        });

        // The tap seeds one pending notification from the snapshot's authoritative id set; the live
        // chat event that follows is not a notification change, so pending stays at one.
        let mut seeded = false;
        for _ in 0..100 {
            if hub.pending_all().get("fake").is_some_and(|p| p.len() == 1) {
                seeded = true;
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        assert!(seeded, "the snapshot's pending id should seed the notifications projection");

        listener.abort();
    }
}
