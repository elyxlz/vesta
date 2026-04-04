use tauri::ipc::Channel;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::error::{ErrorCode, VestaError};

pub use vesta_common::{AgentStatus, ListEntry, ServerConfig};

fn map_err(e: String) -> VestaError {
    VestaError::new(ErrorCode::Internal, e)
}

fn client() -> Result<vesta_common::client::Client, VestaError> {
    let config = vesta_common::load_server_config()
        .ok_or_else(|| VestaError::new(ErrorCode::Internal, "server not configured. run setup first"))?;
    Ok(vesta_common::client::Client::new(&config))
}

// ── Server config ───────────────────────────────────────────────

pub fn get_server_config() -> Result<ServerConfig, VestaError> {
    vesta_common::load_server_config()
        .ok_or_else(|| VestaError::new(ErrorCode::Internal, "server not configured. run setup first"))
}

pub async fn connect_to_server(url: String, api_key: String) -> Result<ServerConfig, VestaError> {
    let url = vesta_common::normalize_url(&url);

    // Validate with a temp client
    let config = ServerConfig {
        url,
        api_key,
        cert_fingerprint: None,
        cert_pem: None,
    };

    let c = vesta_common::client::Client::new(&config);
    tokio::task::spawn_blocking(move || {
        c.health().map_err(|e| format!("cannot reach server: {}", e))?;
        c.list_agents().map_err(|_| "invalid API key".to_string())?;
        Ok::<_, String>(())
    })
    .await
    .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
    .map_err(map_err)?;

    vesta_common::save_server_config(&config).map_err(map_err)?;
    Ok(config)
}

// ── Platform operations ─────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PlatformStatus {
    pub ready: bool,
    pub platform: String,
    #[serde(default)]
    pub message: String,
}

fn not_configured_status(message: &str) -> PlatformStatus {
    PlatformStatus {
        ready: false,
        platform: std::env::consts::OS.to_string(),
        message: message.to_string(),
    }
}

pub async fn auto_setup() -> Result<bool, VestaError> {
    auto_setup_with(None).await
}

pub async fn auto_setup_with(vestad_path: Option<&std::path::Path>) -> Result<bool, VestaError> {
    let path = vestad_path.map(|p| p.to_path_buf());
    let did_setup = tokio::task::spawn_blocking(move || {
        vesta_common::ensure_server_with(path.as_deref())
    })
    .await
    .map_err(|e| VestaError::new(ErrorCode::Internal, format!("setup task failed: {}", e)))?
    .map_err(map_err)?;
    Ok(did_setup)
}

pub async fn platform_check() -> Result<PlatformStatus, VestaError> {
    let c = match client() {
        Ok(c) => c,
        Err(_) => return Ok(not_configured_status("server not configured. run setup first")),
    };

    let result = tokio::task::spawn_blocking(move || c.health())
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?;

    match result {
        Ok(()) => Ok(PlatformStatus {
            ready: true,
            platform: std::env::consts::OS.to_string(),
            message: String::new(),
        }),
        Err(e) => Ok(not_configured_status(&e)),
    }
}

pub async fn platform_setup() -> Result<PlatformStatus, VestaError> {
    tokio::task::spawn_blocking(vesta_common::ensure_server)
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("setup task failed: {}", e)))?
        .map_err(map_err)?;
    platform_check().await
}

// ── Agent operations ────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AgentInfo {
    pub status: AgentStatus,
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub authenticated: bool,
    pub name: String,
    #[serde(default)]
    pub agent_ready: bool,
    #[serde(default = "default_ws_port")]
    pub ws_port: u16,
    #[serde(default)]
    pub alive: bool,
    #[serde(default)]
    pub friendly_status: String,
}

fn default_ws_port() -> u16 {
    vesta_common::DEFAULT_WS_PORT
}

pub async fn list_agents() -> Result<Vec<ListEntry>, VestaError> {
    let c = client()?;
    tokio::task::spawn_blocking(move || c.list_agents())
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

pub async fn agent_status(name: &str) -> Result<AgentInfo, VestaError> {
    let c = client()?;
    let name = name.to_string();
    let json: vesta_common::StatusJson = tokio::task::spawn_blocking(move || c.agent_status(&name))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)?;

    // Convert StatusJson to AgentInfo (with enum status)
    let status = match json.status.as_str() {
        "running" => AgentStatus::Running,
        "stopped" | "exited" | "created" => AgentStatus::Stopped,
        "dead" => AgentStatus::Dead,
        "not_found" => AgentStatus::NotFound,
        _ => AgentStatus::Unknown,
    };

    Ok(AgentInfo {
        status,
        id: json.id.unwrap_or_default(),
        authenticated: json.authenticated,
        name: json.name,
        agent_ready: json.agent_ready,
        ws_port: json.ws_port,
        alive: json.alive,
        friendly_status: json.friendly_status,
    })
}

pub async fn create_agent(name: Option<String>) -> Result<(), VestaError> {
    let c = client()?;
    let agent_name = name.unwrap_or_else(|| "default".to_string());
    tokio::task::spawn_blocking(move || c.create_agent(&agent_name, false))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)?;
    Ok(())
}

pub async fn start_agent(name: &str) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    tokio::task::spawn_blocking(move || c.start_agent(&name))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

pub async fn stop_agent(name: &str) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    tokio::task::spawn_blocking(move || c.stop_agent(&name))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

pub async fn restart_agent(name: &str) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    tokio::task::spawn_blocking(move || c.restart_agent(&name))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

pub async fn delete_agent(name: &str) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    tokio::task::spawn_blocking(move || c.destroy_agent(&name))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

pub async fn rebuild_agent(name: &str) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    tokio::task::spawn_blocking(move || c.rebuild_agent(&name))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

// ── Auth operations ─────────────────────────────────────────────

pub async fn obtain_and_inject_credentials(
    name: &str,
    on_event: impl Fn(&str, Option<&str>) + Send + Sync + 'static,
    code_rx: tokio::sync::oneshot::Receiver<String>,
) -> Result<(), VestaError> {
    let c = client()?;
    let name_str = name.to_string();
    let auth = tokio::task::spawn_blocking(move || c.start_auth(&name_str))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)?;

    on_event("auth-url", Some(&auth.auth_url));
    on_event("auth-code-needed", None);

    let code = match tokio::time::timeout(
        tokio::time::Duration::from_secs(600),
        code_rx,
    )
    .await
    {
        Ok(Ok(code)) => code,
        Ok(Err(_)) => return Err(VestaError::new(ErrorCode::Internal, "auth cancelled")),
        Err(_) => {
            return Err(VestaError::new(
                ErrorCode::Timeout,
                "authentication timed out after 10 minutes",
            ))
        }
    };

    let c = client()?;
    let name_str = name.to_string();
    tokio::task::spawn_blocking(move || c.complete_auth(&name_str, &auth.session_id, &code))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

// ── Backup/Restore operations ───────────────────────────────────

pub async fn backup_agent(name: &str, output: &str) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    let output = std::path::PathBuf::from(output);
    tokio::task::spawn_blocking(move || c.backup(&name, &output))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

pub async fn restore_agent(
    input: &str,
    name: Option<&str>,
    replace: bool,
) -> Result<(), VestaError> {
    let c = client()?;
    let input = std::path::PathBuf::from(input);
    let name = name.map(|n| n.to_string());
    tokio::task::spawn_blocking(move || c.restore(&input, name.as_deref(), replace))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)?;
    Ok(())
}

pub async fn wait_for_ready(name: &str, timeout_secs: u64) -> Result<(), VestaError> {
    let c = client()?;
    let name = name.to_string();
    tokio::task::spawn_blocking(move || c.wait_ready(&name, timeout_secs))
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?
        .map_err(map_err)
}

// ── Agent host ──────────────────────────────────────────────────

pub async fn agent_host() -> String {
    match vesta_common::load_server_config() {
        Some(config) => {
            let stripped = config
                .url
                .strip_prefix("https://")
                .or_else(|| config.url.strip_prefix("http://"))
                .unwrap_or(&config.url);
            stripped
                .split(':')
                .next()
                .unwrap_or("localhost")
                .to_string()
        }
        None => "localhost".to_string(),
    }
}

// ── Streaming operations ────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "kind")]
pub enum LogEvent {
    Line { text: String },
    End,
    Error { message: String },
}

pub async fn stream_agent_logs(
    name: &str,
    channel: Channel<LogEvent>,
    cancel: CancellationToken,
) -> Result<(), VestaError> {
    let config = vesta_common::load_server_config()
        .ok_or_else(|| VestaError::new(ErrorCode::Internal, "server not configured"))?;
    let url = format!("{}/agents/{}/logs", config.url, name);

    // Streaming logs needs async reqwest — can't do this with sync ureq
    let mut builder = reqwest::Client::builder();
    if let Some(ref pem) = config.cert_pem {
        if let Ok(cert) = reqwest::Certificate::from_pem(pem.as_bytes()) {
            builder = builder
                .add_root_certificate(cert)
                .tls_built_in_root_certs(false);
        }
    }
    let http = builder.build().map_err(|e| VestaError::new(ErrorCode::Internal, e.to_string()))?;

    let resp = http
        .get(&url)
        .bearer_auth(&config.api_key)
        .send()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to connect to log stream: {}", e)))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        let msg = vesta_common::client::extract_server_error(&body)
            .unwrap_or_else(|| format!("server returned {}", status));
        return Err(VestaError::new(ErrorCode::Internal, msg));
    }

    let ch = channel.clone();
    tokio::spawn(async move {
        use futures_util::StreamExt;

        let mut stream = resp.bytes_stream();
        let mut buffer = String::new();

        loop {
            tokio::select! {
                _ = cancel.cancelled() => break,
                chunk = stream.next() => {
                    match chunk {
                        Some(Ok(bytes)) => {
                            let text = String::from_utf8_lossy(&bytes);
                            buffer.push_str(&text);

                            while let Some(pos) = buffer.find('\n') {
                                let line = buffer[..pos].trim_end().to_string();
                                buffer = buffer[pos + 1..].to_string();

                                if line.is_empty() || line.starts_with(':') {
                                    continue;
                                }

                                if let Some(data) = line.strip_prefix("data: ") {
                                    let _ = ch.send(LogEvent::Line { text: data.to_string() });
                                } else {
                                    let _ = ch.send(LogEvent::Line { text: line });
                                }
                            }
                        }
                        Some(Err(e)) => {
                            let _ = ch.send(LogEvent::Error { message: e.to_string() });
                            break;
                        }
                        None => break,
                    }
                }
            }
        }
        let _ = ch.send(LogEvent::End);
    });

    Ok(())
}

// ── WebSocket proxy ────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "kind")]
pub enum WsEvent {
    Message { text: String },
    Open,
    Close,
    Error { message: String },
}

pub async fn connect_agent_ws(
    name: &str,
    channel: Channel<WsEvent>,
    cancel: CancellationToken,
) -> Result<mpsc::Sender<String>, VestaError> {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite;

    let config = vesta_common::load_server_config()
        .ok_or_else(|| VestaError::new(ErrorCode::Internal, "server not configured"))?;

    let ws_url = format!(
        "{}/agents/{}/ws?token={}",
        vesta_common::client::ws_base_url(&config.url),
        name,
        config.api_key
    );

    let tls_config = vesta_common::client::make_ws_rustls_config(
        config.cert_fingerprint.clone(),
    );
    let connector = tokio_tungstenite::Connector::Rustls(tls_config);

    let (ws_stream, _) = tokio_tungstenite::connect_async_tls_with_config(
        &ws_url,
        None,
        false,
        Some(connector),
    )
    .await
    .map_err(|e| VestaError::new(ErrorCode::Internal, format!("ws connect failed: {}", e)))?;

    let (mut sink, mut stream) = ws_stream.split();
    let (tx, mut rx) = mpsc::channel::<String>(64);

    let ch = channel.clone();
    let _ = ch.send(WsEvent::Open);

    let cancel_read = cancel.clone();
    let ch_read = channel.clone();
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = cancel_read.cancelled() => break,
                msg = stream.next() => {
                    match msg {
                        Some(Ok(tungstenite::Message::Text(text))) => {
                            let _ = ch_read.send(WsEvent::Message { text: text.to_string() });
                        }
                        Some(Ok(tungstenite::Message::Close(_))) | None => break,
                        Some(Err(e)) => {
                            let _ = ch_read.send(WsEvent::Error { message: e.to_string() });
                            break;
                        }
                        _ => {}
                    }
                }
            }
        }
        let _ = ch_read.send(WsEvent::Close);
        cancel_read.cancel();
    });

    let cancel_write = cancel;
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = cancel_write.cancelled() => break,
                msg = rx.recv() => {
                    match msg {
                        Some(text) => {
                            if sink.send(tungstenite::Message::Text(text.into())).await.is_err() {
                                break;
                            }
                        }
                        None => break,
                    }
                }
            }
        }
        let _ = sink.close().await;
    });

    Ok(tx)
}
