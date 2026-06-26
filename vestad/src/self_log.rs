//! vestad's own log file: where vestad writes its logs, and how the gateway logs
//! viewer reads them back. vestad always writes to a rolling file under the config
//! dir (see `init_tracing` in main.rs), so the viewer can tail that file identically
//! whether vestad runs under systemd, `cargo run`, or anything else — unlike
//! journalctl, which only has entries when vestad is a systemd unit.

use std::path::{Path, PathBuf};
use std::process::Stdio;

const LOG_FILENAME_PREFIX: &str = "vestad.log";
const MAX_LOG_FILES: usize = 7;

/// A daily-rotating, self-pruning file appender for vestad's own logs, writing
/// `vestad.log.<date>` under `dir`. Retains [`MAX_LOG_FILES`] days so the logs stay
/// bounded without external rotation.
pub fn build_appender(dir: &Path) -> Result<tracing_appender::rolling::RollingFileAppender, String> {
    tracing_appender::rolling::Builder::new()
        .rotation(tracing_appender::rolling::Rotation::DAILY)
        .filename_prefix(LOG_FILENAME_PREFIX)
        .max_log_files(MAX_LOG_FILES)
        .build(dir)
        .map_err(|e| format!("failed to build log appender: {}", e))
}

/// Newest log file in the log directory (rotation writes one dated file per day),
/// or `None` when nothing has been written yet. Dated filenames sort lexically by
/// date, so the lexical max is the newest.
pub fn latest_log_file(dir: &Path) -> Option<PathBuf> {
    let entries = std::fs::read_dir(dir).ok()?;
    entries
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with(LOG_FILENAME_PREFIX))
        })
        .max()
}

/// `tail -n <lines> [-f] <path>` — the argv used to stream vestad's own log.
fn log_tail_argv(path: &Path, lines: usize, follow: bool) -> Vec<String> {
    let mut argv = vec!["tail".to_string(), "-n".to_string(), lines.to_string()];
    if follow {
        argv.push("-f".to_string());
    }
    argv.push(path.to_string_lossy().into_owned());
    argv
}

/// Spawn a `tail` over vestad's own log file, piping its stdout for the SSE reader.
pub fn spawn_log_tail(path: &Path, lines: usize, follow: bool) -> Result<tokio::process::Child, String> {
    let argv = log_tail_argv(path, lines, follow);
    let (program, args) = argv.split_first().expect("log_tail_argv is never empty");
    tokio::process::Command::new(program)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("failed to spawn log tail: {}", e))
}

#[cfg(test)]
mod tests {
    use super::{latest_log_file, log_tail_argv, spawn_log_tail, LOG_FILENAME_PREFIX};

    #[test]
    fn tail_argv_follows_and_targets_the_path() {
        let argv = log_tail_argv(std::path::Path::new("/var/x.log"), 500, true);
        assert_eq!(argv, vec!["tail", "-n", "500", "-f", "/var/x.log"]);
    }

    #[test]
    fn tail_argv_omits_follow_when_not_following() {
        let argv = log_tail_argv(std::path::Path::new("/var/x.log"), 100, false);
        assert_eq!(argv, vec!["tail", "-n", "100", "/var/x.log"]);
    }

    #[tokio::test]
    async fn tails_a_plain_file_without_systemd() {
        // The whole point: given a plain file (no journald, no systemd unit), the
        // gateway log source returns its tail. This is what makes the viewer work
        // under `cargo run` as well as under systemd.
        use tokio::io::AsyncBufReadExt;
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("vestad.log.2026-06-26");
        std::fs::write(&path, "line one\nline two\nline three\n").expect("write log");

        let mut child = spawn_log_tail(&path, 2, false).expect("spawn tail");
        let stdout = child.stdout.take().expect("piped stdout");
        let mut lines = tokio::io::BufReader::new(stdout).lines();

        let mut got = Vec::new();
        while let Some(line) = lines.next_line().await.expect("read line") {
            got.push(line);
        }
        assert_eq!(got, vec!["line two".to_string(), "line three".to_string()]);
    }

    #[test]
    fn latest_log_file_picks_the_newest_dated_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let older = dir.path().join(format!("{LOG_FILENAME_PREFIX}.2026-06-25"));
        let newer = dir.path().join(format!("{LOG_FILENAME_PREFIX}.2026-06-26"));
        std::fs::write(&older, "old\n").expect("write older");
        std::fs::write(&newer, "new\n").expect("write newer");

        assert_eq!(latest_log_file(dir.path()), Some(newer));
    }

    #[test]
    fn latest_log_file_is_none_for_empty_dir() {
        let dir = tempfile::tempdir().expect("tempdir");
        assert_eq!(latest_log_file(dir.path()), None);
    }

    #[test]
    fn appender_writes_a_file_the_reader_can_find() {
        // The write side (what vestad logs) and the read side (what the viewer tails)
        // must agree: a line written through the appender is found by latest_log_file.
        use std::io::Write;
        let dir = tempfile::tempdir().expect("tempdir");
        let mut appender = super::build_appender(dir.path()).expect("build appender");
        writeln!(appender, "hello from vestad").expect("write line");
        appender.flush().expect("flush");

        let latest = latest_log_file(dir.path()).expect("a log file exists");
        let content = std::fs::read_to_string(latest).expect("read log");
        assert!(content.contains("hello from vestad"), "content: {content}");
    }
}
