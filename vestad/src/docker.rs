use serde::Serialize;
use std::process;
use crate::types::{BackupInfo, BackupType};

#[derive(Debug)]
pub enum DockerError {
    NotFound(String),
    AlreadyExists(String),
    NotRunning(String),
    BrokenState(String),
    InvalidName(String),
    BuildRequired(String),
    Failed(String),
}

impl std::fmt::Display for DockerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound(s) | Self::AlreadyExists(s) | Self::NotRunning(s)
            | Self::BrokenState(s) | Self::InvalidName(s) | Self::BuildRequired(s)
            | Self::Failed(s) => write!(f, "{}", s),
        }
    }
}

pub const VESTA_IMAGE: &str = "ghcr.io/elyxlz/vesta:latest";
pub const VESTA_LOG_PATH: &str = "/root/vesta/logs/vesta.log";
pub const LOCAL_IMAGE_TAG: &str = "vesta:local";
const MAX_DOCKERFILE_SEARCH_DEPTH: usize = 5;
pub const CREDENTIALS_PATH: &str = "/root/.claude/.credentials.json";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";
pub const BASE_WS_PORT: u16 = 7865;
const NAME_MAX_LEN: usize = 32;
const DOCKER_DAEMON_WAIT_RETRIES: usize = 10;
const AGENT_READY_TIMEOUT_MS: u64 = 200;
const WAIT_READY_POLL_MS: u64 = 500;
const DEFAULT_TOKEN_EXPIRES_SECS: u64 = 28800;
const LABEL_USER: &str = "vesta.user";


pub const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
pub const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
pub const OAUTH_TOKEN_URL: &str = "https://api.anthropic.com/v1/oauth/token";
pub const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

const ENTRYPOINT: &[&str] = &["uv", "run", "--project", "/root/vesta", "python", "-m", "vesta.main"];

#[derive(PartialEq, Clone, Copy)]
pub enum ContainerStatus {
    Running,
    Stopped,
    NotFound,
    Dead,
}

#[derive(Serialize, Clone)]
pub struct StatusJson {
    pub name: String,
    pub status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub authenticated: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub agent_ready: bool,
    pub ws_port: u16,
    pub alive: bool,
    pub friendly_status: &'static str,
}

#[derive(Serialize, Clone)]
pub struct ListEntry {
    pub name: String,
    pub status: &'static str,
    pub authenticated: bool,
    pub agent_ready: bool,
    pub ws_port: u16,
    pub alive: bool,
    pub friendly_status: &'static str,
}

pub fn container_name(name: &str) -> String {
    format!("vesta-{}-{}", current_user(), name)
}

pub fn name_from_cname(cname: &str) -> String {
    let without_vesta = cname.strip_prefix("vesta-").unwrap_or(cname);
    let user = current_user();
    let user_prefix = format!("{}-", user);
    without_vesta.strip_prefix(&user_prefix).unwrap_or(without_vesta).to_string()
}

pub fn normalize_name(raw: &str) -> String {
    let s: String = raw
        .trim()
        .to_lowercase()
        .replace(|c: char| c.is_whitespace() || c == '_', "-")
        .chars()
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '-')
        .collect();
    let s = s.trim_matches('-').to_string();
    let mut result = String::new();
    let mut prev_hyphen = false;
    for c in s.chars() {
        if c == '-' {
            if !prev_hyphen {
                result.push(c);
            }
            prev_hyphen = true;
        } else {
            result.push(c);
            prev_hyphen = false;
        }
    }
    if result.len() > NAME_MAX_LEN {
        result.truncate(NAME_MAX_LEN);
        result = result.trim_end_matches('-').to_string();
    }
    result
}

pub fn validate_name(name: &str) -> Result<(), DockerError> {
    if name.is_empty() || name.len() > NAME_MAX_LEN {
        return Err(DockerError::InvalidName("agent name must be 1-32 characters".into()));
    }
    let valid = if name.len() == 1 {
        name.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
    } else {
        let chars: Vec<char> = name.chars().collect();
        let first_last_ok = (chars[0].is_ascii_lowercase() || chars[0].is_ascii_digit())
            && (chars[chars.len() - 1].is_ascii_lowercase()
                || chars[chars.len() - 1].is_ascii_digit());
        let middle_ok = chars
            .iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '-');
        first_last_ok && middle_ok
    };
    if !valid {
        return Err(DockerError::InvalidName("agent name must match [a-z0-9][a-z0-9-]*[a-z0-9]".into()));
    }
    Ok(())
}

fn current_user() -> String {
    std::env::var("USER")
        .or_else(|_| std::env::var("LOGNAME"))
        .unwrap_or_else(|_| "unknown".into())
}

// --- Docker helpers ---

pub fn docker(args: &[&str]) -> Result<process::ExitStatus, DockerError> {
    process::Command::new("docker")
        .args(args)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::inherit())
        .status()
        .map_err(|e| DockerError::Failed(format!("failed to run docker: {e}")))
}

pub fn docker_ok(args: &[&str]) -> bool {
    docker(args).map(|s| s.success()).unwrap_or(false)
}

pub fn docker_output(args: &[&str]) -> Option<String> {
    let output = process::Command::new("docker")
        .args(args)
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(
        String::from_utf8_lossy(&output.stdout)
            .trim()
            .to_string(),
    )
}

pub fn docker_quiet(args: &[&str]) -> bool {
    process::Command::new("docker")
        .args(args)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

pub fn ensure_docker() -> Result<(), DockerError> {
    if !docker_quiet(&["--version"]) {
        return Err(DockerError::Failed("docker is not installed".into()));
    }

    // Check permission on the first attempt — no point retrying 10 times if it's a group issue
    if let Some(err) = check_docker_permission() {
        return Err(err);
    }

    for _ in 0..DOCKER_DAEMON_WAIT_RETRIES {
        if docker_quiet(&["info"]) {
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }

    Err(DockerError::Failed("docker daemon is not running. start it with: sudo systemctl start docker".into()))
}

/// Run `docker info` once and check stderr for permission-denied errors.
fn check_docker_permission() -> Option<DockerError> {
    let output = process::Command::new("docker")
        .args(["info"])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::piped())
        .output()
        .ok()?;
    if output.status.success() {
        return None;
    }
    let stderr = String::from_utf8_lossy(&output.stderr).to_lowercase();
    if stderr.contains("permission denied") {
        return Some(DockerError::Failed(
            "docker permission denied. add your user to the docker group:\n  \
             sudo usermod -aG docker $USER\n  \
             then log out and back in (or run: newgrp docker)".to_string()
        ));
    }
    None
}

// --- Container query operations ---

pub struct ContainerInfo {
    pub status: ContainerStatus,
    pub port: u16,
    pub id: Option<String>,
}

pub struct AgentDerivedState {
    pub authenticated: bool,
    pub agent_ready: bool,
    pub alive: bool,
    pub friendly_status: &'static str,
}

pub fn compute_agent_state(cname: &str, info: &ContainerInfo) -> AgentDerivedState {
    let authenticated = info.status != ContainerStatus::NotFound && is_authenticated(cname);
    let agent_ready = info.status == ContainerStatus::Running && is_agent_ready(info.port);
    let alive = info.status == ContainerStatus::Running && authenticated;
    let friendly_status = friendly_status(&info.status, authenticated, agent_ready);
    AgentDerivedState { authenticated, agent_ready, alive, friendly_status }
}

fn inspect_container(cname: &str) -> ContainerInfo {
    match docker_output(&[
        "inspect",
        "--format",
        "{{.State.Status}}|{{index .Config.Labels \"vesta.ws_port\"}}|{{.Id}}",
        cname,
    ]) {
        Some(s) => {
            let parts: Vec<&str> = s.splitn(3, '|').collect();
            let status = match parts.first().map(|p| p.trim()) {
                Some("running" | "restarting" | "paused") => ContainerStatus::Running,
                Some("exited" | "created") => ContainerStatus::Stopped,
                Some("dead" | "removing") => ContainerStatus::Dead,
                _ => ContainerStatus::Stopped,
            };
            let port = parts
                .get(1)
                .and_then(|p| p.trim().parse().ok())
                .unwrap_or(BASE_WS_PORT);
            let id = parts
                .get(2)
                .map(|p| p.trim().chars().take(12).collect::<String>());
            ContainerInfo { status, port, id }
        }
        None => ContainerInfo {
            status: ContainerStatus::NotFound,
            port: BASE_WS_PORT,
            id: None,
        },
    }
}

pub fn container_status(cname: &str) -> ContainerStatus {
    inspect_container(cname).status
}

pub fn read_container_file(cname: &str, container_path: &str) -> Option<String> {
    let tmp = std::env::temp_dir().join(format!(
        "vesta_read_{}_{}",
        std::process::id(),
        cname
    ));
    let src = format!("{}:{}", cname, container_path);
    if !docker_quiet(&["cp", &src, tmp.to_str().unwrap()]) {
        return None;
    }
    let content = std::fs::read_to_string(&tmp).ok();
    std::fs::remove_file(&tmp).ok();
    content
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

pub fn is_authenticated(cname: &str) -> bool {
    let Some(content) = read_container_file(cname, CREDENTIALS_PATH) else {
        return false;
    };
    let Ok(creds) = serde_json::from_str::<serde_json::Value>(&content) else {
        return false;
    };
    let Some(expires_at) = creds["claudeAiOauth"]["expiresAt"].as_u64() else {
        return false;
    };
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    expires_at > now_ms
}

pub fn is_agent_ready(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(AGENT_READY_TIMEOUT_MS),
    )
    .is_ok()
}

pub fn ensure_exists(cname: &str) -> Result<(), DockerError> {
    match container_status(cname) {
        ContainerStatus::NotFound => Err(DockerError::NotFound(format!("agent '{}' not found", name_from_cname(cname)))),
        ContainerStatus::Dead => Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name_from_cname(cname)))),
        _ => Ok(()),
    }
}

pub fn ensure_running(cname: &str) -> Result<(), DockerError> {
    let cs = container_status(cname);
    match cs {
        ContainerStatus::NotFound => Err(DockerError::NotFound(format!("agent '{}' not found", name_from_cname(cname)))),
        ContainerStatus::Dead => Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name_from_cname(cname)))),
        ContainerStatus::Running => Ok(()),
        ContainerStatus::Stopped => Err(DockerError::NotRunning(format!("agent '{}' is not running", name_from_cname(cname)))),
    }
}

// --- Image and port operations ---

pub fn find_dockerfile() -> Result<std::path::PathBuf, DockerError> {
    let cwd = std::env::current_dir()
        .map_err(|_| DockerError::BuildRequired("cannot determine working directory".into()))?;
    if cwd.join("Dockerfile").exists() {
        return Ok(cwd);
    }

    let exe = std::env::current_exe()
        .map_err(|_| DockerError::BuildRequired("cannot determine executable path".into()))?;
    let mut dir = exe.parent().map(std::path::Path::to_path_buf);
    let mut depth = 0;
    while let Some(d) = dir {
        if depth >= MAX_DOCKERFILE_SEARCH_DEPTH {
            break;
        }
        if d.join("Dockerfile").exists() {
            return Ok(d);
        }
        dir = d.parent().map(std::path::Path::to_path_buf);
        depth += 1;
    }
    Err(DockerError::BuildRequired("--build requires vestad to have access to the Vesta source code (run vestad from the repo root)".into()))
}

pub fn resolve_image(build: bool) -> Result<&'static str, DockerError> {
    if build {
        let context = find_dockerfile()?;
        let status = process::Command::new("docker")
            .args(["build", "-t", LOCAL_IMAGE_TAG, "."])
            .current_dir(&context)
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::inherit())
            .status()
            .map_err(|e| DockerError::Failed(format!("docker build failed: {}", e)))?;
        if !status.success() {
            return Err(DockerError::Failed("image build failed".into()));
        }
        Ok(LOCAL_IMAGE_TAG)
    } else {
        if !docker_quiet(&["pull", VESTA_IMAGE]) {
            return Err(DockerError::Failed("failed to pull image".into()));
        }
        Ok(VESTA_IMAGE)
    }
}

pub fn allocate_port() -> u16 {
    let containers = list_managed_containers();
    let used: Vec<u16> = if containers.is_empty() {
        vec![]
    } else {
        let args: Vec<&str> = ["inspect", "--format", "{{index .Config.Labels \"vesta.ws_port\"}}"]
            .iter()
            .copied()
            .chain(containers.iter().map(|s| s.as_str()))
            .collect();
        docker_output(&args)
            .unwrap_or_default()
            .lines()
            .filter_map(|s| s.trim().parse().ok())
            .collect()
    };
    let mut port = BASE_WS_PORT;
    while used.contains(&port) {
        port += 1;
    }
    port
}

pub fn get_container_port(cname: &str) -> u16 {
    docker_output(&[
        "inspect",
        "--format",
        "{{index .Config.Labels \"vesta.ws_port\"}}",
        cname,
    ])
    .and_then(|s| s.parse().ok())
    .unwrap_or(BASE_WS_PORT)
}

pub fn list_managed_containers() -> Vec<String> {
    // Get all vesta-managed containers with their user label
    let all = docker_output(&[
        "ps",
        "-a",
        "--filter",
        "label=vesta.managed=true",
        "--format",
        &format!("{{{{.Names}}}}\t{{{{.Label \"{LABEL_USER}\"}}}}"),
    ])
    .unwrap_or_default();

    let user = current_user();
    all.lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|line| {
            let mut parts = line.splitn(2, '\t');
            let name = parts.next()?.trim();
            let owner = parts.next().unwrap_or("").trim();
            // Show containers owned by this user, or legacy containers with no owner
            if owner == user || owner.is_empty() {
                Some(name.to_string())
            } else {
                None
            }
        })
        .collect()
}

// --- GPU detection ---

enum GpuStatus {
    Ready,
    NoRuntime,
    NoGpu,
}

fn gpu_available() -> GpuStatus {
    let has_gpu = std::process::Command::new("nvidia-smi")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    if !has_gpu {
        return GpuStatus::NoGpu;
    }

    let has_runtime = docker_output(&["info", "--format", "{{json .Runtimes}}"])
        .map(|s| s.contains("nvidia"))
        .unwrap_or(false);

    if has_runtime { GpuStatus::Ready } else { GpuStatus::NoRuntime }
}

// --- Container creation ---

pub fn create_container(cname: &str, image: &str, port: u16, agent_name: &str) -> Result<(), DockerError> {
    let ws_port_env = format!("WS_PORT={}", port);
    let agent_name_env = format!("AGENT_NAME={}", agent_name);
    let port_label = format!("vesta.ws_port={}", port);
    let user_label = format!("{}={}", LABEL_USER, current_user());
    let mut args = vec![
        "create", "--name", cname, "-it",
        "--restart", "unless-stopped", "--network", "host",
        "--label", "vesta.managed=true",
        "--label", &port_label,
        "--label", &user_label,
        "-e", &ws_port_env,
        "-e", &agent_name_env,
        "-e", "IS_SANDBOX=1",
    ];

    match gpu_available() {
        GpuStatus::Ready => {
            args.extend(["--gpus", "all"]);
            tracing::info!("GPU detected, enabling passthrough");
        }
        GpuStatus::NoRuntime => {
            tracing::warn!("NVIDIA GPU detected but nvidia-container-toolkit is not installed. Install it to enable GPU passthrough: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html");
        }
        GpuStatus::NoGpu => {}
    }

    args.push(image);
    args.extend(ENTRYPOINT);
    if !docker_ok(&args) {
        return Err(DockerError::Failed("failed to create container".into()));
    }
    Ok(())
}

// --- Credential injection ---

fn docker_cp_content(container: &str, content: &str, dest: &str) -> Result<(), DockerError> {
    let tmp = std::env::temp_dir().join(format!("vesta_{}", std::process::id()));
    std::fs::write(&tmp, content)
        .map_err(|e| DockerError::Failed(format!("failed to write temp file: {}", e)))?;
    let target = format!("{}:{}", container, dest);
    let ok = docker_ok(&["cp", tmp.to_str().unwrap(), &target]);
    std::fs::remove_file(&tmp).ok();
    if !ok {
        return Err(DockerError::Failed(format!("failed to copy to {}", dest)));
    }
    Ok(())
}

pub fn inject_credentials(container: &str, credentials: &str) -> Result<(), DockerError> {
    let tmp_dir = std::env::temp_dir().join(format!("vesta_claude_{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir)
        .map_err(|e| DockerError::Failed(format!("failed to create temp dir: {}", e)))?;
    std::fs::write(tmp_dir.join(".credentials.json"), credentials)
        .map_err(|e| DockerError::Failed(format!("failed to write temp credentials: {}", e)))?;
    let src = format!("{}/.", tmp_dir.to_str().unwrap());
    let target = format!("{}:/root/.claude/", container);
    let ok = docker_ok(&["cp", &src, &target]);
    std::fs::remove_dir_all(&tmp_dir).ok();
    if !ok {
        return Err(DockerError::Failed("failed to copy credentials to container".into()));
    }
    docker_cp_content(container, "{\"hasCompletedOnboarding\":true}", CLAUDE_JSON_PATH)?;
    Ok(())
}

// --- Auth flow (split for HTTP API) ---

fn urlencod(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 3);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                out.push('%');
                out.push(char::from(b"0123456789ABCDEF"[(b >> 4) as usize]));
                out.push(char::from(b"0123456789ABCDEF"[(b & 0xf) as usize]));
            }
        }
    }
    out
}

fn base64url_encode(data: &[u8]) -> String {
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::with_capacity((data.len() * 4).div_ceil(3));
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as usize;
        let b1 = if chunk.len() > 1 { chunk[1] as usize } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as usize } else { 0 };
        out.push(CHARS[b0 >> 2] as char);
        out.push(CHARS[((b0 & 3) << 4) | (b1 >> 4)] as char);
        if chunk.len() > 1 {
            out.push(CHARS[((b1 & 0xf) << 2) | (b2 >> 6)] as char);
        }
        if chunk.len() > 2 {
            out.push(CHARS[b2 & 0x3f] as char);
        }
    }
    out
}

use ring::rand::SecureRandom;

fn generate_pkce() -> (String, String) {
    let rng = ring::rand::SystemRandom::new();
    let mut verifier_bytes = [0u8; 32];
    rng.fill(&mut verifier_bytes).expect("random failed");
    let verifier = base64url_encode(&verifier_bytes);

    let challenge_hash = ring::digest::digest(&ring::digest::SHA256, verifier.as_bytes());
    let challenge = base64url_encode(challenge_hash.as_ref());

    (verifier, challenge)
}

fn generate_state() -> String {
    let rng = ring::rand::SystemRandom::new();
    let mut state_bytes = [0u8; 32];
    rng.fill(&mut state_bytes).expect("random failed");
    base64url_encode(&state_bytes)
}

/// Start the OAuth PKCE flow. Returns (auth_url, session_id, code_verifier, state).
pub fn start_auth_flow() -> (String, String, String) {
    let (code_verifier, code_challenge) = generate_pkce();
    let state = generate_state();

    let auth_url = format!(
        "{}?code=true&client_id={}&redirect_uri={}&response_type=code&scope={}&code_challenge={}&code_challenge_method=S256&state={}",
        OAUTH_AUTHORIZE_URL,
        OAUTH_CLIENT_ID,
        urlencod(OAUTH_REDIRECT_URI),
        urlencod("org:create_api_key user:profile user:inference"),
        code_challenge,
        state,
    );

    (auth_url, code_verifier, state)
}

/// Complete the OAuth flow by exchanging the auth code for tokens.
/// Returns the credentials JSON string.
pub fn complete_auth_flow(input: &str, code_verifier: &str, expected_state: &str) -> Result<String, DockerError> {
    let (auth_code, pasted_state) = match input.split_once('#') {
        Some((code, st)) => (code, st),
        None => (input, expected_state),
    };

    let body = format!(
        r#"{{"grant_type":"authorization_code","code":"{}","client_id":"{}","redirect_uri":"{}","code_verifier":"{}","state":"{}"}}"#,
        auth_code, OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI, code_verifier, pasted_state,
    );

    let response = process::Command::new("curl")
        .args([
            "-s", "-X", "POST", OAUTH_TOKEN_URL,
            "-H", "Content-Type: application/json",
            "-d", &body,
        ])
        .output()
        .map_err(|_| DockerError::Failed("curl not found".into()))?;

    let response_str = String::from_utf8_lossy(&response.stdout);
    let token_data: serde_json::Value = serde_json::from_str(&response_str)
        .map_err(|_| DockerError::Failed(format!("token exchange failed: {}", response_str)))?;

    if let Some(error) = token_data.get("error") {
        return Err(DockerError::Failed(format!(
            "auth failed: {} — {}",
            error,
            token_data
                .get("error_description")
                .unwrap_or(error)
        )));
    }

    let access_token = token_data["access_token"]
        .as_str()
        .ok_or(DockerError::Failed("no access_token in response".into()))?;
    let refresh_token = token_data.get("refresh_token").and_then(|v| v.as_str());
    let expires_in = token_data["expires_in"].as_u64().unwrap_or(DEFAULT_TOKEN_EXPIRES_SECS);

    let expires_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()
        + (expires_in as u128) * 1000;

    let mut creds = serde_json::json!({
        "claudeAiOauth": {
            "accessToken": access_token,
            "expiresAt": expires_at as u64,
        }
    });
    if let Some(rt) = refresh_token {
        creds["claudeAiOauth"]["refreshToken"] = serde_json::json!(rt);
    }
    if let Some(scopes) = token_data.get("scope").and_then(|v| v.as_str()) {
        let scope_list: Vec<&str> = scopes.split_whitespace().collect();
        creds["claudeAiOauth"]["scopes"] = serde_json::json!(scope_list);
    }

    Ok(creds.to_string())
}

// --- Status helpers ---

pub fn status_label(cs: &ContainerStatus) -> &'static str {
    match cs {
        ContainerStatus::Running => "running",
        ContainerStatus::Dead => "dead",
        ContainerStatus::NotFound => "not_found",
        ContainerStatus::Stopped => "stopped",
    }
}

pub fn friendly_status(
    status: &ContainerStatus,
    authenticated: bool,
    agent_ready: bool,
) -> &'static str {
    match status {
        ContainerStatus::Running if !authenticated => "not signed in",
        ContainerStatus::Running if agent_ready => "alive",
        ContainerStatus::Running => "starting...",
        ContainerStatus::Dead => "broken",
        ContainerStatus::Stopped => "stopped",
        ContainerStatus::NotFound => "not found",
    }
}

// --- High-level operations (used by serve.rs handlers) ---

pub fn get_status(name: &str) -> Result<StatusJson, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(&cname);
    let derived = compute_agent_state(&cname, &info);

    Ok(StatusJson {
        name: name.to_string(),
        status: status_label(&info.status),
        id: info.id,
        authenticated: derived.authenticated,
        agent_ready: derived.agent_ready,
        ws_port: info.port,
        alive: derived.alive,
        friendly_status: derived.friendly_status,
    })
}

pub fn list_agents() -> Vec<ListEntry> {
    let containers = list_managed_containers();
    containers
        .iter()
        .map(|cname| {
            let info = inspect_container(cname);
            let derived = compute_agent_state(cname, &info);
            ListEntry {
                name: name_from_cname(cname),
                status: status_label(&info.status),
                authenticated: derived.authenticated,
                agent_ready: derived.agent_ready,
                ws_port: info.port,
                alive: derived.alive,
                friendly_status: derived.friendly_status,
            }
        })
        .collect()
}

pub fn create_agent(name: &str, build: bool) -> Result<String, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);

    if container_status(&cname) != ContainerStatus::NotFound {
        return Err(DockerError::AlreadyExists(format!("agent '{}' already exists", name)));
    }

    let image = resolve_image(build)?;
    let port = allocate_port();
    create_container(&cname, image, port, name)?;
    Ok(name.to_string())
}

pub fn start_agent(name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(&cname);
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        ContainerStatus::Running => return Ok(()),
        ContainerStatus::Stopped => {}
    }
    if !docker_ok(&["start", &cname]) {
        return Err(DockerError::Failed(format!("failed to start '{}'", name)));
    }
    Ok(())
}

#[derive(Serialize)]
pub struct StartAllResult {
    pub name: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

pub fn start_all_agents() -> Vec<StartAllResult> {
    let containers = list_managed_containers();
    let mut results = Vec::new();
    for cname in &containers {
        let name = name_from_cname(cname);
        if container_status(cname) != ContainerStatus::Running {
            if docker_ok(&["start", cname]) {
                results.push(StartAllResult { name, ok: true, error: None });
            } else {
                results.push(StartAllResult {
                    name,
                    ok: false,
                    error: Some("failed to start".into()),
                });
            }
        } else {
            results.push(StartAllResult { name, ok: true, error: None });
        }
    }
    results
}

pub fn stop_agent(name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(&cname);
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        ContainerStatus::Stopped => return Ok(()),
        ContainerStatus::Running => {}
    }
    if !docker_ok(&["stop", &cname]) {
        return Err(DockerError::Failed("failed to stop".into()));
    }
    Ok(())
}

pub fn restart_agent(name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    ensure_exists(&cname)?;
    if !docker_ok(&["restart", &cname]) {
        return Err(DockerError::Failed("failed to restart".into()));
    }
    Ok(())
}

pub fn destroy_agent(name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(&cname);
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        ContainerStatus::Running => { docker_ok(&["stop", &cname]); }
        ContainerStatus::Stopped => {}
    }
    if !docker_ok(&["rm", "-f", &cname]) {
        return Err(DockerError::Failed("failed to destroy".into()));
    }
    Ok(())
}

pub fn rebuild_agent(name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(&cname);
    match info.status {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        _ => {}
    }
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let backup_tag = format!("vesta-rebuild:{}_{}", name, ts);

    // Ensure base image layers are present so commit succeeds
    docker_ok(&["pull", VESTA_IMAGE]);

    if !docker_ok(&["commit", &cname, &backup_tag]) {
        return Err(DockerError::Failed("backup failed".into()));
    }

    docker_ok(&["rm", "-f", &cname]);

    create_container(&cname, &backup_tag, info.port, name)?;

    if !docker_ok(&["start", &cname]) {
        return Err(DockerError::Failed("failed to start".into()));
    }
    docker_ok(&["rmi", &backup_tag]);
    Ok(())
}

pub async fn wait_ready_async(name: &str, timeout_secs: u64) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let port = {
        let cname = cname.clone();
        tokio::task::spawn_blocking(move || {
            ensure_running(&cname)?;
            Ok::<_, DockerError>(get_container_port(&cname))
        })
        .await
        .unwrap()?
    };
    let addr = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let deadline = tokio::time::Instant::now() + tokio::time::Duration::from_secs(timeout_secs);
    loop {
        if tokio::net::TcpStream::connect(addr).await.is_ok() {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(DockerError::Failed(format!(
                "{name}: not ready after {timeout_secs}s"
            )));
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(WAIT_READY_POLL_MS)).await;
    }
}

// ── Backup operations ──────────────────────────────────────────

const BACKUP_IMAGE_PREFIX: &str = "vesta-backup";
const RETENTION_DAILY: usize = 3;
const RETENTION_WEEKLY: usize = 2;
const RETENTION_MONTHLY: usize = 1;
const MIN_DISK_SPACE_BYTES: u64 = 1_000_000_000; // 1 GB

/// Check that Docker's data root has enough free disk space for a backup.
fn check_disk_space() -> Result<(), DockerError> {
    let root = docker_output(&["info", "--format", "{{.DockerRootDir}}"])
        .unwrap_or_else(|| "/var/lib/docker".to_string());

    let stat = nix::sys::statvfs::statvfs(root.as_str())
        .map_err(|e| DockerError::Failed(format!("failed to check disk space: {}", e)))?;

    let available = stat.blocks_available() * stat.fragment_size();
    if available < MIN_DISK_SPACE_BYTES {
        let avail_mb = available / 1_000_000;
        return Err(DockerError::Failed(format!(
            "insufficient disk space for backup ({}MB available, need at least 1GB)",
            avail_mb
        )));
    }
    Ok(())
}

/// Build a backup image tag from components.
pub fn backup_tag(agent_name: &str, backup_type: &BackupType, timestamp: &str) -> String {
    format!("{}:{}-{}-{}", BACKUP_IMAGE_PREFIX, agent_name, backup_type, timestamp)
}

/// Parse a backup image tag into (agent_name, backup_type, timestamp).
/// Returns None if the tag doesn't match the expected format.
pub fn parse_backup_tag(tag: &str) -> Option<(String, BackupType, String)> {
    let repo_tag = tag.strip_prefix(&format!("{}:", BACKUP_IMAGE_PREFIX))?;
    // Format: {agent_name}-{type}-{YYYYMMDD-HHMMSS}
    // The timestamp is always YYYYMMDD-HHMMSS (15 chars), type is before that.
    // We need to find the type by scanning from the right since agent names can contain hyphens.
    // Timestamp: YYYYMMDD-HHMMSS = 15 chars
    if repo_tag.len() < 17 {
        return None; // minimum: "a-x-YYYYMMDD-HHMMSS"
    }
    let timestamp = &repo_tag[repo_tag.len() - 15..];
    // Validate timestamp format: YYYYMMDD-HHMMSS
    if timestamp.len() != 15 || timestamp.as_bytes()[8] != b'-' {
        return None;
    }
    // Everything before the timestamp (minus trailing hyphen) is "name-type"
    let name_and_type = &repo_tag[..repo_tag.len() - 16]; // -16 for hyphen + timestamp

    // Try each backup type suffix (longest first to avoid ambiguity)
    for (suffix, bt) in [
        ("-pre-restore", BackupType::PreRestore),
        ("-manual", BackupType::Manual),
        ("-daily", BackupType::Daily),
        ("-weekly", BackupType::Weekly),
        ("-monthly", BackupType::Monthly),
    ] {
        if let Some(name) = name_and_type.strip_suffix(suffix) {
            if !name.is_empty() {
                return Some((name.to_string(), bt, timestamp.to_string()));
            }
        }
    }
    None
}

pub fn now_timestamp() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    now_timestamp_from_epoch(now)
}

pub fn now_timestamp_from_epoch(now: u64) -> String {
    // Convert to YYYYMMDD-HHMMSS using simple arithmetic (UTC)
    let secs_per_day = 86400u64;
    let days = now / secs_per_day;
    let time_of_day = now % secs_per_day;
    let hours = time_of_day / 3600;
    let minutes = (time_of_day % 3600) / 60;
    let seconds = time_of_day % 60;

    // Days since epoch to Y/M/D
    let mut y = 1970i64;
    let mut remaining = days as i64;
    loop {
        let days_in_year = if y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) { 366 } else { 365 };
        if remaining < days_in_year {
            break;
        }
        remaining -= days_in_year;
        y += 1;
    }
    let leap = y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    let month_days = [31, if leap { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let mut m = 0usize;
    for (i, &md) in month_days.iter().enumerate() {
        if remaining < md as i64 {
            m = i;
            break;
        }
        remaining -= md as i64;
    }
    let d = remaining + 1;

    format!("{:04}{:02}{:02}-{:02}{:02}{:02}", y, m + 1, d, hours, minutes, seconds)
}

/// Commit the container to a backup image without managing container lifecycle.
/// Caller is responsible for stopping/starting the container.
fn commit_backup(cname: &str, name: &str, backup_type: &BackupType) -> Result<BackupInfo, DockerError> {
    let ts = now_timestamp();
    let tag = backup_tag(name, backup_type, &ts);
    let name_label = format!("LABEL vesta.agent_name={}", name);
    let type_label = format!("LABEL vesta.backup_type={}", backup_type);
    let date_label = format!("LABEL vesta.backup_date={}", ts);

    if !docker_ok(&[
        "commit",
        "--change", &name_label,
        "--change", &type_label,
        "--change", &date_label,
        cname, &tag,
    ]) {
        return Err(DockerError::Failed("backup commit failed".into()));
    }

    let size = docker_output(&["inspect", "--format", "{{.Size}}", &tag])
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);

    Ok(BackupInfo {
        id: tag,
        agent_name: name.to_string(),
        backup_type: backup_type.clone(),
        created_at: ts,
        size,
    })
}

/// Create a backup of the given agent. Stops the container during commit, then restarts.
pub fn create_backup(name: &str, backup_type: BackupType) -> Result<BackupInfo, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(&cname);
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        _ => {}
    }

    check_disk_space()?;

    tracing::debug!(agent = %name, backup_type = %backup_type, "starting backup");
    let was_running = cs == ContainerStatus::Running;
    if was_running {
        docker_ok(&["stop", &cname]);
    }

    let result = commit_backup(&cname, name, &backup_type);

    if was_running {
        docker_ok(&["start", &cname]);
    }

    match &result {
        Ok(info) => tracing::debug!(agent = %name, backup_id = %info.id, size = info.size, "backup committed"),
        Err(e) => tracing::error!(agent = %name, error = %e, "backup commit failed"),
    }

    result
}

/// List all backups for the given agent, sorted by date descending.
pub fn list_backups(name: &str) -> Result<Vec<BackupInfo>, DockerError> {
    validate_name(name)?;
    // Ensure agent exists
    let cname = container_name(name);
    if container_status(&cname) == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!("agent '{}' not found", name)));
    }

    let output = docker_output(&[
        "images",
        "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}",
        "--filter", &format!("reference={}:{}-*", BACKUP_IMAGE_PREFIX, name),
    ])
    .unwrap_or_default();

    let mut backups: Vec<BackupInfo> = output
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|line| {
            let mut parts = line.splitn(2, '\t');
            let tag = parts.next()?.trim();
            let size_str = parts.next().unwrap_or("0").trim();
            let (parsed_name, backup_type, timestamp) = parse_backup_tag(tag)?;
            if parsed_name != name {
                return None;
            }
            Some(BackupInfo {
                id: tag.to_string(),
                agent_name: parsed_name,
                backup_type,
                created_at: timestamp,
                size: parse_docker_size(size_str),
            })
        })
        .collect();

    backups.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    Ok(backups)
}

/// Parse Docker's human-readable size strings like "1.5GB", "300MB", "15kB".
fn parse_docker_size(s: &str) -> u64 {
    let s = s.trim();
    let (num_str, multiplier) = if let Some(n) = s.strip_suffix("GB") {
        (n, 1_000_000_000u64)
    } else if let Some(n) = s.strip_suffix("MB") {
        (n, 1_000_000u64)
    } else if let Some(n) = s.strip_suffix("kB") {
        (n, 1_000u64)
    } else if let Some(n) = s.strip_suffix('B') {
        (n, 1u64)
    } else {
        (s, 1u64)
    };
    num_str
        .trim()
        .parse::<f64>()
        .map(|n| (n * multiplier as f64) as u64)
        .unwrap_or(0)
}

/// Restore an agent from a backup image.
/// Creates a pre-restore safety backup first, then replaces the container.
pub fn restore_backup(name: &str, backup_id: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);

    if docker_output(&["inspect", "--format", "{{.Id}}", backup_id]).is_none() {
        return Err(DockerError::NotFound(format!("backup '{}' not found", backup_id)));
    }

    let info = inspect_container(&cname);
    if info.status == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!("agent '{}' not found", name)));
    }

    // Stop once, commit safety backup, then remove — avoids a redundant stop/start cycle
    if info.status == ContainerStatus::Running {
        docker_ok(&["stop", &cname]);
    }
    tracing::info!(agent = %name, "creating pre-restore safety backup");
    commit_backup(&cname, name, &BackupType::PreRestore)?;
    docker_ok(&["rm", "-f", &cname]);

    // Create new container from backup image, reusing the port
    tracing::debug!(agent = %name, backup_id = %backup_id, "creating container from backup image");
    create_container(&cname, backup_id, info.port, name)?;

    if !docker_ok(&["start", &cname]) {
        return Err(DockerError::Failed("failed to start restored agent".into()));
    }

    Ok(())
}

/// Delete a backup image.
pub fn delete_backup(backup_id: &str) -> Result<(), DockerError> {
    // Verify it's actually a backup image
    if parse_backup_tag(backup_id).is_none() {
        return Err(DockerError::Failed(format!("'{}' is not a valid backup tag", backup_id)));
    }
    if !docker_ok(&["rmi", backup_id]) {
        return Err(DockerError::Failed(format!("failed to delete backup '{}'", backup_id)));
    }
    Ok(())
}

/// Determine which auto-backups should be deleted based on the retention policy.
/// Returns the IDs of backups to delete.
pub fn compute_backups_to_delete(backups: &[BackupInfo]) -> Vec<String> {
    let mut to_delete = Vec::new();

    for (backup_type, retention) in [
        (BackupType::Daily, RETENTION_DAILY),
        (BackupType::Weekly, RETENTION_WEEKLY),
        (BackupType::Monthly, RETENTION_MONTHLY),
    ] {
        let mut typed: Vec<&BackupInfo> = backups
            .iter()
            .filter(|b| b.backup_type == backup_type)
            .collect();
        // Sort by date descending (newest first)
        typed.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        // Mark excess for deletion
        for excess in typed.into_iter().skip(retention) {
            to_delete.push(excess.id.clone());
        }
    }

    to_delete
}

/// Run retention cleanup for an agent's auto-backups.
/// Pass existing backups list to avoid a redundant `docker images` call.
pub fn cleanup_backups(backups: &[BackupInfo]) {
    let to_delete = compute_backups_to_delete(backups);
    if to_delete.is_empty() {
        return;
    }
    tracing::info!(count = to_delete.len(), "cleaning up old backups");
    for id in &to_delete {
        if docker_ok(&["rmi", id]) {
            tracing::debug!(backup_id = %id, "deleted expired backup");
        } else {
            tracing::warn!(backup_id = %id, "failed to delete expired backup");
        }
    }
}

/// List all agent names that have containers.
pub fn list_agent_names() -> Vec<String> {
    list_managed_containers()
        .iter()
        .map(|cname| name_from_cname(cname))
        .collect()
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_simple() {
        assert_eq!(normalize_name("MyAgent"), "myagent");
    }

    #[test]
    fn normalize_spaces_and_underscores() {
        assert_eq!(normalize_name("My Agent_Name"), "my-agent-name");
    }

    #[test]
    fn normalize_special_chars() {
        assert_eq!(normalize_name("hello!@#world"), "helloworld");
    }

    #[test]
    fn normalize_leading_trailing_hyphens() {
        assert_eq!(normalize_name("--test--"), "test");
    }

    #[test]
    fn normalize_multiple_hyphens() {
        assert_eq!(normalize_name("a---b"), "a-b");
    }

    #[test]
    fn normalize_whitespace() {
        assert_eq!(normalize_name("  hello  "), "hello");
    }

    #[test]
    fn normalize_empty() {
        assert_eq!(normalize_name(""), "");
    }

    #[test]
    fn normalize_all_special() {
        assert_eq!(normalize_name("!!!"), "");
    }

    #[test]
    fn normalize_truncates_long_name() {
        let long = "a".repeat(50);
        let result = normalize_name(&long);
        assert_eq!(result.len(), 32);
    }

    #[test]
    fn normalize_truncate_strips_trailing_hyphen() {
        let input = format!("{}--b", "a".repeat(31));
        let result = normalize_name(&input);
        assert!(!result.ends_with('-'));
        assert!(result.len() <= 32);
    }

    #[test]
    fn validate_ok() {
        assert!(validate_name("hello").is_ok());
        assert!(validate_name("a").is_ok());
        assert!(validate_name("test-agent").is_ok());
        assert!(validate_name("a1").is_ok());
        assert!(validate_name("123").is_ok());
    }

    #[test]
    fn validate_rejects_empty() {
        assert!(validate_name("").is_err());
    }

    #[test]
    fn validate_rejects_uppercase() {
        assert!(validate_name("Hello").is_err());
    }

    #[test]
    fn validate_rejects_leading_hyphen() {
        assert!(validate_name("-hello").is_err());
    }

    #[test]
    fn validate_rejects_trailing_hyphen() {
        assert!(validate_name("hello-").is_err());
    }

    #[test]
    fn validate_rejects_too_long() {
        let long = "a".repeat(33);
        assert!(validate_name(&long).is_err());
    }

    #[test]
    fn validate_rejects_special_chars() {
        assert!(validate_name("hello world").is_err());
        assert!(validate_name("hello_world").is_err());
    }

    #[test]
    fn container_name_roundtrip() {
        assert_eq!(name_from_cname(&container_name("test")), "test");
        assert_eq!(name_from_cname(&container_name("my-agent")), "my-agent");
    }

    // ── Backup tag tests ──────────────────────────────────────────

    #[test]
    fn backup_tag_generation() {
        let tag = backup_tag("myagent", &BackupType::Manual, "20260404-120000");
        assert_eq!(tag, "vesta-backup:myagent-manual-20260404-120000");
    }

    #[test]
    fn backup_tag_generation_pre_restore() {
        let tag = backup_tag("myagent", &BackupType::PreRestore, "20260404-120000");
        assert_eq!(tag, "vesta-backup:myagent-pre-restore-20260404-120000");
    }

    #[test]
    fn parse_backup_tag_manual() {
        let (name, bt, ts) = parse_backup_tag("vesta-backup:myagent-manual-20260404-120000").unwrap();
        assert_eq!(name, "myagent");
        assert_eq!(bt, BackupType::Manual);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_pre_restore() {
        let (name, bt, ts) = parse_backup_tag("vesta-backup:myagent-pre-restore-20260404-120000").unwrap();
        assert_eq!(name, "myagent");
        assert_eq!(bt, BackupType::PreRestore);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_with_hyphenated_name() {
        let (name, bt, ts) = parse_backup_tag("vesta-backup:my-cool-agent-daily-20260404-120000").unwrap();
        assert_eq!(name, "my-cool-agent");
        assert_eq!(bt, BackupType::Daily);
        assert_eq!(ts, "20260404-120000");
    }

    #[test]
    fn parse_backup_tag_roundtrip() {
        let original_tag = backup_tag("test-agent", &BackupType::Weekly, "20260101-235959");
        let (name, bt, ts) = parse_backup_tag(&original_tag).unwrap();
        assert_eq!(name, "test-agent");
        assert_eq!(bt, BackupType::Weekly);
        assert_eq!(ts, "20260101-235959");
    }

    #[test]
    fn parse_backup_tag_invalid() {
        assert!(parse_backup_tag("not-a-backup:tag").is_none());
        assert!(parse_backup_tag("vesta-backup:").is_none());
        assert!(parse_backup_tag("vesta-backup:short").is_none());
    }

    #[test]
    fn parse_backup_tag_all_types() {
        for type_str in ["manual", "daily", "weekly", "monthly", "pre-restore"] {
            let bt: BackupType = type_str.parse().unwrap();
            let tag = backup_tag("agent", &bt, "20260404-120000");
            let (name, parsed_bt, _) = parse_backup_tag(&tag).unwrap();
            assert_eq!(name, "agent");
            assert_eq!(parsed_bt, bt);
        }
    }

    // ── Retention policy tests ────────────────────────────────────

    fn make_backup(agent: &str, bt: BackupType, ts: &str) -> BackupInfo {
        BackupInfo {
            id: backup_tag(agent, &bt, ts),
            agent_name: agent.to_string(),
            backup_type: bt,
            created_at: ts.to_string(),
            size: 1000,
        }
    }

    #[test]
    fn retention_empty_list() {
        let to_delete = compute_backups_to_delete(&[]);
        assert!(to_delete.is_empty());
    }

    #[test]
    fn retention_under_limit() {
        let backups = vec![
            make_backup("a", BackupType::Daily, "20260401-120000"),
            make_backup("a", BackupType::Daily, "20260402-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups);
        assert!(to_delete.is_empty());
    }

    #[test]
    fn retention_daily_over_limit() {
        let backups = vec![
            make_backup("a", BackupType::Daily, "20260401-120000"),
            make_backup("a", BackupType::Daily, "20260402-120000"),
            make_backup("a", BackupType::Daily, "20260403-120000"),
            make_backup("a", BackupType::Daily, "20260404-120000"),
            make_backup("a", BackupType::Daily, "20260405-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups);
        assert_eq!(to_delete.len(), 2);
        // Oldest two should be deleted
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Daily, "20260401-120000")));
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Daily, "20260402-120000")));
    }

    #[test]
    fn retention_weekly_over_limit() {
        let backups = vec![
            make_backup("a", BackupType::Weekly, "20260301-120000"),
            make_backup("a", BackupType::Weekly, "20260308-120000"),
            make_backup("a", BackupType::Weekly, "20260315-120000"),
            make_backup("a", BackupType::Weekly, "20260322-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups);
        assert_eq!(to_delete.len(), 2);
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Weekly, "20260301-120000")));
        assert!(to_delete.contains(&backup_tag("a", &BackupType::Weekly, "20260308-120000")));
    }

    #[test]
    fn retention_monthly_over_limit() {
        let backups = vec![
            make_backup("a", BackupType::Monthly, "20260101-120000"),
            make_backup("a", BackupType::Monthly, "20260201-120000"),
            make_backup("a", BackupType::Monthly, "20260301-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups);
        assert_eq!(to_delete.len(), 2);
    }

    #[test]
    fn retention_mixed_types() {
        let backups = vec![
            make_backup("a", BackupType::Daily, "20260401-120000"),
            make_backup("a", BackupType::Daily, "20260402-120000"),
            make_backup("a", BackupType::Daily, "20260403-120000"),
            make_backup("a", BackupType::Weekly, "20260322-120000"),
            make_backup("a", BackupType::Weekly, "20260329-120000"),
            make_backup("a", BackupType::Monthly, "20260301-120000"),
            make_backup("a", BackupType::Manual, "20260404-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups);
        // 3 daily (keep all), 2 weekly (keep all), 1 monthly (keep all), manual not touched
        assert!(to_delete.is_empty());
    }

    #[test]
    fn retention_ignores_manual_and_pre_restore() {
        let backups = vec![
            make_backup("a", BackupType::Manual, "20260401-120000"),
            make_backup("a", BackupType::Manual, "20260402-120000"),
            make_backup("a", BackupType::Manual, "20260403-120000"),
            make_backup("a", BackupType::Manual, "20260404-120000"),
            make_backup("a", BackupType::PreRestore, "20260401-120000"),
            make_backup("a", BackupType::PreRestore, "20260402-120000"),
        ];
        let to_delete = compute_backups_to_delete(&backups);
        assert!(to_delete.is_empty());
    }

    // ── Docker size parsing ───────────────────────────────────────

    #[test]
    fn parse_docker_size_values() {
        assert_eq!(parse_docker_size("1.5GB"), 1_500_000_000);
        assert_eq!(parse_docker_size("300MB"), 300_000_000);
        assert_eq!(parse_docker_size("15kB"), 15_000);
        assert_eq!(parse_docker_size("1024B"), 1024);
        assert_eq!(parse_docker_size("0B"), 0);
    }

    #[test]
    fn name_from_cname_no_prefix() {
        assert_eq!(name_from_cname("random"), "random");
    }
}
