//! The durable, uncapped log of user-facing notifications: every notification
//! `UserNotifier::notify` delivers is appended here, one JSON line per entry
//! (`user-notifications.jsonl` beside `settings.json`), so appends stay O(1)
//! forever. The whole log is held in memory (entries are small and a personal
//! gateway produces a handful a day), pages serve from memory newest-first,
//! and the file is only ever appended, never rewritten.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

use crate::time_utils::now_epoch_secs;

const LOG_FILE: &str = "user-notifications.jsonl";
const SEEN_FILE: &str = "user-notifications-seen";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct LoggedUserNotification {
    pub(crate) id: u64,
    /// Unix seconds at delivery.
    pub(crate) at: u64,
    pub(crate) agent: String,
    pub(crate) kind: String,
    pub(crate) title: String,
    pub(crate) body: String,
}

#[derive(Debug)]
pub(crate) struct UserNotificationLog {
    path: PathBuf,
    seen_path: PathBuf,
    entries: Mutex<Vec<LoggedUserNotification>>,
    seen_at: AtomicU64,
}

impl UserNotificationLog {
    /// Load the log from disk. A missing file is an empty log; a corrupt line
    /// (a torn final write) is skipped rather than poisoning the rest. The seen
    /// watermark loads from its sidecar; missing or unreadable is 0 (nothing seen).
    pub(crate) fn load(config_dir: &Path) -> Self {
        let path = config_dir.join(LOG_FILE);
        let entries = match std::fs::read_to_string(&path) {
            Ok(content) => content
                .lines()
                .filter_map(|line| serde_json::from_str::<LoggedUserNotification>(line).ok())
                .collect(),
            Err(_) => Vec::new(),
        };
        let seen_path = config_dir.join(SEEN_FILE);
        let seen_at = std::fs::read_to_string(&seen_path)
            .ok()
            .and_then(|content| content.trim().parse::<u64>().ok())
            .unwrap_or(0);
        Self { path, seen_path, entries: Mutex::new(entries), seen_at: AtomicU64::new(seen_at) }
    }

    /// The feed's seen watermark: unix seconds of the user's last catch-up, 0 before the first.
    /// Everything stamped after it is unseen; the client derives that, this is only the memory.
    pub(crate) fn seen_at(&self) -> u64 {
        self.seen_at.load(Ordering::Relaxed)
    }

    /// Advance the seen watermark to now and persist it, returning the new value. The disk write
    /// is best-effort like the log's own: a failure costs the memory across a restart, never the
    /// live state.
    pub(crate) fn mark_seen_now(&self) -> u64 {
        let now = now_epoch_secs();
        self.seen_at.store(now, Ordering::Relaxed);
        if let Err(error) = std::fs::write(&self.seen_path, now.to_string()) {
            tracing::warn!(%error, "could not persist the notifications seen watermark");
        }
        now
    }

    /// The newest logged entry's delivery stamp, `None` on an empty log.
    pub(crate) fn last_at(&self) -> Option<u64> {
        let entries = self.entries.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        entries.last().map(|entry| entry.at)
    }

    /// Append one delivered notification, assigning the next monotonic id, and return the logged
    /// entry so the fanned delta carries the same identity the log serves. The disk write is
    /// best-effort: a full disk costs history, never delivery.
    pub(crate) fn append(&self, agent: &str, kind: &str, title: &str, body: String) -> LoggedUserNotification {
        let mut entries = self.entries.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        Self::push_entry(&self.path, &mut entries, agent, kind, title, body)
    }

    /// Append unless an entry with this kind and title is already logged, the check and the
    /// append under one lock: the log itself is the durable memory of "already delivered", so
    /// a producer that must notify once ever cannot repeat itself across restarts or races.
    /// Returns the new logged entry, or `None` when it was already logged.
    pub(crate) fn append_once(&self, agent: &str, kind: &str, title: &str, body: String) -> Option<LoggedUserNotification> {
        let mut entries = self.entries.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if entries.iter().any(|entry| entry.kind == kind && entry.title == title) {
            return None;
        }
        Some(Self::push_entry(&self.path, &mut entries, agent, kind, title, body))
    }

    fn push_entry(
        path: &Path,
        entries: &mut Vec<LoggedUserNotification>,
        agent: &str,
        kind: &str,
        title: &str,
        body: String,
    ) -> LoggedUserNotification {
        let entry = LoggedUserNotification {
            id: entries.last().map_or(1, |last| last.id + 1),
            at: now_epoch_secs(),
            agent: agent.to_string(),
            kind: kind.to_string(),
            title: title.to_string(),
            body,
        };
        match serde_json::to_string(&entry) {
            Ok(line) => {
                let written = std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
                    .and_then(|mut file| writeln!(file, "{line}"));
                if let Err(error) = written {
                    tracing::warn!(%error, "could not persist a user notification; kept in memory only");
                }
            }
            Err(error) => tracing::warn!(%error, "could not serialize a user notification"),
        }
        entries.push(entry.clone());
        entry
    }

    /// A newest-first page: entries with id below `before` (all when `None`),
    /// at most `limit`. The id cursor is what lets a feed walk arbitrarily far
    /// back and join the live delta edge without gaps.
    pub(crate) fn page(&self, before: Option<u64>, limit: usize) -> Vec<LoggedUserNotification> {
        let entries = self.entries.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        entries
            .iter()
            .rev()
            .filter(|entry| before.is_none_or(|cursor| entry.id < cursor))
            .take(limit)
            .cloned()
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn appends_page_newest_first_with_an_id_cursor() {
        let directory = tempfile::tempdir().expect("tempdir");
        let log = UserNotificationLog::load(directory.path());
        log.append("aria", "message", "aria", "hi".to_string());
        log.append("aria", "task", "aria added a task: x", String::new());
        log.append("", "gateway_updated", "gateway updated to v0.2.10", String::new());

        let newest = log.page(None, 2);
        assert_eq!(newest.iter().map(|entry| entry.id).collect::<Vec<_>>(), vec![3, 2]);
        let older = log.page(Some(2), 10);
        assert_eq!(older.iter().map(|entry| entry.id).collect::<Vec<_>>(), vec![1]);
    }

    #[test]
    fn survives_a_restart_and_keeps_numbering() {
        let directory = tempfile::tempdir().expect("tempdir");
        {
            let log = UserNotificationLog::load(directory.path());
            log.append("aria", "message", "aria", "hi".to_string());
            log.append("aria", "message", "aria", "again".to_string());
        }
        let reloaded = UserNotificationLog::load(directory.path());
        reloaded.append("aria", "message", "aria", "after restart".to_string());
        let ids: Vec<u64> = reloaded.page(None, 10).iter().map(|entry| entry.id).collect();
        assert_eq!(ids, vec![3, 2, 1]);
    }

    #[test]
    fn append_once_dedups_by_kind_and_title_across_restarts() {
        let directory = tempfile::tempdir().expect("tempdir");
        {
            let log = UserNotificationLog::load(directory.path());
            assert!(log.append_once("", "update_available", "gateway v0.3.0 available", String::new()).is_some());
            assert!(log.append_once("", "update_available", "gateway v0.3.0 available", String::new()).is_none());
            assert!(log.append_once("", "update_available", "gateway v0.4.0 available", String::new()).is_some());
        }
        let reloaded = UserNotificationLog::load(directory.path());
        assert!(reloaded.append_once("", "update_available", "gateway v0.3.0 available", String::new()).is_none());
        assert_eq!(reloaded.page(None, 10).len(), 2);
    }

    #[test]
    fn the_seen_watermark_starts_at_zero_and_survives_a_restart() {
        let directory = tempfile::tempdir().expect("tempdir");
        let marked = {
            let log = UserNotificationLog::load(directory.path());
            assert_eq!(log.seen_at(), 0);
            log.mark_seen_now()
        };
        let reloaded = UserNotificationLog::load(directory.path());
        assert_eq!(reloaded.seen_at(), marked);
    }

    #[test]
    fn last_at_reports_the_newest_entry_stamp() {
        let directory = tempfile::tempdir().expect("tempdir");
        let log = UserNotificationLog::load(directory.path());
        assert_eq!(log.last_at(), None);
        log.append("aria", "message", "aria", "hi".to_string());
        let newest = log.page(None, 1);
        assert_eq!(log.last_at(), Some(newest[0].at));
    }

    #[test]
    fn a_torn_final_line_is_skipped_not_fatal() {
        let directory = tempfile::tempdir().expect("tempdir");
        {
            let log = UserNotificationLog::load(directory.path());
            log.append("aria", "message", "aria", "hi".to_string());
        }
        let path = directory.path().join(LOG_FILE);
        let mut content = std::fs::read_to_string(&path).expect("log file");
        content.push_str("{\"id\":2,\"at\":");
        std::fs::write(&path, content).expect("write torn line");

        let reloaded = UserNotificationLog::load(directory.path());
        assert_eq!(reloaded.page(None, 10).len(), 1);
    }
}
