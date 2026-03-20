use std::path::PathBuf;
use std::sync::OnceLock;

use tauri::ipc::Channel;
use tokio::io::AsyncBufReadExt;
use tokio_util::sync::CancellationToken;

use crate::error::{ErrorCode, VestaError};

const SETUP_TIMEOUT_SECS: u64 = 600;

// ── Server config ───────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ServerConfig {
    pub url: String,
    pub api_key: String,
    #[serde(default)]
    pub cert_fingerprint: String,
}

fn config_path() -> Result<PathBuf, VestaError> {
    let config_dir = dirs::config_dir()
        .ok_or_else(|| VestaError::new(ErrorCode::Internal, "cannot determine config dir"))?;
    Ok(config_dir.join("vesta").join("server.json"))
}

fn load_config() -> Result<ServerConfig, VestaError> {
    let path = config_path()?;
    let content = std::fs::read_to_string(&path)
        .map_err(|_| VestaError::new(ErrorCode::Internal, "server not configured. run setup first"))?;
    let config: ServerConfig = serde_json::from_str(&content)
        .map_err(|_| VestaError::new(ErrorCode::Internal, "invalid server.json"))?;
    if config.url.is_empty() {
        return Err(VestaError::new(ErrorCode::Internal, "no url in server.json"));
    }
    if config.api_key.is_empty() {
        return Err(VestaError::new(ErrorCode::Internal, "no api_key in server.json"));
    }
    Ok(config)
}

pub fn get_server_config() -> Result<ServerConfig, VestaError> {
    load_config()
}

// ── HTTP client ─────────────────────────────────────────────────

fn http_client() -> reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT
        .get_or_init(|| {
            reqwest::Client::builder()
                .danger_accept_invalid_certs(true)
                .build()
                .expect("failed to create HTTP client")
        })
        .clone()
}

async fn api_get<T: serde::de::DeserializeOwned>(path: &str) -> Result<T, VestaError> {
    let config = load_config()?;
    let url = format!("{}{}", config.url, path);
    let resp = http_client()
        .get(&url)
        .bearer_auth(&config.api_key)
        .send()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("request failed: {}", e)))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        let msg = extract_server_error(&body)
            .unwrap_or_else(|| format!("server returned {}", status));
        return Err(VestaError::new(ErrorCode::Internal, msg));
    }

    resp.json::<T>()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to parse response: {}", e)))
}

async fn api_post<T: serde::de::DeserializeOwned>(
    path: &str,
    body: &impl serde::Serialize,
) -> Result<T, VestaError> {
    let config = load_config()?;
    let url = format!("{}{}", config.url, path);
    let resp = http_client()
        .post(&url)
        .bearer_auth(&config.api_key)
        .json(body)
        .send()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("request failed: {}", e)))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        let msg = extract_server_error(&body)
            .unwrap_or_else(|| format!("server returned {}", status));
        return Err(VestaError::new(ErrorCode::Internal, msg));
    }

    resp.json::<T>()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("failed to parse response: {}", e)))
}

async fn api_post_empty(path: &str, body: &impl serde::Serialize) -> Result<(), VestaError> {
    let config = load_config()?;
    let url = format!("{}{}", config.url, path);
    let resp = http_client()
        .post(&url)
        .bearer_auth(&config.api_key)
        .json(body)
        .send()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("request failed: {}", e)))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        let msg = extract_server_error(&body)
            .unwrap_or_else(|| format!("server returned {}", status));
        return Err(VestaError::new(ErrorCode::Internal, msg));
    }

    Ok(())
}

async fn api_delete(path: &str) -> Result<(), VestaError> {
    let config = load_config()?;
    let url = format!("{}{}", config.url, path);
    let resp = http_client()
        .delete(&url)
        .bearer_auth(&config.api_key)
        .send()
        .await
        .map_err(|e| VestaError::new(ErrorCode::Internal, format!("request failed: {}", e)))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        let msg = extract_server_error(&body)
            .unwrap_or_else(|| format!("server returned {}", status));
        return Err(VestaError::new(ErrorCode::Internal, msg));
    }

    Ok(())
}

fn extract_server_error(body: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    v["error"].as_str().map(|s| s.to_string())
}

// ── CLI for first-run setup ─────────────────────────────────────

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

fn cli_command(args: &[&str]) -> tokio::process::Command {
    let path = cli_path();
    eprintln!("[vesta] exec: {} {}", path.display(), args.join(" "));
    let mut cmd = tokio::process::Command::new(path.as_os_str());
    cmd.args(args);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

async fn run_cli_with_timeout(args: &[&str], timeout_secs: u64) -> Result<String, VestaError> {
    let mut cmd = cli_command(args);
    cmd.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| {
        VestaError::new(ErrorCode::ExecFailed, format!("failed to run cli: {}", e))
    })?;

    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();

    let stdout_task = tokio::spawn(async move {
        let mut lines = tokio::io::BufReader::new(stdout).lines();
        let mut buf = String::new();
        while let Ok(Some(line)) = lines.next_line().await {
            eprintln!("[vesta] {}", line);
            if !buf.is_empty() {
                buf.push('\n');
            }
            buf.push_str(&line);
        }
        buf
    });

    let stderr_task = tokio::spawn(async move {
        let mut lines = tokio::io::BufReader::new(stderr).lines();
        let mut buf = String::new();
        while let Ok(Some(line)) = lines.next_line().await {
            eprintln!("[vesta] {}", line);
            if !buf.is_empty() {
                buf.push('\n');
            }
            buf.push_str(&line);
        }
        buf
    });

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
        let msg = stderr_str
            .lines()
            .rev()
            .find(|l| l.trim().starts_with("error: "))
            .map(|l| l.trim().strip_prefix("error: ").unwrap().to_string())
            .or_else(|| {
                stderr_str
                    .lines()
                    .rev()
                    .find(|l| !l.trim().is_empty())
                    .map(|l| l.trim().to_string())
            })
            .unwrap_or_else(|| "command failed with no output".to_string());
        return Err(VestaError::new(ErrorCode::Internal, msg));
    }

    Ok(stdout_str)
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

fn not_configured_status(message: &str) -> PlatformStatus {
    PlatformStatus {
        ready: false,
        platform: std::env::consts::OS.to_string(),
        wsl_installed: false,
        virtualization_enabled: None,
        distro_registered: false,
        distro_healthy: false,
        services_ready: false,
        needs_reboot: false,
        message: message.to_string(),
    }
}

pub async fn platform_check() -> Result<PlatformStatus, VestaError> {
    let config = match load_config() {
        Ok(c) => c,
        Err(_) => return Ok(not_configured_status("server not configured. run setup first")),
    };

    let url = format!("{}/health", config.url);
    let result = http_client()
        .get(&url)
        .bearer_auth(&config.api_key)
        .timeout(std::time::Duration::from_secs(5))
        .send()
        .await;

    match result {
        Ok(resp) if resp.status().is_success() => Ok(PlatformStatus {
            ready: true,
            platform: std::env::consts::OS.to_string(),
            wsl_installed: true,
            virtualization_enabled: Some(true),
            distro_registered: true,
            distro_healthy: true,
            services_ready: true,
            needs_reboot: false,
            message: String::new(),
        }),
        Ok(resp) => Ok(not_configured_status(&format!(
            "server returned {}",
            resp.status()
        ))),
        Err(e) => Ok(not_configured_status(&format!(
            "cannot reach server: {}",
            e
        ))),
    }
}

pub async fn platform_setup() -> Result<PlatformStatus, VestaError> {
    run_cli_with_timeout(&["setup"], SETUP_TIMEOUT_SECS).await?;
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
    7865
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ListEntry {
    pub name: String,
    pub status: String,
    pub authenticated: bool,
    pub agent_ready: bool,
    pub ws_port: u16,
    #[serde(default)]
    pub alive: bool,
    #[serde(default)]
    pub friendly_status: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum AgentStatus {
    Running,
    Stopped,
    Dead,
    NotFound,
    Unknown,
}

pub async fn list_agents() -> Result<Vec<ListEntry>, VestaError> {
    api_get("/agents").await
}

pub async fn agent_status(name: &str) -> Result<AgentInfo, VestaError> {
    api_get(&format!("/agents/{}", name)).await
}

#[derive(serde::Serialize)]
struct CreateRequest {
    name: String,
}

pub async fn create_agent(name: Option<String>) -> Result<(), VestaError> {
    let agent_name = name.unwrap_or_else(|| "default".to_string());
    api_post_empty("/agents", &CreateRequest { name: agent_name }).await
}

#[derive(serde::Serialize)]
struct EmptyBody {}

pub async fn start_agent(name: &str) -> Result<(), VestaError> {
    api_post_empty(&format!("/agents/{}/start", name), &EmptyBody {}).await
}

pub async fn stop_agent(name: &str) -> Result<(), VestaError> {
    api_post_empty(&format!("/agents/{}/stop", name), &EmptyBody {}).await
}

pub async fn restart_agent(name: &str) -> Result<(), VestaError> {
    api_post_empty(&format!("/agents/{}/restart", name), &EmptyBody {}).await
}

pub async fn delete_agent(name: &str) -> Result<(), VestaError> {
    api_delete(&format!("/agents/{}", name)).await
}

pub async fn rebuild_agent(name: &str) -> Result<(), VestaError> {
    api_post_empty(&format!("/agents/{}/rebuild", name), &EmptyBody {}).await
}

// ── Auth operations ─────────────────────────────────────────────

#[derive(serde::Deserialize)]
struct AuthResponse {
    auth_url: String,
    session_id: String,
}

#[derive(serde::Serialize)]
struct AuthCodeRequest {
    session_id: String,
    code: String,
}

pub async fn obtain_and_inject_credentials(
    name: &str,
    on_event: impl Fn(&str, Option<&str>) + Send + Sync + 'static,
    code_rx: tokio::sync::oneshot::Receiver<String>,
) -> Result<(), VestaError> {
    let auth: AuthResponse = api_post(&format!("/agents/{}/auth", name), &EmptyBody {}).await?;

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

    api_post_empty(
        &format!("/agents/{}/auth/code", name),
        &AuthCodeRequest {
            session_id: auth.session_id,
            code,
        },
    )
    .await
}

// ── Backup/Restore operations ───────────────────────────────────

#[derive(serde::Serialize)]
struct BackupRequest {
    output: String,
}

pub async fn backup_agent(name: &str, output: &str) -> Result<(), VestaError> {
    api_post_empty(
        &format!("/agents/{}/backup", name),
        &BackupRequest {
            output: output.to_string(),
        },
    )
    .await
}

#[derive(serde::Serialize)]
struct RestoreRequest {
    input: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    replace: bool,
}

pub async fn restore_agent(
    input: &str,
    name: Option<&str>,
    replace: bool,
) -> Result<(), VestaError> {
    api_post_empty(
        "/agents/restore",
        &RestoreRequest {
            input: input.to_string(),
            name: name.map(|s| s.to_string()),
            replace,
        },
    )
    .await
}

pub async fn wait_for_ready(name: &str, timeout: u64) -> Result<(), VestaError> {
    let start = std::time::Instant::now();
    let deadline = std::time::Duration::from_secs(timeout);

    loop {
        if start.elapsed() > deadline {
            return Err(VestaError::new(
                ErrorCode::Timeout,
                format!("agent not ready after {}s", timeout),
            ));
        }

        match agent_status(name).await {
            Ok(info) if info.agent_ready => return Ok(()),
            _ => {}
        }

        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
    }
}

// ── Agent host ──────────────────────────────────────────────────

pub async fn agent_host() -> String {
    match load_config() {
        Ok(config) => {
            // Extract host from URL like "https://192.168.1.50:7860"
            let stripped = config
                .url
                .strip_prefix("https://")
                .or_else(|| config.url.strip_prefix("http://"))
                .unwrap_or(&config.url);
            // Remove port if present
            stripped
                .split(':')
                .next()
                .unwrap_or("localhost")
                .to_string()
        }
        Err(_) => "localhost".to_string(),
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
    let config = load_config()?;
    let url = format!("{}/agents/{}/logs", config.url, name);

    let resp = http_client()
        .get(&url)
        .bearer_auth(&config.api_key)
        .send()
        .await
        .map_err(|e| {
            VestaError::new(
                ErrorCode::Internal,
                format!("failed to connect to log stream: {}", e),
            )
        })?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        let msg = extract_server_error(&body)
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

                            // Process complete lines
                            while let Some(pos) = buffer.find('\n') {
                                let line = buffer[..pos].trim_end().to_string();
                                buffer = buffer[pos + 1..].to_string();

                                if line.is_empty() || line.starts_with(':') {
                                    continue;
                                }

                                // SSE format: lines starting with "data: "
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
                        None => break, // Stream ended
                    }
                }
            }
        }
        let _ = ch.send(LogEvent::End);
    });

    Ok(())
}
