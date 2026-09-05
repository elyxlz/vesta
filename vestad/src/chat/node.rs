//! `ChatNode`: the one owner of chat state. Rooms and messages live in the store under one
//! mutex; the room list is a watch channel `/sync` projects, and every message and room event
//! is broadcast once for the `/rooms/ws` sessions to filter.

use std::collections::{HashMap, HashSet, VecDeque};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, PoisonError};

use tokio::sync::{broadcast, watch};

use crate::chat::store::ChatStore;
use crate::chat::{
    ChatEvent, InputMethod, Message, MessageDraft, MessageKind, Room, BURST_REFUSAL,
    CHAT_EVENT_BROADCAST_CAPACITY, ROOM_AGENT_POSTS_WITHOUT_USER, ROOM_NAME_MAX_CHARS,
    SEEN_INTENT_IDS_CAP, SPEAKING_REFUSAL, USER_SENDER,
};

const GROUP_ID_BYTES: usize = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ChatError {
    NotFound,
    Forbidden,
    Invalid(String),
    /// An agent post refused while the user talks; the text is the instruction the agent reads.
    Speaking(String),
    /// An agent post refused by the burst guard.
    Burst(String),
}

impl std::fmt::Display for ChatError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound => write!(formatter, "no such room"),
            Self::Forbidden => write!(formatter, "not a member of this room"),
            Self::Invalid(reason) | Self::Speaking(reason) | Self::Burst(reason) => {
                write!(formatter, "{reason}")
            }
        }
    }
}

impl std::error::Error for ChatError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct OpenRoom {
    pub name: Option<String>,
    pub agents: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ImportItem {
    pub origin_id: u64,
    /// Unix milliseconds; the route parses the agent's stamp before the node sees it.
    pub at_ms: u64,
    pub kind: MessageKind,
    pub text: String,
    pub input_method: Option<InputMethod>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ImportOutcome {
    pub imported: usize,
    pub skipped: usize,
}

/// Which socket connections currently report the user talking in a room, and whether an agent
/// post was refused during that turn (the turn-end event repays exactly that refusal).
#[derive(Debug, Default)]
struct Speaking {
    connections: HashSet<u64>,
    refused: bool,
}

pub(crate) struct ChatNode {
    store: Mutex<ChatStore>,
    known_agents: Mutex<HashSet<String>>,
    seen_intents: Mutex<VecDeque<String>>,
    speaking: Mutex<HashMap<String, Speaking>>,
    next_connection: AtomicU64,
    rooms_tx: watch::Sender<Vec<Room>>,
    events_tx: broadcast::Sender<Arc<ChatEvent>>,
}

impl std::fmt::Debug for ChatNode {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("ChatNode").finish_non_exhaustive()
    }
}

impl ChatNode {
    pub(crate) fn load(config_dir: &Path) -> Self {
        let store = ChatStore::load(config_dir);
        let (rooms_tx, _) = watch::channel(store.rooms());
        let (events_tx, _) = broadcast::channel(CHAT_EVENT_BROADCAST_CAPACITY);
        Self {
            store: Mutex::new(store),
            known_agents: Mutex::new(HashSet::new()),
            seen_intents: Mutex::new(VecDeque::new()),
            speaking: Mutex::new(HashMap::new()),
            next_connection: AtomicU64::new(1),
            rooms_tx,
            events_tx,
        }
    }

    pub(crate) fn subscribe_rooms(&self) -> watch::Receiver<Vec<Room>> {
        self.rooms_tx.subscribe()
    }

    pub(crate) fn rooms_snapshot(&self) -> Vec<Room> {
        self.rooms_tx.borrow().clone()
    }

    pub(crate) fn subscribe_events(&self) -> broadcast::Receiver<Arc<ChatEvent>> {
        self.events_tx.subscribe()
    }

    pub(crate) fn room(&self, id: &str) -> Option<Room> {
        self.store
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .room(id)
            .cloned()
    }

    /// The rooms `agent` is in, or every room for the user.
    pub(crate) fn rooms_for_agent(&self, agent: &str) -> Vec<Room> {
        self.rooms_snapshot()
            .into_iter()
            .filter(|room| room.has_agent(agent))
            .collect()
    }

    pub(crate) fn known_agents(&self) -> Vec<String> {
        let mut names: Vec<String> = self
            .known_agents
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .iter()
            .cloned()
            .collect();
        names.sort_unstable();
        names
    }

    /// Every agent vestad knows gets its direct room; names are remembered for membership checks.
    /// The roster poll calls this every tick, so a name set matching the one already known is a
    /// no-op: nothing is claimed and the room list is not republished.
    pub(crate) fn reconcile_agents(&self, names: &[String], now_secs: u64) {
        {
            let mut known = self
                .known_agents
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            let incoming: HashSet<String> = names.iter().cloned().collect();
            if *known == incoming {
                return;
            }
            *known = incoming;
        }
        for name in names {
            self.ensure_direct_room(name, now_secs);
        }
    }

    pub(crate) fn ensure_direct_room(&self, agent: &str, now_secs: u64) -> Room {
        self.known_agents
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .insert(agent.to_string());
        let claim = Room {
            id: Room::direct_id(agent),
            name: None,
            agents: vec![agent.to_string()],
            created_at: now_secs,
            last_message_at: None,
        };
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        let created = store.claim_room(claim.clone());
        let room = store.room(&claim.id).cloned().unwrap_or(claim);
        self.publish_rooms(
            &store,
            created.then(|| ChatEvent::RoomCreated(room.clone())),
        );
        room
    }

    /// Create-or-get: no name and one agent is that agent's direct room, no name and two agents
    /// is their peer room, a name makes a group. Returns whether the room was created.
    pub(crate) fn open_room(
        &self,
        request: OpenRoom,
        now_secs: u64,
    ) -> Result<(Room, bool), ChatError> {
        let mut agents = request.agents;
        if agents.is_empty() {
            return Err(ChatError::Invalid("a room needs at least one agent".into()));
        }
        agents.sort_unstable();
        if agents.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(ChatError::Invalid("agents must be distinct".into()));
        }
        {
            let known = self
                .known_agents
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            if let Some(unknown) = agents.iter().find(|agent| !known.contains(*agent)) {
                return Err(ChatError::Invalid(format!("unknown agent: {unknown}")));
            }
        }
        let name = match request.name.as_deref().map(str::trim) {
            Some("") | None => None,
            Some(trimmed) if trimmed.chars().count() > ROOM_NAME_MAX_CHARS => {
                return Err(ChatError::Invalid(format!(
                    "a room name is at most {ROOM_NAME_MAX_CHARS} characters"
                )));
            }
            Some(trimmed) => Some(trimmed.to_string()),
        };
        let id = match (&name, agents.len()) {
            (None, 1) => Room::direct_id(&agents[0]),
            (None, 2) => Room::peer_id(&agents[0], &agents[1]),
            (None, _) => {
                return Err(ChatError::Invalid(
                    "a room with three or more agents needs a name".into(),
                ))
            }
            (Some(_), _) => format!(
                "grp-{}",
                hex::encode(rand::random::<[u8; GROUP_ID_BYTES]>())
            ),
        };
        let claim = Room {
            id,
            name,
            agents,
            created_at: now_secs,
            last_message_at: None,
        };
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        let created = store.claim_room(claim.clone());
        let room = store.room(&claim.id).cloned().unwrap_or(claim);
        self.publish_rooms(
            &store,
            created.then(|| ChatEvent::RoomCreated(room.clone())),
        );
        Ok((room, created))
    }

    /// The user deletes a room. A direct room goes only once its agent is gone from `live_agents`.
    pub(crate) fn delete_room(&self, id: &str, live_agents: &[String]) -> Result<(), ChatError> {
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        let room = store.room(id).cloned().ok_or(ChatError::NotFound)?;
        if room.is_direct() && live_agents.iter().any(|agent| room.has_agent(agent)) {
            return Err(ChatError::Invalid(
                "a direct room lives as long as its agent".into(),
            ));
        }
        store.remove_room(id);
        self.publish_rooms(
            &store,
            Some(ChatEvent::RoomDeleted {
                room: id.to_string(),
            }),
        );
        Ok(())
    }

    /// Persist one message and fan it to the live edge.
    pub(crate) fn append(&self, draft: MessageDraft) -> Message {
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        let message = store.append(draft);
        self.publish_rooms(&store, Some(ChatEvent::Message(message.clone())));
        message
    }

    pub(crate) fn page(
        &self,
        room: &str,
        before: Option<u64>,
        limit: usize,
    ) -> (Vec<Message>, Option<u64>) {
        self.store
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .page(room, before, limit)
    }

    pub(crate) fn after(
        &self,
        room: &str,
        after: u64,
        limit: usize,
    ) -> (Vec<Message>, Option<u64>) {
        self.store
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .after(room, after, limit)
    }

    /// True when `intent_id` belongs to a message that already landed. The one dedup decision.
    pub(crate) fn intent_seen(&self, intent_id: &str) -> bool {
        let seen = self
            .seen_intents
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        seen.iter().any(|known| known == intent_id)
    }

    /// Record a landed message's `intent_id`, so its retry deduplicates. Intake calls this after
    /// the append, never before: a post refused by the gate or the guard never landed, and its
    /// retry must reach the room.
    pub(crate) fn remember_intent(&self, intent_id: &str) {
        let mut seen = self
            .seen_intents
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        seen.push_back(intent_id.to_string());
        while seen.len() > SEEN_INTENT_IDS_CAP {
            seen.pop_front();
        }
    }

    /// The burst guard: agent posts stop once the room's tail holds the cap of agent messages
    /// since the user last spoke.
    pub(crate) fn check_burst(&self, room: &str) -> Result<(), ChatError> {
        let tail = self
            .store
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .agent_messages_since_user(room);
        if tail >= ROOM_AGENT_POSTS_WITHOUT_USER {
            return Err(ChatError::Burst(BURST_REFUSAL.into()));
        }
        Ok(())
    }

    /// The speaking gate: an agent post is refused while any connection reports the user talking
    /// in `room`, and the refusal is remembered for the turn-end event.
    pub(crate) fn check_speaking(&self, room: &str) -> Result<(), ChatError> {
        let mut speaking = self.speaking.lock().unwrap_or_else(PoisonError::into_inner);
        match speaking.get_mut(room) {
            Some(state) if !state.connections.is_empty() => {
                state.refused = true;
                Err(ChatError::Speaking(SPEAKING_REFUSAL.into()))
            }
            _ => Ok(()),
        }
    }

    pub(crate) fn new_connection(&self) -> u64 {
        self.next_connection.fetch_add(1, Ordering::Relaxed)
    }

    /// A connection's speaking report for one room. The floor clearing after a refusal emits the
    /// turn-end event into the room.
    pub(crate) fn set_speaking(&self, connection: u64, room: &str, active: bool) {
        let emit = {
            let mut speaking = self.speaking.lock().unwrap_or_else(PoisonError::into_inner);
            let state = speaking.entry(room.to_string()).or_default();
            if active {
                state.connections.insert(connection);
                false
            } else {
                state.connections.remove(&connection);
                let clear = state.connections.is_empty() && state.refused;
                if clear {
                    state.refused = false;
                }
                clear
            }
        };
        if emit {
            let _ = self
                .events_tx
                .send(Arc::new(ChatEvent::UserFinishedTalking {
                    room: room.to_string(),
                }));
        }
    }

    /// A connection closed: clear its speaking report in every room.
    pub(crate) fn drop_connection(&self, connection: u64) {
        let rooms: Vec<String> = {
            let speaking = self.speaking.lock().unwrap_or_else(PoisonError::into_inner);
            speaking
                .iter()
                .filter(|(_, state)| state.connections.contains(&connection))
                .map(|(room, _)| room.clone())
                .collect()
        };
        for room in rooms {
            self.set_speaking(connection, &room, false);
        }
    }

    /// Import an agent's history into its direct room: fresh ids, original stamps, and every
    /// origin id already present is skipped. Nothing fans to the live edge; clients reseed.
    pub(crate) fn import(&self, room: &str, items: Vec<ImportItem>) -> ImportOutcome {
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(target) = store.room(room).cloned() else {
            return ImportOutcome {
                imported: 0,
                skipped: items.len(),
            };
        };
        let agent = target.agents.first().cloned().unwrap_or_default();
        let mut known = store.origin_ids(room);
        let mut outcome = ImportOutcome {
            imported: 0,
            skipped: 0,
        };
        for item in items {
            if !known.insert(item.origin_id) {
                outcome.skipped += 1;
                continue;
            }
            let sender = match item.kind {
                MessageKind::User => USER_SENDER.to_string(),
                MessageKind::Chat => agent.clone(),
            };
            store.append(MessageDraft {
                room: room.to_string(),
                kind: item.kind,
                sender,
                text: item.text,
                input_method: item.input_method,
                intent_id: None,
                origin_id: Some(item.origin_id),
                at_ms: item.at_ms,
            });
            outcome.imported += 1;
        }
        self.publish_rooms(&store, None);
        outcome
    }

    pub(crate) fn rename_agent(&self, old: &str, new: &str) {
        {
            let mut known = self
                .known_agents
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            if known.remove(old) {
                known.insert(new.to_string());
            }
        }
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        store.rename_agent(old, new);
        self.publish_rooms(&store, None);
    }

    /// A deleted agent leaves every member set; its rooms and messages stay readable.
    pub(crate) fn forget_agent(&self, name: &str) {
        self.known_agents
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .remove(name);
        let mut store = self.store.lock().unwrap_or_else(PoisonError::into_inner);
        for mut room in store.rooms() {
            if room.has_agent(name) {
                room.agents.retain(|member| member != name);
                store.put_room(room);
            }
        }
        self.publish_rooms(&store, None);
    }

    /// Republish the room list when it changed, then fan an optional event.
    fn publish_rooms(&self, store: &ChatStore, event: Option<ChatEvent>) {
        let rooms = store.rooms();
        self.rooms_tx.send_if_modified(|current| {
            if *current == rooms {
                false
            } else {
                *current = rooms;
                true
            }
        });
        if let Some(event) = event {
            let _ = self.events_tx.send(Arc::new(event));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chat::MessageKind;

    fn node() -> (tempfile::TempDir, ChatNode) {
        let tmp = tempfile::tempdir().expect("tempdir");
        let node = ChatNode::load(tmp.path());
        (tmp, node)
    }

    fn draft(room: &str, kind: MessageKind, sender: &str, text: &str) -> MessageDraft {
        MessageDraft {
            room: room.into(),
            kind,
            sender: sender.into(),
            text: text.into(),
            input_method: None,
            intent_id: None,
            origin_id: None,
            at_ms: 1_000,
        }
    }

    #[test]
    fn ensure_direct_room_is_idempotent_and_publishes_the_room_list_once() {
        let (_tmp, node) = node();
        let mut rooms_rx = node.subscribe_rooms();
        let first = node.ensure_direct_room("alice", 5);
        let second = node.ensure_direct_room("alice", 9);
        assert_eq!(first, second);
        assert_eq!(first.id, "dm:alice");
        assert_eq!(first.created_at, 5);
        assert!(rooms_rx.has_changed().expect("watch alive"));
        assert_eq!(rooms_rx.borrow_and_update().len(), 1);
        assert!(!rooms_rx.has_changed().expect("watch alive"));
    }

    // The lookup `/sync` presence rides on: a viewed room id names the agents to notify, and an id
    // naming no room names nobody.
    #[test]
    fn a_room_id_resolves_to_its_agents_and_an_unknown_id_to_nothing() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into(), "bob".into()], 1);
        let (group, _) = node
            .open_room(
                OpenRoom {
                    name: Some("trip".into()),
                    agents: vec!["alice".into(), "bob".into()],
                },
                2,
            )
            .expect("open the group room");
        assert_eq!(
            node.room(&group.id).expect("the group room").agents,
            vec!["alice", "bob"]
        );
        assert_eq!(
            node.room("dm:alice").expect("the direct room").agents,
            vec!["alice"]
        );
        assert_eq!(node.room("dm:nobody"), None);
    }

    #[test]
    fn open_room_derives_peer_and_direct_ids_and_needs_a_name_past_two_agents() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into(), "bob".into(), "cy".into()], 1);
        let (peer, created) = node
            .open_room(
                OpenRoom {
                    name: None,
                    agents: vec!["bob".into(), "alice".into()],
                },
                2,
            )
            .expect("peer");
        assert!(created);
        assert_eq!(peer.id, "dm:alice:bob");
        assert_eq!(peer.agents, vec!["alice".to_string(), "bob".to_string()]);
        let (again, created) = node
            .open_room(
                OpenRoom {
                    name: None,
                    agents: vec!["alice".into(), "bob".into()],
                },
                3,
            )
            .expect("peer again");
        assert!(!created);
        assert_eq!(again, peer);
        let (direct, created) = node
            .open_room(
                OpenRoom {
                    name: None,
                    agents: vec!["cy".into()],
                },
                4,
            )
            .expect("direct");
        assert!(!created);
        assert_eq!(direct.id, "dm:cy");
        let error = node
            .open_room(
                OpenRoom {
                    name: None,
                    agents: vec!["alice".into(), "bob".into(), "cy".into()],
                },
                5,
            )
            .expect_err("needs a name");
        assert_eq!(
            error.to_string(),
            "a room with three or more agents needs a name"
        );
        let (group, created) = node
            .open_room(
                OpenRoom {
                    name: Some("  trip planning ".into()),
                    agents: vec!["alice".into(), "cy".into()],
                },
                6,
            )
            .expect("group");
        assert!(created);
        assert!(group.id.starts_with("grp-"));
        assert_eq!(group.id.len(), 20);
        assert_eq!(group.name.as_deref(), Some("trip planning"));
    }

    #[test]
    fn open_room_rejects_unknown_duplicate_and_empty_agents_and_long_names() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into()], 1);
        let unknown = node
            .open_room(
                OpenRoom {
                    name: None,
                    agents: vec!["nobody".into()],
                },
                1,
            )
            .expect_err("unknown");
        assert_eq!(unknown.to_string(), "unknown agent: nobody");
        let duplicate = node
            .open_room(
                OpenRoom {
                    name: Some("x".into()),
                    agents: vec!["alice".into(), "alice".into()],
                },
                1,
            )
            .expect_err("duplicate");
        assert_eq!(duplicate.to_string(), "agents must be distinct");
        let empty = node
            .open_room(
                OpenRoom {
                    name: Some("x".into()),
                    agents: vec![],
                },
                1,
            )
            .expect_err("empty");
        assert_eq!(empty.to_string(), "a room needs at least one agent");
        let long = node
            .open_room(
                OpenRoom {
                    name: Some("n".repeat(81)),
                    agents: vec!["alice".into()],
                },
                1,
            )
            .expect_err("long");
        assert_eq!(long.to_string(), "a room name is at most 80 characters");
    }

    #[test]
    fn delete_refuses_a_direct_room_while_its_agent_lives_and_fans_the_event() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into()], 1);
        let mut events = node.subscribe_events();
        let live = vec!["alice".to_string()];
        let refused = node.delete_room("dm:alice", &live).expect_err("alive");
        assert_eq!(
            refused.to_string(),
            "a direct room lives as long as its agent"
        );
        node.delete_room("dm:alice", &[]).expect("agent gone");
        assert!(node.room("dm:alice").is_none());
        let event = events.try_recv().expect("event");
        assert_eq!(
            *event,
            ChatEvent::RoomDeleted {
                room: "dm:alice".into()
            }
        );
        assert!(matches!(
            node.delete_room("dm:alice", &[]),
            Err(ChatError::NotFound)
        ));
    }

    #[test]
    fn append_fans_the_message_and_bumps_last_message_at() {
        let (_tmp, node) = node();
        node.ensure_direct_room("alice", 1);
        let mut events = node.subscribe_events();
        let message = node.append(draft("dm:alice", MessageKind::User, "user", "hello"));
        assert_eq!(message.id, 1);
        assert_eq!(
            *events.try_recv().expect("event"),
            ChatEvent::Message(message)
        );
        assert_eq!(
            node.room("dm:alice").expect("room").last_message_at,
            Some(1)
        );
    }

    #[test]
    fn import_skips_known_origin_ids_and_keeps_original_stamps() {
        let (_tmp, node) = node();
        node.ensure_direct_room("alice", 1);
        let items = vec![
            ImportItem {
                origin_id: 7,
                at_ms: 1_788_516_723_123,
                kind: MessageKind::User,
                text: "old".into(),
                input_method: None,
            },
            ImportItem {
                origin_id: 8,
                at_ms: 1_788_516_724_000,
                kind: MessageKind::Chat,
                text: "reply".into(),
                input_method: None,
            },
        ];
        let first = node.import("dm:alice", items.clone());
        assert_eq!(
            first,
            ImportOutcome {
                imported: 2,
                skipped: 0
            }
        );
        let second = node.import("dm:alice", items.clone());
        assert_eq!(
            second,
            ImportOutcome {
                imported: 0,
                skipped: 2
            }
        );
        let (page, _) = node.page("dm:alice", None, 10);
        assert_eq!(page[0].ts, "2026-09-04T10:12:03.123Z");
        assert_eq!(page[0].origin_id, Some(7));
        assert_eq!(page[1].sender, "alice");
        assert_eq!(page[0].sender, "user");
        let mut twice = items;
        twice.truncate(1);
        let repeated = ImportItem {
            origin_id: 9,
            ..twice[0].clone()
        };
        let batch = node.import("dm:alice", vec![repeated.clone(), repeated]);
        assert_eq!(
            batch,
            ImportOutcome {
                imported: 1,
                skipped: 1
            },
            "an origin id repeated inside one batch imports once"
        );
    }

    #[test]
    fn an_intent_is_deduped_only_once_recorded() {
        let (_tmp, node) = node();
        assert!(!node.intent_seen("c-1"));
        node.remember_intent("c-1");
        assert!(node.intent_seen("c-1"));
        for index in 0..SEEN_INTENT_IDS_CAP {
            node.remember_intent(&format!("id-{index}"));
        }
        assert!(!node.intent_seen("c-1"));
        assert!(node.intent_seen(&format!("id-{}", SEEN_INTENT_IDS_CAP - 1)));
    }

    #[test]
    fn forget_then_ensure_restores_the_direct_rooms_membership() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into()], 1);
        node.forget_agent("alice");
        let restored = node.ensure_direct_room("alice", 9);
        assert_eq!(restored.agents, vec!["alice".to_string()]);
        assert_eq!(restored.created_at, 1, "the room is claimed, not recreated");
    }

    #[test]
    fn forget_then_open_peer_restores_membership() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into(), "bob".into()], 1);
        node.open_room(
            OpenRoom {
                name: None,
                agents: vec!["alice".into(), "bob".into()],
            },
            2,
        )
        .expect("peer");
        node.forget_agent("alice");
        node.reconcile_agents(&["alice".into(), "bob".into()], 3);
        let (peer, created) = node
            .open_room(
                OpenRoom {
                    name: None,
                    agents: vec!["alice".into(), "bob".into()],
                },
                4,
            )
            .expect("peer again");
        assert!(!created, "the peer id is claimed, not recreated");
        assert_eq!(peer.agents, vec!["alice".to_string(), "bob".to_string()]);
    }

    #[test]
    fn reconciling_the_same_names_publishes_nothing() {
        let (_tmp, node) = node();
        let mut rooms_rx = node.subscribe_rooms();
        node.reconcile_agents(&["alice".into(), "bob".into()], 1);
        assert!(rooms_rx.has_changed().expect("watch alive"));
        assert_eq!(rooms_rx.borrow_and_update().len(), 2);
        node.reconcile_agents(&["alice".into(), "bob".into()], 2);
        assert!(
            !rooms_rx.has_changed().expect("watch alive"),
            "an unchanged roster is a no-op"
        );
    }

    #[test]
    fn forget_agent_drops_it_from_member_sets_and_keeps_the_rooms() {
        let (_tmp, node) = node();
        node.reconcile_agents(&["alice".into(), "bob".into()], 1);
        node.open_room(
            OpenRoom {
                name: None,
                agents: vec!["alice".into(), "bob".into()],
            },
            2,
        )
        .expect("peer");
        node.forget_agent("alice");
        let peer = node.room("dm:alice:bob").expect("peer stays");
        assert_eq!(peer.agents, vec!["bob".to_string()]);
        let direct = node.room("dm:alice").expect("direct stays");
        assert!(direct.agents.is_empty());
    }
}
