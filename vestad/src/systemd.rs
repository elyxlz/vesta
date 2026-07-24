use std::io::{BufRead, IsTerminal, Write};
use std::process::{self, Command};

const SERVICE_NAME: &str = "vestad";
const SERVICE_STARTUP_WAIT_MS: u64 = 2000;
const SERVICE_POLL_INTERVAL_MS: u64 = 100;

fn unit_file_path() -> Result<String, String> {
    let home = std::env::var("HOME").map_err(|_| "HOME not set".to_string())?;
    Ok(format!("{home}/.config/systemd/user/vestad.service"))
}

pub fn ensure_service_installed() -> Result<(), String> {
    let vestad_path = std::env::current_exe()
        .map_err(|e| format!("cannot determine binary path: {e}"))?
        .to_str()
        .ok_or("binary path is not valid UTF-8")?
        .trim_end_matches(" (deleted)")
        .to_string();

    let unit_path = unit_file_path()?;

    let working_dir = if cfg!(debug_assertions) {
        std::env::current_dir()
            .ok()
            .and_then(|p| p.to_str().map(String::from))
    } else {
        None
    };

    let working_dir_line = match &working_dir {
        Some(dir) => format!("WorkingDirectory={dir}\n"),
        None => String::new(),
    };

    let unit_content = format!(
        r"[Unit]
Description=Vesta API Server
After=docker.service network-online.target
Wants=network-online.target

[Service]
ExecStart={vestad_path} serve --standalone
{working_dir_line}Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"
    );

    if let Ok(existing) = std::fs::read_to_string(&unit_path) {
        if existing == unit_content {
            return Ok(());
        }
        eprintln!("updating systemd service...");
    } else {
        eprintln!("installing systemd user service...");
    }

    if let Some(parent) = std::path::Path::new(&unit_path).parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("failed to create {}: {}", parent.display(), e))?;
    }

    std::fs::write(&unit_path, &unit_content)
        .map_err(|e| format!("failed to write systemd service: {e}"))?;

    run_systemctl(&["daemon-reload"])?;
    run_systemctl(&["enable", SERVICE_NAME])?;

    let user = std::env::var("USER").map_err(|_| "USER not set".to_string())?;
    let status = Command::new("loginctl")
        .args(["enable-linger", &user])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map_err(|e| format!("failed to run loginctl: {e}"))?;
    if !status.success() {
        eprintln!("warning: loginctl enable-linger failed, vestad may stop on logout");
    }

    Ok(())
}

pub fn is_active() -> bool {
    Command::new("systemctl")
        .args(["--user", "is-active", SERVICE_NAME])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .is_ok_and(|s| s.success())
}

pub fn start() -> Result<(), String> {
    run_systemctl(&["start", SERVICE_NAME])
}

pub fn stop() -> Result<(), String> {
    run_systemctl(&["stop", SERVICE_NAME])
}

pub fn restart() -> Result<(), String> {
    run_systemctl(&["restart", SERVICE_NAME])
}

pub fn uninstall() -> Result<(), String> {
    run_systemctl(&["disable", SERVICE_NAME]).ok();
    let unit_path = unit_file_path()?;
    std::fs::remove_file(&unit_path).ok();
    run_systemctl(&["daemon-reload"])
}

pub fn wait_for_start() -> Result<(), String> {
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_millis(SERVICE_STARTUP_WAIT_MS);

    while std::time::Instant::now() < deadline {
        if is_active() {
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_millis(SERVICE_POLL_INTERVAL_MS));
    }

    if is_active() {
        Ok(())
    } else {
        Err("vestad failed to start — run 'vestad logs' for details".into())
    }
}

pub fn print_status() {
    let _ = Command::new("systemctl")
        .args(["--user", "status", SERVICE_NAME, "--no-pager"])
        .stdin(process::Stdio::null())
        .status();
}

fn journal_args(lines: usize, follow: bool) -> Vec<String> {
    let mut args = vec![
        "--user".into(),
        "-u".into(),
        SERVICE_NAME.into(),
        // `-u` also includes systemd's own start/stop and resource-accounting
        // messages. Keep the stream focused on output from the daemon itself.
        "SYSLOG_IDENTIFIER=vestad".into(),
        "-n".into(),
        lines.to_string(),
        "--no-pager".into(),
        "--quiet".into(),
        // tracing already puts an RFC 3339 timestamp on each event. `cat` avoids
        // wrapping it in a second journald timestamp, hostname, and process id.
        "-o".into(),
        "cat".into(),
    ];
    if follow {
        args.push("-f".into());
    }
    args
}

pub fn stream_journal(lines: usize, follow: bool) -> Result<(), String> {
    let mut child = Command::new("journalctl")
        .args(journal_args(lines, follow))
        .stdout(process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to run journalctl: {e}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or("failed to read journalctl output")?;
    let color = std::io::stdout().is_terminal()
        && std::env::var_os("NO_COLOR").is_none()
        && std::env::var_os("TERM").is_none_or(|term| term != "dumb");
    let mut output = std::io::stdout().lock();

    for line in std::io::BufReader::new(stdout).lines() {
        let line = line.map_err(|e| format!("failed to read journalctl output: {e}"))?;
        if writeln!(output, "{}", format_log_line(&line, color)).is_err() {
            // A downstream command such as `head` closed the pipe. This is a
            // successful end to the stream, not an error worth printing.
            child.kill().ok();
            return Ok(());
        }
    }

    let status = child
        .wait()
        .map_err(|e| format!("failed to wait for journalctl: {e}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("journalctl exited with {status}"))
    }
}

/// Remove ANSI already embedded by an older vestad, then give tracing's stable
/// `<timestamp> <LEVEL> <message>` shape a compact, consistent terminal view.
fn format_log_line(line: &str, color: bool) -> String {
    let clean = strip_ansi(line);
    let trimmed = clean.trim_start();
    let Some(timestamp_end) = trimmed.find(char::is_whitespace) else {
        return clean;
    };
    let timestamp = &trimmed[..timestamp_end];
    let rest = trimmed[timestamp_end..].trim_start();
    let level_end = rest.find(char::is_whitespace).unwrap_or(rest.len());
    let level = &rest[..level_end];
    let message = rest[level_end..].trim_start();
    let level_color = match level {
        "TRACE" => "\x1b[2;37m",
        "DEBUG" => "\x1b[36m",
        "INFO" => "\x1b[32m",
        "WARN" => "\x1b[33m",
        "ERROR" => "\x1b[1;31m",
        _ => return clean,
    };
    let timestamp = compact_timestamp(timestamp);

    if color {
        format!("\x1b[2m{timestamp}\x1b[0m {level_color}{level:>5}\x1b[0m {message}")
    } else {
        format!("{timestamp} {level:>5} {message}")
    }
}

fn compact_timestamp(timestamp: &str) -> String {
    // tracing's default timer is UTC RFC 3339. Keep second precision: fractions
    // make a live operational stream harder to scan without adding useful context.
    if timestamp.len() >= 20
        && timestamp.as_bytes().get(10) == Some(&b'T')
        && timestamp
            .as_bytes()
            .get(19)
            .is_some_and(|c| *c == b'.' || *c == b'Z')
    {
        return format!("{} {}Z", &timestamp[..10], &timestamp[11..19]);
    }
    timestamp.to_string()
}

fn strip_ansi(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut output = String::with_capacity(input.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == 0x1b && bytes.get(index + 1) == Some(&b'[') {
            index += 2;
            while index < bytes.len() {
                let byte = bytes[index];
                index += 1;
                if (0x40..=0x7e).contains(&byte) {
                    break;
                }
            }
        } else {
            let ch = input[index..]
                .chars()
                .next()
                .expect("index remains on a UTF-8 boundary");
            output.push(ch);
            index += ch.len_utf8();
        }
    }
    output
}

pub fn main_pid() -> Option<u32> {
    let output = Command::new("systemctl")
        .args([
            "--user",
            "show",
            SERVICE_NAME,
            "--property=MainPID",
            "--value",
        ])
        .output()
        .ok()?;
    let pid_str = String::from_utf8_lossy(&output.stdout);
    let pid: u32 = pid_str.trim().parse().ok()?;
    if pid == 0 {
        None
    } else {
        Some(pid)
    }
}

fn run_systemctl(args: &[&str]) -> Result<(), String> {
    let mut full_args = vec!["--user"];
    full_args.extend_from_slice(args);

    let output = Command::new("systemctl")
        .args(&full_args)
        .stdout(process::Stdio::null())
        .output()
        .map_err(|e| format!("failed to run systemctl: {e}"))?;

    if output.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr.trim();
        if detail.is_empty() {
            Err(format!(
                "systemctl {} failed (exit {})",
                args.join(" "),
                output.status.code().unwrap_or(-1)
            ))
        } else {
            Err(format!("systemctl {} failed: {}", args.join(" "), detail))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{format_log_line, journal_args, strip_ansi, SERVICE_NAME};

    #[test]
    fn journal_args_scope_the_vestad_unit_and_forward_follow() {
        let args = journal_args(500, true);
        assert!(
            args.iter().any(|arg| arg == SERVICE_NAME),
            "must scope to the vestad unit"
        );
        assert!(
            args.iter().any(|arg| arg == "-f"),
            "follow flag must be forwarded"
        );
        assert!(args.iter().any(|arg| arg == "SYSLOG_IDENTIFIER=vestad"));
        assert!(args.windows(2).any(|pair| pair == ["-o", "cat"]));
    }

    #[test]
    fn journal_args_omit_follow_when_not_following() {
        let args = journal_args(100, false);
        assert!(
            !args.iter().any(|arg| arg == "-f"),
            "no follow flag without follow"
        );
    }

    #[test]
    fn log_lines_drop_fractional_seconds_and_align_levels() {
        let line = "2026-07-23T12:34:56.123456Z  INFO server ready port=443";
        assert_eq!(
            format_log_line(line, false),
            "2026-07-23 12:34:56Z  INFO server ready port=443"
        );
    }

    #[test]
    fn log_lines_color_levels_only_when_requested() {
        let line = "2026-07-23T12:34:56Z ERROR tunnel failed";
        let colored = format_log_line(line, true);
        assert!(colored.contains("\x1b[1;31mERROR\x1b[0m"));
        assert_eq!(strip_ansi(&colored), format_log_line(line, false));
    }

    #[test]
    fn old_ansi_and_non_tracing_lines_are_cleaned() {
        assert_eq!(
            format_log_line(
                "\x1b[2m2026-07-23T12:34:56Z\x1b[0m \x1b[33m WARN\x1b[0m retrying",
                false
            ),
            "2026-07-23 12:34:56Z  WARN retrying"
        );
        assert_eq!(
            format_log_line("\x1b[1;35mvestad\x1b[0m started", false),
            "vestad started"
        );
    }
}
