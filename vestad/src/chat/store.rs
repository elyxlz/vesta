//! The chat store: `rooms.json` (the room list, rewritten atomically on change) and
//! `messages.jsonl` (append-only, one message per line), both under `<config_dir>/chat/` and
//! held in memory. A rename is the one operation that rewrites the log instead of appending.

use std::collections::{BTreeMap, HashMap};
use std::io::Write;
use std::path::{Path, PathBuf};

use crate::chat::{format_ts, parse_ts, Message, MessageDraft, Room};

const CHAT_DIR: &str = "chat";
const ROOMS_FILE: &str = "rooms.json";
const MESSAGES_FILE: &str = "messages.jsonl";

#[derive(Debug, Clone)]
struct Entry {
    at_ms: u64,
    message: Message,
}

#[derive(Debug)]
pub(crate) struct ChatStore {
    dir: PathBuf,
    rooms: BTreeMap<String, Room>,
    messages: Vec<Entry>,
    next_id: u64,
    /// The log exists but could not be read, so its ids are unknown. Nothing touches the file
    /// while this holds: appending under a restarted id counter would duplicate ids.
    log_unreadable: bool,
    /// The room list exists but could not be read, so the rooms on disk are unknown. Nothing
    /// rewrites the file while this holds: saving would drop rooms this process never saw.
    rooms_unreadable: bool,
}

impl ChatStore {
    /// Load both files; a missing file is empty, a torn line is skipped, and a file that exists
    /// but cannot be read or parsed leaves that half of the store in memory only.
    pub(crate) fn load(config_dir: &Path) -> Self {
        let dir = config_dir.join(CHAT_DIR);
        let (rooms, rooms_unreadable) = Self::load_rooms(&dir.join(ROOMS_FILE));
        let log = dir.join(MESSAGES_FILE);
        let (messages, log_unreadable): (Vec<Entry>, bool) = match std::fs::read_to_string(&log) {
            Ok(content) => (
                content
                    .lines()
                    .filter_map(|line| serde_json::from_str::<Message>(line).ok())
                    .map(|message| Entry {
                        at_ms: parse_ts(&message.ts).unwrap_or(0),
                        message,
                    })
                    .collect(),
                false,
            ),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (Vec::new(), false),
            Err(error) => {
                tracing::error!(
                    path = %log.display(),
                    %error,
                    "cannot read the chat log; chat stays in memory and the file is left untouched"
                );
                (Vec::new(), true)
            }
        };
        let next_id = messages
            .iter()
            .map(|entry| entry.message.id)
            .max()
            .map_or(1, |max| max + 1);
        Self {
            dir,
            rooms,
            messages,
            next_id,
            log_unreadable,
            rooms_unreadable,
        }
    }

    /// The room list, and whether the file exists but could not be read or parsed. A missing file
    /// is an empty, writable list; anything else names itself once in the log.
    fn load_rooms(path: &Path) -> (BTreeMap<String, Room>, bool) {
        let content = match std::fs::read_to_string(path) {
            Ok(content) => content,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return (BTreeMap::new(), false)
            }
            Err(error) => {
                tracing::error!(
                    path = %path.display(),
                    %error,
                    "cannot read the room list; chat rooms stay in memory and the file is left untouched"
                );
                return (BTreeMap::new(), true);
            }
        };
        match serde_json::from_str::<Vec<Room>>(&content) {
            Ok(list) => (
                list.into_iter()
                    .map(|room| (room.id.clone(), room))
                    .collect(),
                false,
            ),
            Err(error) => {
                tracing::error!(
                    path = %path.display(),
                    %error,
                    "cannot parse the room list; chat rooms stay in memory and the file is left untouched"
                );
                (BTreeMap::new(), true)
            }
        }
    }

    /// The id the next appended message takes. Reading it back is how the tests prove a reload
    /// resumes the log's numbering.
    #[cfg(test)]
    pub(crate) fn next_id(&self) -> u64 {
        self.next_id
    }

    pub(crate) fn rooms(&self) -> Vec<Room> {
        self.rooms.values().cloned().collect()
    }

    pub(crate) fn room(&self, id: &str) -> Option<&Room> {
        self.rooms.get(id)
    }

    /// Insert or replace a room and persist the list.
    pub(crate) fn put_room(&mut self, room: Room) {
        self.rooms.insert(room.id.clone(), room);
        self.save_rooms();
    }

    /// Claim a derived id: insert the room when the id is absent, and otherwise union the members
    /// into the room already holding it, keeping its name and stamps. A `dm:` room's identity is
    /// its id, so a member set a forgotten agent left short is repaired here rather than replaced.
    /// Returns whether the room was created.
    pub(crate) fn claim_room(&mut self, room: Room) -> bool {
        let Some(existing) = self.rooms.get_mut(&room.id) else {
            self.rooms.insert(room.id.clone(), room);
            self.save_rooms();
            return true;
        };
        let mut agents: Vec<String> = existing.agents.iter().cloned().chain(room.agents).collect();
        agents.sort_unstable();
        agents.dedup();
        if agents != existing.agents {
            existing.agents = agents;
            self.save_rooms();
        }
        false
    }

    /// Drop a room and every message in it, so a deterministic id created later starts empty.
    pub(crate) fn remove_room(&mut self, id: &str) -> Option<Room> {
        let removed = self.rooms.remove(id)?;
        self.messages.retain(|entry| entry.message.room != id);
        self.save_rooms();
        self.rewrite_messages();
        Some(removed)
    }

    /// Stamp the next id, persist the line, bump the room's `last_message_at`.
    pub(crate) fn append(&mut self, draft: MessageDraft) -> Message {
        let message = Message {
            id: self.next_id,
            ts: format_ts(draft.at_ms),
            room: draft.room,
            kind: draft.kind,
            sender: draft.sender,
            text: draft.text,
            input_method: draft.input_method,
            intent_id: draft.intent_id,
            origin_id: draft.origin_id,
        };
        self.next_id += 1;
        self.append_line(&message);
        if let Some(room) = self.rooms.get_mut(&message.room) {
            let at_secs = draft.at_ms / 1000;
            if room.last_message_at.is_none_or(|last| last < at_secs) {
                room.last_message_at = Some(at_secs);
                self.save_rooms();
            }
        }
        self.messages.push(Entry {
            at_ms: draft.at_ms,
            message: message.clone(),
        });
        message
    }

    /// The origin ids already imported into `room`.
    pub(crate) fn origin_ids(&self, room: &str) -> std::collections::HashSet<u64> {
        self.messages
            .iter()
            .filter(|entry| entry.message.room == room)
            .filter_map(|entry| entry.message.origin_id)
            .collect()
    }

    /// The newest `limit` messages of `room` strictly before the position of `before` in the
    /// room's `(ts, id)` order, oldest first, with the cursor for the next older page.
    pub(crate) fn page(
        &self,
        room: &str,
        before: Option<u64>,
        limit: usize,
    ) -> (Vec<Message>, Option<u64>) {
        if limit == 0 {
            return (Vec::new(), None);
        }
        let mut ordered: Vec<&Entry> = self
            .messages
            .iter()
            .filter(|entry| entry.message.room == room)
            .collect();
        ordered.sort_by_key(|entry| (entry.at_ms, entry.message.id));
        let end = match before {
            Some(cursor) => ordered
                .iter()
                .position(|entry| entry.message.id == cursor)
                .unwrap_or(0),
            None => ordered.len(),
        };
        let start = end.saturating_sub(limit);
        let page: Vec<Message> = ordered[start..end]
            .iter()
            .map(|entry| entry.message.clone())
            .collect();
        let cursor = (start > 0)
            .then(|| page.first().map(|message| message.id))
            .flatten();
        (page, cursor)
    }

    /// Up to `limit` messages of `room` with an id above `after`, in append order, with the id to
    /// continue from when more remain. This is the replication walk.
    pub(crate) fn after(
        &self,
        room: &str,
        after: u64,
        limit: usize,
    ) -> (Vec<Message>, Option<u64>) {
        let mut matching = self
            .messages
            .iter()
            .filter(|entry| entry.message.room == room && entry.message.id > after)
            .map(|entry| entry.message.clone());
        let events: Vec<Message> = matching.by_ref().take(limit).collect();
        let cursor = if matching.next().is_some() {
            events.last().map(|message| message.id)
        } else {
            None
        };
        (events, cursor)
    }

    /// The tail of `room` in append order, newest last: the messages after the user's last one.
    /// Imported history is skipped whole, so replaying an agent's old conversation never spends
    /// the burst guard the live edge is there to bound.
    pub(crate) fn agent_messages_since_user(&self, room: &str) -> usize {
        self.messages
            .iter()
            .rev()
            .filter(|entry| entry.message.room == room && entry.message.origin_id.is_none())
            .take_while(|entry| entry.message.sender != crate::chat::USER_SENDER)
            .count()
    }

    /// Rewrite every member set, room id, and sender that names `old`, then rewrite both files.
    /// The rooms that moved make the map every message is rewritten through, so an id and the
    /// messages under it can never be derived differently.
    pub(crate) fn rename_agent(&mut self, old: &str, new: &str) {
        let mut moved: HashMap<String, String> = HashMap::new();
        let mut renamed: BTreeMap<String, Room> = BTreeMap::new();
        for mut room in std::mem::take(&mut self.rooms).into_values() {
            for member in &mut room.agents {
                if member == old {
                    *member = new.to_string();
                }
            }
            room.agents.sort_unstable();
            room.agents.dedup();
            let renamed_id = Self::renamed_room_id(&room.id, old, new);
            if renamed_id != room.id {
                moved.insert(room.id.clone(), renamed_id.clone());
            }
            room.id = renamed_id;
            match renamed.get_mut(&room.id) {
                None => {
                    renamed.insert(room.id.clone(), room);
                }
                // The rename lands on an id another room already holds (the user forgot an agent
                // and named a new one after it): both rooms' messages now live under that id, so
                // the record merges rather than one overwriting the other.
                Some(held) => {
                    held.agents.append(&mut room.agents);
                    held.agents.sort_unstable();
                    held.agents.dedup();
                    held.created_at = held.created_at.min(room.created_at);
                    held.last_message_at = held.last_message_at.max(room.last_message_at);
                }
            }
        }
        self.rooms = renamed;
        for entry in &mut self.messages {
            if entry.message.sender == old {
                entry.message.sender = new.to_string();
            }
            if let Some(renamed_id) = moved.get(&entry.message.room) {
                entry.message.room.clone_from(renamed_id);
            }
        }
        self.save_rooms();
        self.rewrite_messages();
    }

    /// The one id derivation: `dm:<old>` becomes `dm:<new>`, a peer id naming `old` is rebuilt
    /// around the other member, and every other id stays. Read from the id alone, never the
    /// member set, which a forgotten agent leaves out of step with the id.
    fn renamed_room_id(room_id: &str, old: &str, new: &str) -> String {
        if room_id == Room::direct_id(old) {
            return Room::direct_id(new);
        }
        let Some(rest) = room_id.strip_prefix("dm:") else {
            return room_id.to_string();
        };
        let members: Vec<&str> = rest.split(':').collect();
        if members.len() == 2 && members.contains(&old) {
            let other = if members[0] == old {
                members[1]
            } else {
                members[0]
            };
            return Room::peer_id(other, new);
        }
        room_id.to_string()
    }

    fn save_rooms(&self) {
        if self.rooms_unreadable {
            return;
        }
        let list: Vec<&Room> = self.rooms.values().collect();
        crate::settings::save_json_atomic(&self.dir.join(ROOMS_FILE), &list, None);
    }

    fn append_line(&self, message: &Message) {
        if self.log_unreadable {
            return;
        }
        let Ok(line) = serde_json::to_string(message) else {
            return;
        };
        if std::fs::create_dir_all(&self.dir).is_err() {
            tracing::warn!(dir = %self.dir.display(), "cannot create the chat dir; message kept in memory only");
            return;
        }
        let opened = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.dir.join(MESSAGES_FILE));
        match opened {
            Ok(mut file) => {
                if let Err(error) = writeln!(file, "{line}") {
                    tracing::warn!(%error, "cannot append to the chat log; message kept in memory only");
                }
            }
            Err(error) => {
                tracing::warn!(%error, "cannot open the chat log; message kept in memory only");
            }
        }
    }

    fn rewrite_messages(&self) {
        if self.log_unreadable {
            return;
        }
        let body: String = self
            .messages
            .iter()
            .filter_map(|entry| serde_json::to_string(&entry.message).ok())
            .map(|line| line + "\n")
            .collect();
        let path = self.dir.join(MESSAGES_FILE);
        let tmp = path.with_extension("jsonl.tmp");
        if std::fs::create_dir_all(&self.dir).is_ok()
            && std::fs::write(&tmp, body).is_ok()
            && std::fs::rename(&tmp, &path).is_ok()
        {
            return;
        }
        tracing::warn!(path = %path.display(), "cannot rewrite the chat log after a rename");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chat::{MessageDraft, MessageKind};

    fn draft(room: &str, kind: MessageKind, sender: &str, text: &str, at_ms: u64) -> MessageDraft {
        MessageDraft {
            room: room.into(),
            kind,
            sender: sender.into(),
            text: text.into(),
            input_method: None,
            intent_id: None,
            origin_id: None,
            at_ms,
        }
    }

    #[test]
    fn load_of_an_empty_dir_is_an_empty_store_that_persists_rooms_and_messages() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        assert!(store.rooms().is_empty());
        let room = Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec!["alice".into()],
            created_at: 10,
            last_message_at: None,
        };
        store.put_room(room.clone());
        let message = store.append(draft("dm:alice", MessageKind::User, "user", "hi", 1_000));
        assert_eq!(message.id, 1);
        assert_eq!(message.ts, "1970-01-01T00:00:01Z");
        let reloaded = ChatStore::load(tmp.path());
        assert_eq!(
            reloaded.rooms(),
            vec![Room {
                last_message_at: Some(1),
                ..room
            }]
        );
        assert_eq!(reloaded.page("dm:alice", None, 50).0, vec![message]);
        assert_eq!(reloaded.next_id(), 2);
    }

    #[test]
    fn page_orders_by_time_then_id_and_cursors_backwards() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        let first = store.append(draft("r", MessageKind::User, "user", "first", 3_000));
        let second = store.append(draft("r", MessageKind::Chat, "alice", "second", 4_000));
        let imported_older = store.append(draft("r", MessageKind::User, "user", "older", 1_000));
        let other_room = store.append(draft(
            "other",
            MessageKind::User,
            "user",
            "elsewhere",
            2_000,
        ));
        assert_eq!(other_room.id, 4);
        let (page, cursor) = store.page("r", None, 2);
        assert_eq!(page, vec![first.clone(), second.clone()]);
        assert_eq!(cursor, Some(first.id));
        let (older, cursor) = store.page("r", cursor, 2);
        assert_eq!(older, vec![imported_older]);
        assert_eq!(cursor, None);
    }

    #[test]
    fn after_walks_the_append_order_forwards() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        let one = store.append(draft("r", MessageKind::User, "user", "1", 1));
        let two = store.append(draft("r", MessageKind::Chat, "alice", "2", 2));
        let three = store.append(draft("r", MessageKind::Chat, "alice", "3", 3));
        let (events, cursor) = store.after("r", 0, 2);
        assert_eq!(events, vec![one, two.clone()]);
        assert_eq!(cursor, Some(two.id));
        let (events, cursor) = store.after("r", two.id, 2);
        assert_eq!(events, vec![three]);
        assert_eq!(cursor, None);
    }

    #[test]
    fn rename_rewrites_members_room_ids_and_senders_on_disk() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        store.put_room(Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec!["alice".into()],
            created_at: 1,
            last_message_at: None,
        });
        store.put_room(Room {
            id: "dm:alice:bob".into(),
            name: None,
            agents: vec!["alice".into(), "bob".into()],
            created_at: 1,
            last_message_at: None,
        });
        store.append(draft("dm:alice", MessageKind::Chat, "alice", "hey", 1));
        store.rename_agent("alice", "zed");
        let reloaded = ChatStore::load(tmp.path());
        let ids: Vec<String> = reloaded.rooms().into_iter().map(|room| room.id).collect();
        assert_eq!(ids, vec!["dm:bob:zed".to_string(), "dm:zed".to_string()]);
        let (page, _) = reloaded.page("dm:zed", None, 10);
        assert_eq!(page[0].sender, "zed");
        assert_eq!(page[0].room, "dm:zed");
    }

    #[test]
    fn rename_after_forget_keeps_a_peer_rooms_history_reachable() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        store.put_room(Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec!["alice".into()],
            created_at: 1,
            last_message_at: None,
        });
        store.put_room(Room {
            id: "dm:bob".into(),
            name: None,
            agents: vec!["bob".into()],
            created_at: 1,
            last_message_at: None,
        });
        store.put_room(Room {
            id: "dm:alice:bob".into(),
            name: None,
            agents: vec!["alice".into(), "bob".into()],
            created_at: 1,
            last_message_at: None,
        });
        store.append(draft(
            "dm:alice:bob",
            MessageKind::Chat,
            "alice",
            "between us",
            1_000,
        ));
        store.put_room(Room {
            id: "dm:alice:bob".into(),
            name: None,
            agents: vec!["bob".into()],
            created_at: 1,
            last_message_at: Some(1),
        });
        store.rename_agent("bob", "zed");
        let reloaded = ChatStore::load(tmp.path());
        let ids: Vec<String> = reloaded.rooms().into_iter().map(|room| room.id).collect();
        assert_eq!(
            ids,
            vec![
                "dm:alice".to_string(),
                "dm:alice:zed".to_string(),
                "dm:zed".to_string()
            ]
        );
        assert_eq!(
            reloaded.room("dm:alice:zed").expect("peer room").agents,
            vec!["zed".to_string()]
        );
        let (page, _) = reloaded.page("dm:alice:zed", None, 10);
        assert_eq!(page.len(), 1);
        assert_eq!(page[0].room, "dm:alice:zed");
        assert_eq!(page[0].sender, "alice");
    }

    #[test]
    fn an_unreadable_log_is_left_untouched() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let log = tmp.path().join("chat").join("messages.jsonl");
        std::fs::create_dir_all(&log).expect("log as a dir");
        let mut store = ChatStore::load(tmp.path());
        let message = store.append(draft("r", MessageKind::User, "user", "in memory", 1_000));
        assert_eq!(store.page("r", None, 10).0, vec![message]);
        store.rename_agent("alice", "zed");
        assert!(log.is_dir());
        assert_eq!(
            std::fs::read_dir(&log).expect("read the log dir").count(),
            0
        );
        assert!(!log.with_extension("jsonl.tmp").exists());
    }

    #[test]
    fn claim_room_unions_a_forgotten_rooms_members() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        store.put_room(Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec![],
            created_at: 1,
            last_message_at: Some(9),
        });
        let created = store.claim_room(Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec!["alice".into()],
            created_at: 5,
            last_message_at: None,
        });
        assert!(!created, "an existing id is claimed, never recreated");
        let room = store.room("dm:alice").expect("the claimed room").clone();
        assert_eq!(room.agents, vec!["alice".to_string()]);
        assert_eq!(room.created_at, 1, "the existing stamps stay");
        assert_eq!(room.last_message_at, Some(9));
        assert!(
            !store.claim_room(room.clone()),
            "a second claim changes nothing"
        );
        assert_eq!(ChatStore::load(tmp.path()).room("dm:alice"), Some(&room));
    }

    #[test]
    fn rename_onto_a_forgotten_name_keeps_the_renamed_record() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        store.put_room(Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec![],
            created_at: 7,
            last_message_at: None,
        });
        store.put_room(Room {
            id: "dm:zed".into(),
            name: None,
            agents: vec!["zed".into()],
            created_at: 9,
            last_message_at: None,
        });
        store.append(draft(
            "dm:zed",
            MessageKind::Chat,
            "zed",
            "still here",
            1_000,
        ));
        store.rename_agent("zed", "alice");
        let reloaded = ChatStore::load(tmp.path());
        let rooms = reloaded.rooms();
        assert_eq!(rooms.len(), 1, "the two ids merge into one room: {rooms:?}");
        assert_eq!(rooms[0].id, "dm:alice");
        assert_eq!(rooms[0].agents, vec!["alice".to_string()]);
        assert_eq!(rooms[0].created_at, 7, "the older stamp wins");
        let (page, _) = reloaded.page("dm:alice", None, 10);
        assert_eq!(
            page.len(),
            1,
            "the renamed room keeps its message: {page:?}"
        );
        assert_eq!(page[0].sender, "alice");
        assert_eq!(page[0].room, "dm:alice");
    }

    #[test]
    fn remove_room_drops_its_messages() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        store.put_room(Room {
            id: "r".into(),
            name: Some("room".into()),
            agents: vec!["alice".into()],
            created_at: 1,
            last_message_at: None,
        });
        store.append(draft("r", MessageKind::User, "user", "one", 1_000));
        store.append(draft("r", MessageKind::Chat, "alice", "two", 2_000));
        let kept = store.append(draft(
            "other",
            MessageKind::User,
            "user",
            "elsewhere",
            3_000,
        ));
        store.remove_room("r");
        let reloaded = ChatStore::load(tmp.path());
        assert!(
            reloaded.page("r", None, 10).0.is_empty(),
            "a removed room's messages go with it"
        );
        assert_eq!(reloaded.page("other", None, 10).0, vec![kept]);
        let log = tmp.path().join("chat").join("messages.jsonl");
        let content = std::fs::read_to_string(&log).expect("read the log");
        assert_eq!(
            content.lines().count(),
            1,
            "the log holds the one surviving message: {content}"
        );
    }

    #[test]
    fn an_unreadable_rooms_file_is_left_untouched() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let rooms = tmp.path().join("chat").join("rooms.json");
        std::fs::create_dir_all(&rooms).expect("rooms as a dir");
        let mut store = ChatStore::load(tmp.path());
        store.put_room(Room {
            id: "dm:alice".into(),
            name: None,
            agents: vec!["alice".into()],
            created_at: 1,
            last_message_at: None,
        });
        assert!(store.room("dm:alice").is_some(), "the room lives in memory");
        assert!(rooms.is_dir());
        assert_eq!(
            std::fs::read_dir(&rooms)
                .expect("read the rooms dir")
                .count(),
            0
        );
        assert!(!rooms.with_extension("json.tmp").exists());
    }

    #[test]
    fn imported_messages_never_count_against_the_burst_guard() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        let mut imported = draft("r", MessageKind::Chat, "alice", "replayed", 1_000);
        imported.origin_id = Some(1);
        store.append(imported.clone());
        imported.origin_id = Some(2);
        store.append(imported);
        assert_eq!(store.agent_messages_since_user("r"), 0);
        store.append(draft("r", MessageKind::Chat, "alice", "live reply", 2_000));
        assert_eq!(store.agent_messages_since_user("r"), 1);
    }

    #[test]
    fn a_torn_final_line_is_skipped_on_load() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut store = ChatStore::load(tmp.path());
        store.append(draft("r", MessageKind::User, "user", "kept", 1));
        let log = tmp.path().join("chat").join("messages.jsonl");
        let mut content = std::fs::read_to_string(&log).expect("read log");
        content.push_str("{\"id\":2,\"ts\":\"1970-01-01T00");
        std::fs::write(&log, content).expect("write torn log");
        let reloaded = ChatStore::load(tmp.path());
        assert_eq!(reloaded.page("r", None, 10).0.len(), 1);
        assert_eq!(reloaded.next_id(), 2);
    }
}
