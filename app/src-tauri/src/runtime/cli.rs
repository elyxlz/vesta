use std::path::PathBuf;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::error::{ErrorCode, VestaError};

fn cli_path() -> PathBuf {
    let exe = std::env::current_exe().expect("cannot determine executable path");
    let dir = exe.parent().unwrap();

    #[cfg(target_os = "windows")]
    let name = "vesta.exe";
    #[cfg(not(target_os = "windows"))]
    let name = "vesta";

    let candidate = dir.join(name);
    if candidate.exists() {
        return candidate;
    }

    // Tauri puts sidecars in the same dir as the app binary on all platforms.
    // In dev, fall back to cargo build output.
    let dev_candidate = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("cli")
        .join("target")
        .join("release")
        .join(name);
    if dev_candidate.exists() {
        return dev_candidate;
    }

    let debug_candidate = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("cli")
        .join("target")
        .join("debug")
        .join(name);
    if debug_candidate.exists() {
        return debug_candidate;
    }

    candidate
}

async fn run(args: &[&str]) -> Result<String, VestaError> {
    let output = Command::new(cli_path())
        .args(args)
        .output()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to run cli: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let msg = stderr.trim().strip_prefix("error: ").unwrap_or(stderr.trim());
        return Err(VestaError::new(ErrorCode::Internal, msg.to_string()));
    }

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

async fn run_json<T: serde::de::DeserializeOwned>(args: &[&str]) -> Result<T, VestaError> {
    let stdout = run(args).await?;
    serde_json::from_str(&stdout)
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to parse cli output: {}", e)))
}

// ── Agent operations ────────────────────────────────────────────

use serde::Deserialize;

#[derive(Debug, Clone, serde::Serialize, Deserialize)]
pub struct StatusInfo {
    pub status: String,
    pub id: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct AgentInfo {
    pub status: AgentStatus,
    pub id: String,
}

#[derive(Debug, Clone, serde::Serialize, PartialEq)]
pub enum AgentStatus {
    Running,
    Stopped,
    NotFound,
    Unknown,
}

pub async fn agent_status() -> Result<AgentInfo, VestaError> {
    let info: StatusInfo = run_json(&["status", "--json"]).await?;
    let status = match info.status.as_str() {
        "running" => AgentStatus::Running,
        "stopped" => AgentStatus::Stopped,
        "not_found" => AgentStatus::NotFound,
        _ => AgentStatus::Unknown,
    };
    Ok(AgentInfo {
        status,
        id: info.id.unwrap_or_default(),
    })
}

pub async fn agent_exists() -> Result<bool, VestaError> {
    let info = agent_status().await?;
    Ok(info.status != AgentStatus::NotFound)
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

pub async fn delete_agent() -> Result<(), VestaError> {
    run(&["destroy", "--yes"]).await?;
    Ok(())
}

// ── Streaming operations ────────────────────────────────────────

use tauri::ipc::Channel;

#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "kind")]
pub enum ChatEvent {
    Attached,
    Output { text: String },
    Detached,
    Error { message: String },
}

pub struct AttachHandle {
    pub stdin_tx: mpsc::Sender<String>,
    pub cancel: CancellationToken,
}

pub async fn attach_to_agent(
    channel: Channel<ChatEvent>,
) -> Result<AttachHandle, VestaError> {
    let mut child = Command::new(cli_path())
        .arg("attach")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| VestaError::new(ErrorCode::AttachFailed, format!("failed to spawn cli: {}", e)))?;

    let stdout = child.stdout.take()
        .ok_or_else(|| VestaError::new(ErrorCode::AttachFailed, "no stdout"))?;
    let stdin = child.stdin.take()
        .ok_or_else(|| VestaError::new(ErrorCode::AttachFailed, "no stdin"))?;

    let cancel = CancellationToken::new();
    let (stdin_tx, mut stdin_rx) = mpsc::channel::<String>(64);

    let _ = channel.send(ChatEvent::Attached);

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
                        Ok(Some(text)) if !text.is_empty() => {
                            let _ = ch.send(ChatEvent::Output { text });
                        }
                        Ok(None) | Err(_) => break,
                        _ => {}
                    }
                }
            }
        }
        let _ = ch.send(ChatEvent::Detached);
    });

    let cancel_write = cancel.clone();
    tokio::spawn(async move {
        let mut stdin = stdin;
        loop {
            tokio::select! {
                _ = cancel_write.cancelled() => break,
                msg = stdin_rx.recv() => {
                    match msg {
                        Some(text) => {
                            if stdin.write_all(text.as_bytes()).await.is_err() {
                                break;
                            }
                            if stdin.flush().await.is_err() {
                                break;
                            }
                        }
                        None => break,
                    }
                }
            }
        }
    });

    let cancel_wait = cancel.clone();
    tokio::spawn(async move {
        tokio::select! {
            _ = cancel_wait.cancelled() => { let _ = child.kill().await; }
            _ = child.wait() => {}
        }
    });

    Ok(AttachHandle { stdin_tx, cancel })
}

#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "kind")]
pub enum AuthEvent {
    Output { text: String },
    UrlDetected { url: String },
    Complete,
    Error { message: String },
}

fn extract_auth_url(text: &str) -> Option<String> {
    let re = regex::Regex::new(r"https://[^\s]+(?:claude\.ai|anthropic\.com)[^\s]*").ok()?;
    re.find(text).map(|m| m.as_str().to_string())
}

pub async fn run_claude_auth(
    channel: Channel<AuthEvent>,
    cancel: CancellationToken,
) -> Result<(), VestaError> {
    let mut child = Command::new(cli_path())
        .arg("auth")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, format!("failed to spawn cli: {}", e)))?;

    let stdout = match child.stdout.take() {
        Some(s) => s,
        None => {
            let _ = channel.send(AuthEvent::Error { message: "no stdout".to_string() });
            return Ok(());
        }
    };

    let ch = channel.clone();
    let cancel_read = cancel.clone();
    tokio::spawn(async move {
        let reader = BufReader::new(stdout);
        let mut lines = reader.lines();
        loop {
            tokio::select! {
                _ = cancel_read.cancelled() => {
                    let _ = ch.send(AuthEvent::Error { message: "auth cancelled".to_string() });
                    break;
                }
                line = lines.next_line() => {
                    match line {
                        Ok(Some(text)) if !text.is_empty() => {
                            if let Some(url) = extract_auth_url(&text) {
                                let _ = ch.send(AuthEvent::UrlDetected { url });
                            }
                            let _ = ch.send(AuthEvent::Output { text });
                        }
                        Ok(None) | Err(_) => break,
                        _ => {}
                    }
                }
            }
        }
        let _ = ch.send(AuthEvent::Complete);
    });

    let cancel_wait = cancel.clone();
    tokio::spawn(async move {
        tokio::select! {
            _ = cancel_wait.cancelled() => { let _ = child.kill().await; }
            _ = child.wait() => {}
        }
    });

    Ok(())
}

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
    let mut child = Command::new(cli_path())
        .arg("logs")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, format!("failed to spawn cli: {}", e)))?;

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
                        Ok(Some(text)) if !text.is_empty() => {
                            let _ = ch.send(LogEvent::Line { text });
                        }
                        Ok(None) | Err(_) => break,
                        _ => {}
                    }
                }
            }
        }
        let _ = ch.send(LogEvent::End);
    });

    let cancel_wait = cancel.clone();
    tokio::spawn(async move {
        tokio::select! {
            _ = cancel_wait.cancelled() => { let _ = child.kill().await; }
            _ = child.wait() => {}
        }
    });

    Ok(())
}
