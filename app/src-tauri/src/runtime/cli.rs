use std::path::PathBuf;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tokio_util::sync::CancellationToken;

use crate::error::{ErrorCode, VestaError};

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

fn is_valid_binary(path: &std::path::Path) -> bool {
    path.exists() && std::fs::metadata(path).map(|m| m.len() > 0).unwrap_or(false)
}

fn cli_path() -> PathBuf {
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
}

fn collect_lines(reader: impl tokio::io::AsyncRead + Unpin + Send + 'static) -> tokio::task::JoinHandle<String> {
    tokio::spawn(async move {
        let mut lines = BufReader::new(reader).lines();
        let mut buf = String::new();
        while let Ok(Some(line)) = lines.next_line().await {
            eprintln!("[vesta] {}", line);
            if !buf.is_empty() {
                buf.push('\n');
            }
            buf.push_str(&line);
        }
        buf
    })
}

async fn run(args: &[&str]) -> Result<String, VestaError> {
    let path = cli_path();
    eprintln!("[vesta] exec: {} {}", path.display(), args.join(" "));

    let mut cmd = Command::new(&path);
    cmd.args(args)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn()
        .map_err(|e| {
            eprintln!("[vesta] spawn failed: {} (path: {})", e, path.display());
            VestaError::new(ErrorCode::Internal, format!("failed to run cli: {}", e))
        })?;

    let stdout_task = collect_lines(child.stdout.take().unwrap());
    let stderr_task = collect_lines(child.stderr.take().unwrap());

    let status = child.wait().await.map_err(|e| {
        VestaError::new(ErrorCode::Internal, format!("failed to run cli: {}", e))
    })?;
    let stdout_str = stdout_task.await.unwrap_or_default();
    let stderr_str = stderr_task.await.unwrap_or_default();

    if !status.success() {
        let msg = stderr_str.trim().strip_prefix("error: ").unwrap_or(stderr_str.trim());
        return Err(VestaError::new(ErrorCode::Internal, msg.to_string()));
    }

    eprintln!("[vesta] ok: {}", args.join(" "));
    Ok(stdout_str)
}

async fn run_json<T: serde::de::DeserializeOwned>(args: &[&str]) -> Result<T, VestaError> {
    let stdout = run(args).await?;
    serde_json::from_str(&stdout)
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to parse cli output: {} (got: {:?})", e, stdout)))
}

// ── Agent operations ────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AgentInfo {
    pub status: AgentStatus,
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub authenticated: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum AgentStatus {
    Running,
    Stopped,
    NotFound,
    Unknown,
}

pub async fn agent_status() -> Result<AgentInfo, VestaError> {
    run_json(&["status", "--json"]).await
}

pub async fn create_agent() -> Result<(), VestaError> {
    run(&["create"]).await?;
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

// ── Auth operations ────────────────────────────────────────────

pub async fn obtain_and_inject_credentials() -> Result<(), VestaError> {
    let credentials = run_setup_token().await?;
    run(&["auth", "--token", &credentials]).await?;
    Ok(())
}

async fn run_setup_token() -> Result<String, VestaError> {
    eprintln!("[vesta] exec: claude setup-token");
    let status = Command::new("claude")
        .args(["setup-token"])
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .status()
        .await
        .map_err(|e| {
            VestaError::new(
                ErrorCode::Internal,
                format!("failed to run 'claude setup-token'. is claude code installed?\n{}", e),
            )
        })?;

    if !status.success() {
        return Err(VestaError::new(ErrorCode::Internal, "claude setup-token failed"));
    }

    let creds_path = dirs::home_dir()
        .ok_or_else(|| VestaError::new(ErrorCode::Internal, "cannot determine home directory"))?
        .join(".claude")
        .join(".credentials.json");

    tokio::fs::read_to_string(&creds_path).await.map_err(|e| {
        VestaError::new(ErrorCode::Internal, format!("could not read credentials file: {}", e))
    })
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
    let path = cli_path();
    eprintln!("[vesta] spawn: {} logs", path.display());

    let mut cmd = Command::new(&path);
    cmd.arg("logs")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn()
        .map_err(|e| {
            eprintln!("[vesta] logs spawn failed: {}", e);
            VestaError::new(ErrorCode::ExecFailed, format!("failed to spawn cli: {}", e))
        })?;

    let stdout = match child.stdout.take() {
        Some(s) => s,
        None => {
            let _ = channel.send(LogEvent::Error { message: "no stdout".to_string() });
            return Ok(());
        }
    };

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
    tokio::spawn(async move {
        let timeout = tokio::time::Duration::from_secs(300);
        let _ = tokio::time::timeout(timeout, async {
            tokio::select! {
                _ = cancel_wait.cancelled() => { let _ = child.kill().await; }
                _ = child.wait() => { cancel_wait.cancel(); }
            }
        }).await;
    });

    Ok(())
}
