use std::path::PathBuf;
use std::sync::OnceLock;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tokio_util::sync::CancellationToken;

use crate::error::{ErrorCode, VestaError};

const DEFAULT_TIMEOUT_SECS: u64 = 120;
const SETUP_TIMEOUT_SECS: u64 = 600;
const AUTH_TIMEOUT_SECS: u64 = 600;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

fn is_valid_binary(path: &std::path::Path) -> bool {
    path.exists() && std::fs::metadata(path).map(|m| m.len() > 0).unwrap_or(false)
}

static CLI_PATH: OnceLock<PathBuf> = OnceLock::new();

fn cli_path() -> &'static PathBuf {
    CLI_PATH.get_or_init(|| {
        let exe = std::env::current_exe().expect("cannot determine executable path");
        let dir = exe.parent().unwrap();

        #[cfg(target_os = "windows")]
        let name = "vesta.exe";
        #[cfg(not(target_os = "windows"))]
        let name = "vesta";

        let cli_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("cli")
            .join("target");

        if cfg!(debug_assertions) {
            let debug = cli_dir.join("debug").join(name);
            if is_valid_binary(&debug) {
                return debug;
            }
        }

        let candidate = dir.join(name);
        if is_valid_binary(&candidate) {
            return candidate;
        }

        let release = cli_dir.join("release").join(name);
        if is_valid_binary(&release) {
            return release;
        }

        candidate
    })
}

fn cli_command(args: &[&str]) -> Command {
    let path = cli_path();
    eprintln!("[vesta] exec: {} {}", path.display(), args.join(" "));
    let mut cmd = Command::new(path.as_os_str());
    cmd.args(args);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            match chars.peek() {
                // CSI: \x1b[...letter
                Some('[') => {
                    chars.next();
                    for c in chars.by_ref() {
                        if c.is_ascii_alphabetic() {
                            break;
                        }
                    }
                }
                // OSC: \x1b]...(\x07 | \x1b\\)
                Some(']') => {
                    chars.next();
                    while let Some(c) = chars.next() {
                        if c == '\x07' {
                            break;
                        }
                        if c == '\x1b' && chars.peek() == Some(&'\\') {
                            chars.next();
                            break;
                        }
                    }
                }
                // Charset designator: \x1b(X
                Some('(') => {
                    chars.next();
                    chars.next();
                }
                // Other two-byte escape
                Some(_) => {
                    chars.next();
                }
                None => {}
            }
        } else {
            out.push(c);
        }
    }
    out
}

fn collect_lines(
    reader: impl tokio::io::AsyncRead + Unpin + Send + 'static,
    on_line: impl Fn(&str) + Send + 'static,
) -> tokio::task::JoinHandle<String> {
    tokio::spawn(async move {
        let mut lines = BufReader::new(reader).lines();
        let mut buf = String::new();
        while let Ok(Some(raw_line)) = lines.next_line().await {
            let line = strip_ansi(&raw_line);
            eprintln!("[vesta] {}", line);
            on_line(&line);
            if !buf.is_empty() {
                buf.push('\n');
            }
            buf.push_str(&line);
        }
        buf
    })
}

fn extract_error(stderr: &str) -> String {
    let last_error = stderr
        .lines()
        .rev()
        .find(|l| l.trim().starts_with("error: "))
        .map(|l| l.trim().strip_prefix("error: ").unwrap().to_string());

    if let Some(msg) = last_error {
        return msg;
    }

    let last_line = stderr
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .map(|l| l.trim().to_string());

    last_line.unwrap_or_else(|| "command failed with no output".to_string())
}

async fn run_with_timeout(args: &[&str], timeout_secs: u64) -> Result<String, VestaError> {
    let mut cmd = cli_command(args);
    cmd.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    let mut child = cmd.spawn()
        .map_err(|e| {
            eprintln!("[vesta] spawn failed: {}", e);
            VestaError::new(ErrorCode::ExecFailed, format!("failed to run cli: {}", e))
        })?;

    let stdout_task = collect_lines(child.stdout.take().unwrap(), |_| {});
    let stderr_task = collect_lines(child.stderr.take().unwrap(), |_| {});

    let timeout = tokio::time::Duration::from_secs(timeout_secs);
    let status = match tokio::time::timeout(timeout, child.wait()).await {
        Ok(result) => result.map_err(|e| {
            VestaError::new(ErrorCode::Internal, format!("failed to run cli: {}", e))
        })?,
        Err(_) => {
            let _ = child.kill().await;
            let label = args.first().unwrap_or(&"cli");
            return Err(VestaError::new(
                ErrorCode::Timeout,
                format!("{} timed out after {}s", label, timeout_secs),
            ));
        }
    };

    let stdout_str = stdout_task.await.unwrap_or_default();
    let stderr_str = stderr_task.await.unwrap_or_default();

    if !status.success() {
        return Err(VestaError::new(ErrorCode::Internal, extract_error(&stderr_str)));
    }

    eprintln!("[vesta] ok: {}", args.join(" "));
    Ok(stdout_str)
}

async fn run(args: &[&str]) -> Result<String, VestaError> {
    run_with_timeout(args, DEFAULT_TIMEOUT_SECS).await
}

async fn run_json<T: serde::de::DeserializeOwned>(args: &[&str]) -> Result<T, VestaError> {
    run_json_with_timeout(args, DEFAULT_TIMEOUT_SECS).await
}

async fn run_json_with_timeout<T: serde::de::DeserializeOwned>(args: &[&str], timeout_secs: u64) -> Result<T, VestaError> {
    let stdout = run_with_timeout(args, timeout_secs).await?;
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        return Err(VestaError::new(ErrorCode::Internal, "cli returned no output"));
    }
    serde_json::from_str(trimmed)
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to parse cli output: {} (got: {:?})", e, trimmed)))
}

// ── Platform operations ─────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PlatformStatus {
    pub ready: bool,
    pub platform: String,
    #[serde(default)]
    pub wsl_installed: bool,
    #[serde(default)]
    pub virtualization_enabled: Option<bool>,
    #[serde(default)]
    pub distro_registered: bool,
    #[serde(default)]
    pub distro_healthy: bool,
    #[serde(default)]
    pub services_ready: bool,
    #[serde(default)]
    pub needs_reboot: bool,
    #[serde(default)]
    pub message: String,
}

pub async fn platform_check() -> Result<PlatformStatus, VestaError> {
    run_json(&["platform-check"]).await
}

pub async fn platform_setup() -> Result<PlatformStatus, VestaError> {
    run_json_with_timeout(&["platform-setup"], SETUP_TIMEOUT_SECS).await
}

// ── Agent operations ────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AgentInfo {
    pub status: AgentStatus,
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub authenticated: bool,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub agent_ready: bool,
    #[serde(default = "default_ws_port")]
    pub ws_port: u16,
}

fn default_ws_port() -> u16 { 7865 }

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum AgentStatus {
    Running,
    Stopped,
    Dead,
    NotFound,
    Unknown,
}

pub async fn agent_status() -> Result<AgentInfo, VestaError> {
    run_json(&["status", "--json"]).await
}

pub async fn create_agent(name: Option<String>) -> Result<(), VestaError> {
    let mut args = vec!["create"];
    let name_val;
    if let Some(ref n) = name {
        name_val = n.clone();
        args.push("--name");
        args.push(&name_val);
    }
    run_with_timeout(&args, SETUP_TIMEOUT_SECS).await?;
    Ok(())
}

pub async fn start_agent() -> Result<(), VestaError> {
    run(&["start"]).await?;
    Ok(())
}

pub async fn stop_agent() -> Result<(), VestaError> {
    run(&["stop"]).await?;
    Ok(())
}

pub async fn restart_agent() -> Result<(), VestaError> {
    run(&["restart"]).await?;
    Ok(())
}

pub async fn delete_agent() -> Result<(), VestaError> {
    run(&["destroy", "--yes"]).await?;
    Ok(())
}

pub async fn set_agent_name(name: &str) -> Result<(), VestaError> {
    run(&["name", name]).await?;
    Ok(())
}

// ── Backup/restore operations ───────────────────────────────────

pub async fn backup_agent(path: &str) -> Result<String, VestaError> {
    run_with_timeout(&["backup", path], SETUP_TIMEOUT_SECS).await
}

pub async fn restore_agent(path: &str) -> Result<String, VestaError> {
    run_with_timeout(&["restore", path], SETUP_TIMEOUT_SECS).await
}

// ── Auth operations ────────────────────────────────────────────

pub async fn obtain_and_inject_credentials() -> Result<(), VestaError> {
    // The CLI handles browser opening for the auth URL.
    // We just need to wait for it to finish and capture stderr for errors.
    let mut cmd = cli_command(&["auth"]);
    cmd.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| {
        VestaError::new(ErrorCode::ExecFailed, format!("failed to run cli: {}", e))
    })?;

    let stdout_task = collect_lines(child.stdout.take().unwrap(), |_| {});
    let stderr_task = collect_lines(child.stderr.take().unwrap(), |_| {});

    let timeout = tokio::time::Duration::from_secs(AUTH_TIMEOUT_SECS);
    let status = match tokio::time::timeout(timeout, child.wait()).await {
        Ok(result) => result.map_err(|e| {
            VestaError::new(ErrorCode::Internal, format!("failed to run cli: {}", e))
        })?,
        Err(_) => {
            let _ = child.kill().await;
            return Err(VestaError::new(
                ErrorCode::Timeout,
                "authentication timed out after 10 minutes",
            ));
        }
    };

    let _ = stdout_task.await;
    let stderr_str = stderr_task.await.unwrap_or_default();

    if !status.success() {
        return Err(VestaError::new(ErrorCode::Internal, extract_error(&stderr_str)));
    }

    Ok(())
}

// ── Agent host ──────────────────────────────────────────────────

pub async fn agent_host() -> String {
    #[cfg(target_os = "macos")]
    {
        let path = dirs::data_dir()
            .unwrap_or_default()
            .join("vesta")
            .join("vm_ip");
        if let Ok(content) = tokio::fs::read_to_string(&path).await {
            let ip = content.trim().to_string();
            if !ip.is_empty() {
                return ip;
            }
        }
    }
    "localhost".to_string()
}

// ── Streaming operations ────────────────────────────────────────

use tauri::ipc::Channel;

#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "kind")]
pub enum LogEvent {
    Line { text: String },
    End,
    Error { message: String },
}

pub async fn stream_agent_logs(
    channel: Channel<LogEvent>,
    cancel: CancellationToken,
) -> Result<(), VestaError> {
    let mut cmd = cli_command(&["logs"]);
    cmd.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    let mut child = cmd.spawn()
        .map_err(|e| {
            VestaError::new(ErrorCode::ExecFailed, format!("failed to spawn cli: {}", e))
        })?;

    let stdout = match child.stdout.take() {
        Some(s) => s,
        None => {
            let _ = channel.send(LogEvent::Error { message: "no stdout".to_string() });
            return Ok(());
        }
    };

    // Log stderr for diagnostics
    if let Some(stderr) = child.stderr.take() {
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                eprintln!("[vesta:logs] {}", line);
            }
        });
    }

    let cancel_read = cancel.clone();
    let ch = channel.clone();
    tokio::spawn(async move {
        let reader = BufReader::new(stdout);
        let mut lines = reader.lines();
        loop {
            tokio::select! {
                _ = cancel_read.cancelled() => break,
                line = lines.next_line() => {
                    match line {
                        Ok(Some(text)) => {
                            let _ = ch.send(LogEvent::Line { text });
                        }
                        Ok(None) | Err(_) => break,
                    }
                }
            }
        }
        let _ = ch.send(LogEvent::End);
    });

    let cancel_wait = cancel.clone();
    let ch_timeout = channel.clone();
    tokio::spawn(async move {
        let timeout = tokio::time::Duration::from_secs(300);
        let timed_out = tokio::time::timeout(timeout, async {
            tokio::select! {
                _ = cancel_wait.cancelled() => { let _ = child.kill().await; }
                _ = child.wait() => { cancel_wait.cancel(); }
            }
        }).await.is_err();
        if timed_out {
            let _ = ch_timeout.send(LogEvent::Error { message: "stream timed out after 5 minutes".to_string() });
            let _ = child.kill().await;
        }
    });

    Ok(())
}
