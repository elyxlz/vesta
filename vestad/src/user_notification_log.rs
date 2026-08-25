//! The durable, uncapped log of user-facing notifications: every notification
//! `UserNotifier::notify` delivers is appended here, one JSON line per entry
//! (`user-notifications.jsonl` beside `settings.json`), so appends stay O(1)
//! forever. The whole log is held in memory (entries are small and a personal
//! gateway produces a handful a day), pages serve from memory newest-first,
//! and the file is only ever appended, never rewritten.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

use crate::time_utils::now_epoch_secs;

const LOG_FILE: &str = "user-notifications.jsonl";

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
    entries: Mutex<Vec<LoggedUserNotification>>,
}

impl UserNotificationLog {
    /// Load the log from disk. A missing file is an empty log; a corrupt line
    /// (a torn final write) is skipped rather than poisoning the rest.
    pub(crate) fn load(config_dir: &Path) -> Self {
        let path = config_dir.join(LOG_FILE);
        let entries = match std::fs::read_to_string(&path) {
            Ok(content) => content
                .lines()
                .filter_map(|line| serde_json::from_str::<LoggedUserNotification>(line).ok())
                .collect(),
            Err(_) => Vec::new(),
        };
        Self { path, entries: Mutex::new(entries) }
    }

    /// Append one delivered notification, assigning the next monotonic id. The
    /// disk write is best-effort: a full disk costs history, never delivery.
    pub(crate) fn append(&self, agent: &str, kind: &str, title: &str, body: &str) {
        let mut entries = self.entries.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        Self::push_entry(&self.path, &mut entries, agent, kind, title, body);
    }

    /// Append unless an entry with this kind and title is already logged, the check and the
    /// append under one lock: the log itself is the durable memory of "already delivered", so
    /// a producer that must notify once ever cannot repeat itself across restarts or races.
    pub(crate) fn append_once(&self, agent: &str, kind: &str, title: &str, body: &str) -> bool {
        let mut entries = self.entries.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if entries.iter().any(|entry| entry.kind == kind && entry.title == title) {
            return false;
        }
        Self::push_entry(&self.path, &mut entries, agent, kind, title, body);
        true
    }

    fn push_entry(
        path: &Path,
        entries: &mut Vec<LoggedUserNotification>,
        agent: &str,
        kind: &str,
        title: &str,
        body: &str,
    ) {
        let entry = LoggedUserNotification {
            id: entries.last().map_or(1, |last| last.id + 1),
            at: now_epoch_secs(),
            agent: agent.to_string(),
            kind: kind.to_string(),
            title: title.to_string(),
            body: body.to_string(),
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
        entries.push(entry);
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
        log.append("aria", "message", "aria", "hi");
        log.append("aria", "task", "aria added a task: x", "");
        log.append("", "gateway_updated", "gateway updated to v0.2.10", "");

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
            log.append("aria", "message", "aria", "hi");
            log.append("aria", "message", "aria", "again");
        }
        let reloaded = UserNotificationLog::load(directory.path());
        reloaded.append("aria", "message", "aria", "after restart");
        let ids: Vec<u64> = reloaded.page(None, 10).iter().map(|entry| entry.id).collect();
        assert_eq!(ids, vec![3, 2, 1]);
    }

    #[test]
    fn append_once_dedups_by_kind_and_title_across_restarts() {
        let directory = tempfile::tempdir().expect("tempdir");
        {
            let log = UserNotificationLog::load(directory.path());
            assert!(log.append_once("", "update_available", "gateway v0.3.0 available", ""));
            assert!(!log.append_once("", "update_available", "gateway v0.3.0 available", ""));
            assert!(log.append_once("", "update_available", "gateway v0.4.0 available", ""));
        }
        let reloaded = UserNotificationLog::load(directory.path());
        assert!(!reloaded.append_once("", "update_available", "gateway v0.3.0 available", ""));
        assert_eq!(reloaded.page(None, 10).len(), 2);
    }

    #[test]
    fn a_torn_final_line_is_skipped_not_fatal() {
        let directory = tempfile::tempdir().expect("tempdir");
        {
            let log = UserNotificationLog::load(directory.path());
            log.append("aria", "message", "aria", "hi");
        }
        let path = directory.path().join(LOG_FILE);
        let mut content = std::fs::read_to_string(&path).expect("log file");
        content.push_str("{\"id\":2,\"at\":");
        std::fs::write(&path, content).expect("write torn line");

        let reloaded = UserNotificationLog::load(directory.path());
        assert_eq!(reloaded.page(None, 10).len(), 1);
    }
}
