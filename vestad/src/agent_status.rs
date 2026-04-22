use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use bollard::Docker;
use futures_util::StreamExt;
use tokio::sync::watch;

use crate::docker::{self, ListEntry};
use crate::serve::ServiceEntry;

/// Per-service invalidation state (ephemeral, not persisted).
struct InvalidationEntry {
    rev: u64,
    pending_scopes: Vec<String>,
    /// `true` when any invalidation omitted a scope (= full invalidation).
    full: bool,
}

/// Snapshot returned by [`AgentStatusCache::drain_invalidations`].
#[derive(Clone, Default)]
pub struct DrainedInvalidation {
    pub rev: u64,
    /// Empty vec means full invalidation.
    pub scopes: Vec<String>,
}

const POLL_INTERVAL_SECS: u64 = 3;

/// Cached agent list + activity states, updated by a background task.
/// WS handlers subscribe via the watch receivers.
pub struct AgentStatusCache {
    agents_tx: watch::Sender<Vec<ListEntry>>,
    agents_rx: watch::Receiver<Vec<ListEntry>>,
    activity_tx: watch::Sender<HashMap<String, String>>,
    activity_rx: watch::Receiver<HashMap<String, String>>,
    services_tx: watch::Sender<HashMap<String, HashMap<String, ServiceEntry>>>,
    services_rx: watch::Receiver<HashMap<String, HashMap<String, ServiceEntry>>>,
    /// Notification-only channel -- wakes WS loops when any invalidation occurs.
    invalidations_tx: watch::Sender<()>,
    invalidations_rx: watch::Receiver<()>,
    /// Accumulated invalidation state, drained when WS pushes to clients.
    invalidation_state: Mutex<HashMap<String, HashMap<String, InvalidationEntry>>>,
}

impl AgentStatusCache {
    pub fn new() -> Self {
        let (agents_tx, agents_rx) = watch::channel(Vec::new());
        let (activity_tx, activity_rx) = watch::channel(HashMap::new());
        let (services_tx, services_rx) = watch::channel(HashMap::new());
        let (invalidations_tx, invalidations_rx) = watch::channel(());
        Self {
            agents_tx,
            agents_rx,
            activity_tx,
            activity_rx,
            services_tx,
            services_rx,
            invalidations_tx,
            invalidations_rx,
            invalidation_state: Mutex::new(HashMap::new()),
        }
    }

    pub fn subscribe_agents(&self) -> watch::Receiver<Vec<ListEntry>> {
        self.agents_rx.clone()
    }

    pub fn subscribe_activity(&self) -> watch::Receiver<HashMap<String, String>> {
        self.activity_rx.clone()
    }

    pub fn subscribe_services(&self) -> watch::Receiver<HashMap<String, HashMap<String, ServiceEntry>>> {
        self.services_rx.clone()
    }

    /// Notify subscribers that services changed for an agent.
    pub fn update_services(&self, all_services: &HashMap<String, HashMap<String, ServiceEntry>>) {
        self.services_tx.send_if_modified(|current| {
            if *current == *all_services {
                return false;
            }
            *current = all_services.clone();
            true
        });
    }

    pub fn subscribe_invalidations(&self) -> watch::Receiver<()> {
        self.invalidations_rx.clone()
    }

    /// Bump the revision for a service and accumulate an optional scope.
    /// If `scope` is `None`, marks it as a full invalidation.
    pub fn invalidate_service(&self, agent: &str, service: &str, scope: Option<&str>) {
        {
            let mut state = self.invalidation_state.lock().unwrap();
            let entry = state
                .entry(agent.to_string())
                .or_default()
                .entry(service.to_string())
                .or_insert_with(|| InvalidationEntry {
                    rev: 0,
                    pending_scopes: Vec::new(),
                    full: false,
                });
            entry.rev += 1;
            match scope {
                Some(s) => {
                    if !entry.pending_scopes.contains(&s.to_string()) {
                        entry.pending_scopes.push(s.to_string());
                    }
                }
                None => entry.full = true,
            }
        }
        // Wake all WS loops.
        let _ = self.invalidations_tx.send(());
    }

    /// Snapshot current invalidation state and clear pending scopes.
    /// Returns rev + accumulated scopes for each agent+service.
    pub fn drain_invalidations(&self) -> HashMap<String, HashMap<String, DrainedInvalidation>> {
        let mut state = self.invalidation_state.lock().unwrap();
        let mut result: HashMap<String, HashMap<String, DrainedInvalidation>> = HashMap::new();
        for (agent, services) in state.iter_mut() {
            let agent_map = result.entry(agent.clone()).or_default();
            for (service, entry) in services.iter_mut() {
                let scopes = if entry.full {
                    Vec::new()
                } else {
                    entry.pending_scopes.clone()
                };
                agent_map.insert(
                    service.clone(),
                    DrainedInvalidation {
                        rev: entry.rev,
                        scopes,
                    },
                );
                entry.pending_scopes.clear();
                entry.full = false;
            }
        }
        result
    }
}

/// Spawns the background polling loop that keeps the cache fresh and manages
/// internal WebSocket connections to alive agents for activity state relay.
pub fn spawn_agent_status_task(cache: Arc<AgentStatusCache>, docker: Docker, agents_dir: PathBuf) {
    tokio::spawn(async move {
        let mut agent_ws_handles: HashMap<String, AgentWsHandle> = HashMap::new();
        let (activity_event_tx, mut activity_event_rx) =
            tokio::sync::mpsc::channel::<(String, String)>(64);

        loop {
            // Poll agent list via async bollard
            let agents = docker::list_agents(&docker, &agents_dir).await;

            // Update the agents watch channel (only notifies if changed)
            cache.agents_tx.send_if_modified(|current| {
                if *current == agents {
                    return false;
                }
                *current = agents.clone();
                true
            });

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
                    // Clear activity state for dead agents
                    cache.activity_tx.send_modify(|states| {
                        states.remove(name);
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

            // Drain any pending activity events before sleeping
            while let Ok((name, state)) = activity_event_rx.try_recv() {
                cache.activity_tx.send_modify(|states| {
                    states.insert(name, state);
                });
            }

            // Wait for next poll interval OR an activity event
            tokio::select! {
                _ = tokio::time::sleep(std::time::Duration::from_secs(POLL_INTERVAL_SECS)) => {}
                Some((name, state)) = activity_event_rx.recv() => {
                    cache.activity_tx.send_modify(|states| {
                        states.insert(name, state);
                    });
                }
            }
        }
    });
}

struct AgentWsHandle {
    abort_handle: tokio::task::AbortHandle,
}

/// Connects to a single agent's WebSocket and relays activity state changes
/// back through the mpsc channel. Reconnects on failure.
async fn agent_activity_listener(
    name: String,
    ws_port: u16,
    agents_dir: PathBuf,
    tx: tokio::sync::mpsc::Sender<(String, String)>,
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
            Some(t) => format!("ws://localhost:{}/ws?agent_token={}", ws_port, t),
            None => format!("ws://localhost:{}/ws", ws_port),
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
                    if msg_type == "status" || msg_type == "history" {
                        if let Some(state) = parsed.get("state").and_then(|v| v.as_str()) {
                            let _ = tx.send((name.clone(), state.to_string())).await;
                        }
                    }
                }

                // Connection lost -- reset to idle so the frontend doesn't
                // stay stuck on the last activity state (e.g. "thinking").
                let _ = tx.send((name.clone(), "idle".into())).await;
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
    fn invalidate_bumps_rev() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("agent1", "dashboard", None);
        let inv = cache.drain_invalidations();
        let d = &inv["agent1"]["dashboard"];
        assert_eq!(d.rev, 1);
    }

    #[test]
    fn invalidate_multiple_bumps_rev_incrementally() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "voice", Some("stt"));
        cache.invalidate_service("a", "voice", Some("tts"));
        let inv = cache.drain_invalidations();
        assert_eq!(inv["a"]["voice"].rev, 2);
    }

    #[test]
    fn scoped_invalidation_accumulates_scopes() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "voice", Some("stt"));
        cache.invalidate_service("a", "voice", Some("tts"));
        let inv = cache.drain_invalidations();
        let scopes = &inv["a"]["voice"].scopes;
        assert_eq!(scopes.len(), 2);
        assert!(scopes.contains(&"stt".to_string()));
        assert!(scopes.contains(&"tts".to_string()));
    }

    #[test]
    fn duplicate_scope_not_added_twice() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "voice", Some("stt"));
        cache.invalidate_service("a", "voice", Some("stt"));
        let inv = cache.drain_invalidations();
        assert_eq!(inv["a"]["voice"].scopes.len(), 1);
        assert_eq!(inv["a"]["voice"].rev, 2);
    }

    #[test]
    fn full_invalidation_clears_scopes() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "voice", Some("stt"));
        cache.invalidate_service("a", "voice", None); // full
        let inv = cache.drain_invalidations();
        assert!(inv["a"]["voice"].scopes.is_empty());
    }

    #[test]
    fn drain_clears_pending_scopes_but_keeps_rev() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "dash", Some("pages"));
        let inv1 = cache.drain_invalidations();
        assert_eq!(inv1["a"]["dash"].rev, 1);
        assert_eq!(inv1["a"]["dash"].scopes, vec!["pages"]);

        // Second drain without new invalidations: rev preserved, scopes empty
        let inv2 = cache.drain_invalidations();
        assert_eq!(inv2["a"]["dash"].rev, 1);
        assert!(inv2["a"]["dash"].scopes.is_empty());
    }

    #[test]
    fn drain_resets_full_flag() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a", "dash", None);
        let _ = cache.drain_invalidations();

        // After drain, a scoped invalidation should produce scopes (not full)
        cache.invalidate_service("a", "dash", Some("widgets"));
        let inv = cache.drain_invalidations();
        assert_eq!(inv["a"]["dash"].scopes, vec!["widgets"]);
    }

    #[test]
    fn multiple_agents_and_services() {
        let cache = AgentStatusCache::new();
        cache.invalidate_service("a1", "voice", Some("stt"));
        cache.invalidate_service("a2", "dashboard", None);
        let inv = cache.drain_invalidations();
        assert_eq!(inv["a1"]["voice"].rev, 1);
        assert_eq!(inv["a2"]["dashboard"].rev, 1);
        assert!(inv["a2"]["dashboard"].scopes.is_empty()); // full
    }

    #[test]
    fn empty_drain_returns_empty() {
        let cache = AgentStatusCache::new();
        let inv = cache.drain_invalidations();
        assert!(inv.is_empty());
    }
}
