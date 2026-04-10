use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use futures_util::StreamExt;
use tokio::sync::watch;

use crate::docker::{self, ListEntry};

const POLL_INTERVAL_SECS: u64 = 3;

/// Cached agent list + activity states, updated by a background task.
/// WS handlers subscribe via the watch receivers.
pub struct AgentStatusCache {
    agents_tx: watch::Sender<Vec<ListEntry>>,
    agents_rx: watch::Receiver<Vec<ListEntry>>,
    activity_tx: watch::Sender<HashMap<String, String>>,
    activity_rx: watch::Receiver<HashMap<String, String>>,
}

impl AgentStatusCache {
    pub fn new() -> Self {
        let (agents_tx, agents_rx) = watch::channel(Vec::new());
        let (activity_tx, activity_rx) = watch::channel(HashMap::new());
        Self {
            agents_tx,
            agents_rx,
            activity_tx,
            activity_rx,
        }
    }

    pub fn subscribe_agents(&self) -> watch::Receiver<Vec<ListEntry>> {
        self.agents_rx.clone()
    }

    pub fn subscribe_activity(&self) -> watch::Receiver<HashMap<String, String>> {
        self.activity_rx.clone()
    }
}

/// Spawns the background polling loop that keeps the cache fresh and manages
/// internal WebSocket connections to alive agents for activity state relay.
pub fn spawn_agent_status_task(cache: Arc<AgentStatusCache>, agents_dir: PathBuf) {
    tokio::spawn(async move {
        let mut agent_ws_handles: HashMap<String, AgentWsHandle> = HashMap::new();
        let (activity_event_tx, mut activity_event_rx) =
            tokio::sync::mpsc::channel::<(String, String)>(64);

        loop {
            // Poll agent list (blocking — hits Docker CLI)
            let dir = agents_dir.clone();
            let agents = tokio::task::spawn_blocking(move || docker::list_agents(&dir))
                .await
                .unwrap_or_default();

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
                .filter(|a| a.alive)
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

                // Connection lost — reset to idle so the frontend doesn't
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
