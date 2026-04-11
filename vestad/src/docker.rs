use serde::Serialize;
use std::collections::HashSet;
use std::process;

#[derive(Debug, Clone)]
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
pub const AGENT_READY_MARKER_PATH: &str = "/root/vesta/data/agent_ready";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";
const AGENT_TOKEN_BYTES: usize = 32;
const PORT_ALLOC_RETRIES: usize = 10;
const NAME_MAX_LEN: usize = 32;
const DOCKER_DAEMON_WAIT_RETRIES: usize = 10;
const AGENT_READY_TIMEOUT_MS: u64 = 200;
const WAIT_READY_POLL_MS: u64 = 500;
const DEFAULT_TOKEN_EXPIRES_SECS: u64 = 28800;
const LABEL_USER: &str = "vesta.user";
const LABEL_AGENT_NAME: &str = "vesta.agent_name";


pub const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
pub const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
pub const OAUTH_TOKEN_URL: &str = "https://api.anthropic.com/v1/oauth/token";
pub const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

// --- Expected container config (single source of truth) ---

const NETWORK_MODE: &str = "host";
const RESTART_POLICY: &str = "unless-stopped";
const MOUNT_DESTS: &[&str] = &["/run/vestad-env", "/root/vesta/src/vesta", "/root/vesta/pyproject.toml", "/root/vesta/uv.lock"];

/// Container entrypoint: source the bind-mounted env file (so vestad can inject
/// new vars without rebuilding images), then exec the agent.
const ENTRYPOINT: &[&str] = &[
    "sh", "-c",
    ". /run/vestad-env; . ~/.bashrc || true; exec uv run --frozen --project /root/vesta python -m vesta.main",
];

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

/// Read the agent name from the `vesta.agent_name` Docker label, falling back
/// to parsing the container name for legacy containers that lack the label.
pub fn get_agent_name(cname: &str) -> String {
    docker_output(&[
        "inspect",
        "--format",
        &format!("{{{{index .Config.Labels \"{}\"}}}}", LABEL_AGENT_NAME),
        cname,
    ])
    .filter(|s| !s.trim().is_empty() && s.trim() != "<no value>")
    .unwrap_or_else(|| name_from_cname(cname))
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
    tracing::debug!(cmd = %format!("docker {}", args.join(" ")), "running docker command");
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

/// Snapshot a container's filesystem as a new image using docker export | docker import.
/// Unlike docker commit, this doesn't depend on parent image layers.
/// Optional `changes` apply Dockerfile instructions (e.g. LABEL) to the imported image.
pub fn snapshot_container(cname: &str, tag: &str, changes: &[&str]) -> Result<(), DockerError> {
    let mut export_child = process::Command::new("docker")
        .args(["export", cname])
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::piped())
        .spawn()
        .map_err(|e| DockerError::Failed(format!("failed to start docker export: {e}")))?;

    let export_stdout = export_child.stdout.take()
        .ok_or_else(|| DockerError::Failed("docker export stdout not available".into()))?;

    let mut import_args = Vec::new();
    for change in changes {
        import_args.push("--change");
        import_args.push(change);
    }
    import_args.push("-");
    import_args.push(tag);

    let import_output = process::Command::new("docker")
        .args(["import"])
        .args(&import_args)
        .stdin(export_stdout)
        .output()
        .map_err(|e| DockerError::Failed(format!("failed to run docker import: {e}")))?;

    let export_status = export_child.wait()
        .map_err(|e| DockerError::Failed(format!("docker export wait failed: {e}")))?;

    if !export_status.success() {
        return Err(DockerError::Failed("docker export failed".into()));
    }
    if !import_output.status.success() {
        let stderr = String::from_utf8_lossy(&import_output.stderr);
        return Err(DockerError::Failed(format!("docker import failed: {stderr}")));
    }
    Ok(())
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

    if !docker_quiet(&["buildx", "version"]) {
        return Err(DockerError::Failed(
            "docker buildx is required but not installed. install it with your package manager:\n  \
             apt (docker.io):     sudo apt-get install docker-buildx\n  \
             apt (docker-ce):     sudo apt-get install docker-buildx-plugin\n  \
             dnf:                 sudo dnf install docker-buildx-plugin\n  \
             pacman:              sudo pacman -S docker-buildx\n  \
             brew:                brew install docker-buildx"
                .into(),
        ));
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
    pub port: Option<u16>,
    pub id: Option<String>,
    pub agent_name: Option<String>,
}

pub struct AgentDerivedState {
    pub authenticated: bool,
    pub agent_ready: bool,
    pub alive: bool,
    pub friendly_status: &'static str,
}

pub fn compute_agent_state(cname: &str, info: &ContainerInfo) -> AgentDerivedState {
    let authenticated = info.status != ContainerStatus::NotFound && is_authenticated(cname);
    let agent_ready = info.status == ContainerStatus::Running
        && info.port.is_some_and(|p| is_agent_ready(p, cname));
    let alive = info.status == ContainerStatus::Running && authenticated;
    let friendly_status = friendly_status(&info.status, authenticated, agent_ready);
    AgentDerivedState { authenticated, agent_ready, alive, friendly_status }
}

/// Read a value from a per-agent env file by key (e.g. "WS_PORT").
pub fn read_env_value(agents_dir: &std::path::Path, agent_name: &str, key: &str) -> Option<String> {
    let env_path = agents_dir.join(format!("{}.env", agent_name));
    let content = std::fs::read_to_string(&env_path).ok()?;
    let prefix = format!("{key}=");
    for line in content.lines() {
        let line = line.strip_prefix("export ").unwrap_or(line);
        if let Some(val) = line.strip_prefix(&prefix) {
            return Some(val.to_string());
        }
    }
    None
}

pub(crate) fn inspect_container(cname: &str, agents_dir: Option<&std::path::Path>) -> ContainerInfo {
    let format_str = format!(
        "{{{{.State.Status}}}}|{{{{.Id}}}}|{{{{index .Config.Labels \"{}\"}}}}",
        LABEL_AGENT_NAME
    );
    match docker_output(&[
        "inspect",
        "--format",
        &format_str,
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
            let id = parts
                .get(1)
                .map(|p| p.trim().chars().take(12).collect::<String>());
            let agent_name = parts
                .get(2)
                .map(|p| p.trim().to_string())
                .filter(|s| !s.is_empty() && s != "<no value>");
            let name = agent_name.clone().unwrap_or_else(|| name_from_cname(cname));
            let port = agents_dir.and_then(|dir| read_env_value(dir, &name, "WS_PORT"))
                .and_then(|v| v.parse().ok());
            ContainerInfo { status, port, id, agent_name }
        }
        None => ContainerInfo {
            status: ContainerStatus::NotFound,
            port: None,
            id: None,
            agent_name: None,
        },
    }
}

pub fn container_status(cname: &str) -> ContainerStatus {
    inspect_container(cname, None).status
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

pub fn is_agent_ready(port: u16, cname: &str) -> bool {
    let tcp_ok = std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(AGENT_READY_TIMEOUT_MS),
    )
    .is_ok();
    tcp_ok && read_container_file(cname, AGENT_READY_MARKER_PATH).is_some()
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

pub fn resolve_image() -> Result<&'static str, DockerError> {
    if let Ok(context) = find_dockerfile() {
        let status = process::Command::new("docker")
            .args(["buildx", "build", "-t", LOCAL_IMAGE_TAG, "."])
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

fn all_agent_ports(agents_dir: &std::path::Path) -> HashSet<u16> {
    env_file_names(agents_dir)
        .iter()
        .filter_map(|name| read_env_value(agents_dir, name, "WS_PORT")?.parse().ok())
        .collect()
}

/// List agent names that have env files in the agents directory.
fn env_file_names(agents_dir: &std::path::Path) -> Vec<String> {
    let Ok(entries) = std::fs::read_dir(agents_dir) else { return Vec::new() };
    entries
        .flatten()
        .filter_map(|entry| {
            if !entry.file_type().ok()?.is_file() {
                return None;
            }
            let name = entry.file_name().to_str()?.to_string();
            name.strip_suffix(".env").map(|s| s.to_string())
        })
        .collect()
}

pub fn allocate_port(agents_dir: &std::path::Path) -> Result<(u16, std::net::TcpListener), DockerError> {
    let reserved = all_agent_ports(agents_dir);
    for _ in 0..PORT_ALLOC_RETRIES {
        let listener = std::net::TcpListener::bind("127.0.0.1:0")
            .map_err(|e| DockerError::Failed(format!("failed to bind port: {e}")))?;
        let port = listener.local_addr()
            .map_err(|e| DockerError::Failed(format!("failed to get port: {e}")))?
            .port();
        if !reserved.contains(&port) {
            return Ok((port, listener));
        }
    }
    Err(DockerError::Failed("could not allocate a free port after retries".into()))
}

/// Read the agent's port and token from the per-agent env file in a single read.
pub fn read_agent_port_and_token(agent_name: &str, agents_dir: &std::path::Path) -> (Option<u16>, Option<String>) {
    let env_path = agents_dir.join(format!("{}.env", agent_name));
    let content = match std::fs::read_to_string(&env_path) {
        Ok(content) => content,
        Err(_) => return (None, None),
    };
    let mut port = None;
    let mut token = None;
    for line in content.lines() {
        let line = line.strip_prefix("export ").unwrap_or(line);
        if let Some(val) = line.strip_prefix("WS_PORT=") {
            port = val.parse().ok();
        } else if let Some(val) = line.strip_prefix("AGENT_TOKEN=") {
            token = Some(val.to_string());
        }
    }
    (port, token)
}

pub fn generate_agent_token() -> String {
    (0..AGENT_TOKEN_BYTES)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect()
}

// --- Per-agent env file ---

#[derive(Clone)]
pub struct AgentEnvConfig {
    pub config_dir: std::path::PathBuf,
    pub agents_dir: std::path::PathBuf,
    pub vestad_port: u16,
    pub vestad_tunnel: Option<String>,
}

/// Read an environment variable from a container's config (baked-in env vars).
pub fn read_container_env(cname: &str, key: &str) -> Option<String> {
    let envs = docker_output(&["inspect", "--format", "{{json .Config.Env}}", cname])?;
    let arr: Vec<String> = serde_json::from_str(&envs).ok()?;
    let prefix = format!("{}=", key);
    arr.iter()
        .find(|e| e.starts_with(&prefix))
        .map(|e| e[prefix.len()..].to_string())
}

/// Write a sourceable env file for a single agent. Returns the file path.
pub fn write_agent_env_file(
    env_config: &AgentEnvConfig,
    agent_name: &str,
    ws_port: u16,
    agent_token: &str,
) -> Result<std::path::PathBuf, DockerError> {
    std::fs::create_dir_all(&env_config.agents_dir)
        .map_err(|e| DockerError::Failed(format!("failed to create agents dir: {e}")))?;
    let env_path = env_config.agents_dir.join(format!("{}.env", agent_name));
    let mut content = format!(
        "export WS_PORT={ws_port}\n\
         export AGENT_NAME={agent_name}\n\
         export AGENT_TOKEN={agent_token}\n\
         export IS_SANDBOX=1\n\
         export VESTAD_PORT={}\n",
        env_config.vestad_port,
    );
    if let Some(url) = &env_config.vestad_tunnel {
        content.push_str(&format!("export VESTAD_TUNNEL={url}\n"));
    }
    std::fs::write(&env_path, &content)
        .map_err(|e| DockerError::Failed(format!("failed to write agent env file: {e}")))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&env_path, std::fs::Permissions::from_mode(0o600)).ok();
    }
    Ok(env_path)
}

fn delete_agent_env_file(agents_dir: &std::path::Path, agent_name: &str) {
    let env_path = agents_dir.join(format!("{}.env", agent_name));
    std::fs::remove_file(&env_path).ok();
}

/// Update VESTAD_PORT and VESTAD_TUNNEL in all existing per-agent env files.
/// Called at vestad startup so running containers pick up the new values on restart.
pub fn update_all_agent_env_files(agents_dir: &std::path::Path, vestad_port: u16, vestad_tunnel: Option<&str>) {
    for name in env_file_names(agents_dir) {
        let path = agents_dir.join(format!("{name}.env"));
        let Ok(content) = std::fs::read_to_string(&path) else { continue };
        let mut new_lines: Vec<String> = content
            .lines()
            .filter(|line| {
                let stripped = line.strip_prefix("export ").unwrap_or(line);
                !stripped.starts_with("VESTAD_PORT=") && !stripped.starts_with("VESTAD_TUNNEL=")
            })
            .map(|l| l.to_string())
            .collect();
        new_lines.push(format!("export VESTAD_PORT={vestad_port}"));
        if let Some(url) = vestad_tunnel {
            new_lines.push(format!("export VESTAD_TUNNEL={url}"));
        }
        new_lines.push(String::new());
        std::fs::write(&path, new_lines.join("\n")).ok();
    }
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

pub fn create_container(cname: &str, image: &str, port: u16, agent_name: &str, env_config: &AgentEnvConfig, manage_code: bool) -> Result<(), DockerError> {
    let agent_token = generate_agent_token();
    let env_path = write_agent_env_file(env_config, agent_name, port, &agent_token)?;
    let env_mount = format!("{}:{}:ro,z", env_path.display(), MOUNT_DESTS[0]);

    let code_dir = crate::agent_code::agent_code_dir(&env_config.config_dir);
    let src_mount = format!("{}:{}:ro,z", code_dir.join("src/vesta").display(), MOUNT_DESTS[1]);
    let pyproject_mount = format!("{}:{}:ro,z", code_dir.join("pyproject.toml").display(), MOUNT_DESTS[2]);
    let lock_mount = format!("{}:{}:ro,z", code_dir.join("uv.lock").display(), MOUNT_DESTS[3]);

    let user_label = format!("{}={}", LABEL_USER, current_user());
    let agent_name_label = format!("{}={}", LABEL_AGENT_NAME, agent_name);
    let mut args = vec![
        "create", "--name", cname, "-t",
        "--restart", RESTART_POLICY, "--network", NETWORK_MODE,
        "--label", "vesta.managed=true",
        "--label", &user_label,
        "--label", &agent_name_label,
        "-v", &env_mount,
    ];

    if manage_code {
        args.extend(["-v", &src_mount, "-v", &pyproject_mount, "-v", &lock_mount]);
    }

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

    tracing::info!(agent = %agent_name, manage_code, "creating container");
    args.push(image);
    args.extend(ENTRYPOINT);
    if !docker_ok(&args) {
        delete_agent_env_file(&env_config.agents_dir, agent_name);
        return Err(DockerError::Failed("failed to create container".into()));
    }
    Ok(())
}

// --- Credential injection ---

pub(crate) fn docker_cp_content(container: &str, content: &str, dest: &str) -> Result<(), DockerError> {
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

pub(crate) fn percent_encode(s: &str) -> String {
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
        percent_encode(OAUTH_REDIRECT_URI),
        percent_encode("org:create_api_key user:profile user:inference"),
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

pub fn get_status(name: &str, agents_dir: &std::path::Path) -> Result<StatusJson, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(&cname, Some(agents_dir));
    let derived = compute_agent_state(&cname, &info);

    Ok(StatusJson {
        name: name.to_string(),
        status: status_label(&info.status),
        id: info.id,
        authenticated: derived.authenticated,
        agent_ready: derived.agent_ready,
        ws_port: info.port.unwrap_or(0),
        alive: derived.alive,
        friendly_status: derived.friendly_status,
    })
}

pub fn list_agents(agents_dir: &std::path::Path) -> Vec<ListEntry> {
    let containers = list_managed_containers();
    containers
        .iter()
        .map(|cname| {
            let info = inspect_container(cname, Some(agents_dir));
            let derived = compute_agent_state(cname, &info);
            let name = info.agent_name.clone().unwrap_or_else(|| name_from_cname(cname));
            ListEntry {
                name,
                status: status_label(&info.status),
                authenticated: derived.authenticated,
                agent_ready: derived.agent_ready,
                ws_port: info.port.unwrap_or(0),
                alive: derived.alive,
                friendly_status: derived.friendly_status,
            }
        })
        .collect()
}

pub fn create_agent(name: &str, env_config: &AgentEnvConfig, manage_code: bool) -> Result<String, DockerError> {
    validate_name(name)?;
    if name.contains("vesta") {
        return Err(DockerError::InvalidName("agent name must not contain 'vesta'".into()));
    }
    let cname = container_name(name);

    if container_status(&cname) != ContainerStatus::NotFound {
        return Err(DockerError::AlreadyExists(format!("agent '{}' already exists", name)));
    }

    let image = resolve_image()?;

    if manage_code {
        crate::agent_code::ensure_agent_code(&env_config.config_dir)
            .map_err(|e| DockerError::Failed(format!("agent code: {e}")))?;
    }

    let (port, _listener) = allocate_port(&env_config.agents_dir)?;
    create_container(&cname, image, port, name, env_config, manage_code)?;
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
        let name = get_agent_name(cname);
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

/// Ensure all containers match expected config and running agents are restarted.
/// Called once at startup after agent code and env files are ready.
/// `manages_code` returns whether a given agent name has managed code (default true).
pub fn reconcile_containers(env_config: &AgentEnvConfig, manages_code: &dyn Fn(&str) -> bool) {
    let containers = list_managed_containers();
    if containers.is_empty() {
        return;
    }

    // Phase 1: ensure env files exist, track which are running
    let mut was_running = std::collections::HashSet::new();
    for cname in &containers {
        let name = get_agent_name(cname);
        if container_status(cname) == ContainerStatus::Running {
            was_running.insert(name.clone());
        }
        let env_path = env_config.agents_dir.join(format!("{name}.env"));
        if !env_path.is_file() {
            // Remove if it exists but isn't a file (e.g. stale directory)
            if env_path.exists() {
                std::fs::remove_dir_all(&env_path).ok();
            }
            let port = read_container_env(cname, "WS_PORT")
                .and_then(|v| v.parse::<u16>().ok())
                .or_else(|| allocate_port(&env_config.agents_dir).ok().map(|(p, _)| p));
            if let Some(port) = port {
                let token = generate_agent_token();
                if let Err(e) = write_agent_env_file(env_config, &name, port, &token) {
                    tracing::error!(agent = %name, error = %e, "failed to create missing env file");
                }
            } else {
                tracing::error!(agent = %name, "could not determine or allocate port for env file");
            }
        }
    }

    // Phase 2: rebuild containers with wrong config
    let mut agent_code_ok = false;
    for cname in &containers {
        let name = get_agent_name(cname);
        let manage_code = manages_code(&name);
        if !needs_rebuild(cname, manage_code) {
            continue;
        }
        if manage_code && !agent_code_ok {
            match crate::agent_code::ensure_agent_code(&env_config.config_dir) {
                Ok(_) => agent_code_ok = true,
                Err(e) => {
                    tracing::error!(error = %e, "failed to ensure agent code — skipping rebuilds");
                    break;
                }
            }
        }
        match rebuild_agent(&name, env_config, manage_code) {
            Ok(()) => tracing::info!(agent = %name, "rebuild complete"),
            Err(e) => tracing::error!(agent = %name, error = %e, "rebuild failed"),
        }
    }

    // Phase 3: restart running agents (picks up new env), start rebuilt ones
    for cname in &containers {
        let name = get_agent_name(cname);
        match container_status(cname) {
            ContainerStatus::Running => {
                tracing::info!(agent = %name, "restarting");
                docker_ok(&["restart", cname]);
            }
            ContainerStatus::Stopped if was_running.contains(&name) => {
                tracing::info!(agent = %name, "starting after rebuild");
                docker_ok(&["start", cname]);
            }
            _ => {}
        }
    }
}

pub fn destroy_agent(name: &str, agents_dir: &std::path::Path) -> Result<(), DockerError> {
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
    delete_agent_env_file(agents_dir, name);
    Ok(())
}

/// Check if a container's config diverges from what create_container would produce.
fn needs_rebuild(cname: &str, manage_code: bool) -> bool {
    // docker create puts args after the image into Cmd, not Entrypoint
    let fmt = "{{json .Mounts}}\\n{{json .Config.Cmd}}\\n{{.HostConfig.NetworkMode}}\\n{{.HostConfig.RestartPolicy.Name}}";
    let output = match docker_output(&["inspect", "--format", fmt, cname]) {
        Some(s) => s,
        None => return true,
    };

    let lines: Vec<&str> = output.lines().collect();
    let mounts = lines.first().unwrap_or(&"");
    let cmd_json = lines.get(1).unwrap_or(&"");
    let network = lines.get(2).map(|s| s.trim()).unwrap_or("");
    let restart = lines.get(3).map(|s| s.trim()).unwrap_or("");

    // env mount is always required; code mounts depend on manage_code
    let expected_mounts: &[&str] = if manage_code { MOUNT_DESTS } else { &MOUNT_DESTS[..1] };
    let missing: Vec<_> = expected_mounts.iter().filter(|d| !mounts.contains(**d)).collect();
    if !missing.is_empty() {
        tracing::info!(container = %cname, missing = ?missing, "rebuild needed: missing mounts");
        return true;
    }
    // If not managing code, code mounts should be absent
    if !manage_code {
        let unexpected: Vec<_> = MOUNT_DESTS[1..].iter().filter(|d| mounts.contains(**d)).collect();
        if !unexpected.is_empty() {
            tracing::info!(container = %cname, unexpected = ?unexpected, "rebuild needed: has code mounts but manage_agent_code=false");
            return true;
        }
    }

    let cmd_ok = serde_json::from_str::<Vec<String>>(cmd_json)
        .map(|actual| actual.iter().zip(ENTRYPOINT).all(|(a, e)| a == e) && actual.len() == ENTRYPOINT.len())
        .unwrap_or(false);
    if !cmd_ok {
        let expected: Vec<&str> = ENTRYPOINT.to_vec();
        tracing::info!(container = %cname, actual = %cmd_json, expected = ?expected, "rebuild needed: command mismatch");
        return true;
    }

    if network != NETWORK_MODE {
        tracing::info!(container = %cname, actual = network, expected = NETWORK_MODE, "rebuild needed: wrong network mode");
        return true;
    }

    if restart != RESTART_POLICY {
        tracing::info!(container = %cname, actual = restart, expected = RESTART_POLICY, "rebuild needed: wrong restart policy");
        return true;
    }

    false
}

/// Recreate a container with the latest container config (entrypoint, mounts, env file)
/// while preserving the filesystem. Commits the old container, removes it, and creates
/// a new one from the committed image.
pub fn rebuild_agent(name: &str, env_config: &AgentEnvConfig, manage_code: bool) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(&cname, Some(&env_config.agents_dir));
    match info.status {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        _ => {}
    }

    // Get port: try env file first, then container's baked-in env vars, then allocate new
    let port = match info.port
        .or_else(|| read_container_env(&cname, "WS_PORT").and_then(|v| v.parse().ok()))
    {
        Some(p) => p,
        None => {
            tracing::warn!(agent = %name, "no port found in env file or container — allocating new port");
            let (p, _listener) = allocate_port(&env_config.agents_dir)?;
            p
        }
    };

    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let backup_tag = format!("vesta-rebuild:{}_{}", name, ts);

    tracing::info!(agent = %name, "[1/3] snapshotting container filesystem...");
    snapshot_container(&cname, &backup_tag, &[])?;

    tracing::info!(agent = %name, "[2/3] removing old container...");
    docker_ok(&["rm", "-f", &cname]);

    tracing::info!(agent = %name, "[3/3] creating container with new config...");
    create_container(&cname, &backup_tag, port, name, env_config, manage_code)?;

    Ok(())
}

pub async fn wait_ready_async(name: &str, timeout_secs: u64, agents_dir: &std::path::Path) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let port = {
        let cname = cname.clone();
        let agents_dir = agents_dir.to_path_buf();
        let agent_name = name.to_string();
        tokio::task::spawn_blocking(move || {
            ensure_running(&cname)?;
            read_env_value(&agents_dir, &agent_name, "WS_PORT")
                .and_then(|v| v.parse().ok())
                .ok_or_else(|| DockerError::Failed("agent has no port".into()))
        })
        .await
        .unwrap()?
    };
    let deadline = tokio::time::Instant::now() + tokio::time::Duration::from_secs(timeout_secs);
    loop {
        let cname_check = cname.clone();
        let ready = tokio::task::spawn_blocking(move || is_agent_ready(port, &cname_check))
            .await
            .unwrap();
        if ready {
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
    fn validate_allows_vesta_in_name() {
        assert!(validate_name("vesta").is_ok());
        assert!(validate_name("my-vesta").is_ok());
        assert!(validate_name("vesta-agent").is_ok());
    }

    #[test]
    fn container_name_roundtrip() {
        assert_eq!(name_from_cname(&container_name("test")), "test");
        assert_eq!(name_from_cname(&container_name("my-agent")), "my-agent");
    }

    #[test]
    fn name_from_cname_no_prefix() {
        assert_eq!(name_from_cname("random"), "random");
    }

    #[test]
    fn agent_token_length() {
        let token = generate_agent_token();
        assert_eq!(token.len(), AGENT_TOKEN_BYTES * 2);
    }

    #[test]
    fn agent_tokens_are_unique() {
        let t1 = generate_agent_token();
        let t2 = generate_agent_token();
        assert_ne!(t1, t2);
    }
}
