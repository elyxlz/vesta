use bollard::container::{
    Config, CreateContainerOptions, ListContainersOptions,
    RemoveContainerOptions, StartContainerOptions, StopContainerOptions, UploadToContainerOptions,
};
use bollard::image::{
    BuildImageOptions, CreateImageOptions, ImportImageOptions,
    ListImagesOptions, RemoveImageOptions, TagImageOptions,
};
use bollard::Docker;
use futures_util::StreamExt;
use serde::Serialize;
use std::collections::HashMap;
use std::collections::HashSet;

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

impl From<bollard::errors::Error> for DockerError {
    fn from(e: bollard::errors::Error) -> Self {
        match &e {
            bollard::errors::Error::DockerResponseServerError { status_code, .. } => {
                match *status_code {
                    404 => DockerError::NotFound(e.to_string()),
                    409 => DockerError::AlreadyExists(e.to_string()),
                    _ => DockerError::Failed(e.to_string()),
                }
            }
            _ => DockerError::Failed(e.to_string()),
        }
    }
}

pub const VESTA_IMAGE: &str = "ghcr.io/elyxlz/vesta:latest";
pub const VESTA_LOG_PATH: &str = "/root/agent/logs/vesta.log";
pub const LOCAL_IMAGE_TAG: &str = "vesta:local";
const MAX_DOCKERFILE_SEARCH_DEPTH: usize = 5;
pub const CREDENTIALS_PATH: &str = "/root/.claude/.credentials.json";
pub const AGENT_READY_MARKER_PATH: &str = "/root/agent/data/agent_ready";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";
const AGENT_TOKEN_BYTES: usize = 32;
const PORT_ALLOC_RETRIES: usize = 10;
const NAME_MAX_LEN: usize = 32;
const DOCKER_DAEMON_PING_RETRIES: usize = 10;
const AGENT_READY_TIMEOUT_MS: u64 = 200;
const WAIT_READY_POLL_MS: u64 = 500;
const DEFAULT_TOKEN_EXPIRES_SECS: u64 = 28800;
const LABEL_USER: &str = "vesta.user";
const LABEL_AGENT_NAME: &str = "vesta.agent_name";

pub const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
pub const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
pub const OAUTH_TOKEN_URL: &str = "https://platform.claude.com/v1/oauth/token";
pub const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

// --- Expected container config (single source of truth) ---

const NETWORK_MODE: &str = "host";
const RESTART_POLICY: &str = "unless-stopped";
const MOUNT_DESTS: &[&str] = &["/run/vestad-env", "/root/agent/core", "/root/agent/pyproject.toml", "/root/agent/uv.lock"];

const AGENT_ENTRYPOINT_STEPS: &[&str] = &[
    "export PATH=\"/root/.local/bin:/root/.claude/local/bin:$PATH\"",
    ". /run/vestad-env",
    ". ~/.bashrc || true",
    "git -C ~ config user.name \"$AGENT_NAME\"",
    "git -C ~ config user.email \"$AGENT_NAME@vesta\"",
    "uv sync --frozen --project /root/agent",
    "git -C ~ rev-parse --verify \"$AGENT_NAME\" 2>/dev/null || git -C ~ checkout -b \"$AGENT_NAME\"",
    "mount | grep -q '/root/agent/core ' && git -C ~ update-index --skip-worktree agent/core agent/pyproject.toml agent/uv.lock 2>/dev/null || true",
    "cd /root/agent && exec uv run --frozen python -m core.main",
];

pub(crate) fn agent_container_entrypoint_cmd() -> Vec<String> {
    let script = AGENT_ENTRYPOINT_STEPS.join("; \\\n");
    vec!["sh".into(), "-c".into(), script]
}

const CONTAINER_STOP_TIMEOUT_SECS: i64 = 10;
const CONTAINER_RESTART_TIMEOUT_SECS: isize = 10;
const LOADED_IMAGE_PREFIX: &str = "Loaded image: ";

#[derive(Debug, PartialEq, Clone, Copy)]
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
    pub ws_port: u16,
}

#[derive(Serialize, Clone, PartialEq)]
pub struct ListEntry {
    pub name: String,
    pub status: &'static str,
    pub ws_port: u16,
}

// --- Docker connection ---

pub fn connect() -> Result<Docker, DockerError> {
    Docker::connect_with_local_defaults()
        .map_err(|e| DockerError::Failed(format!("failed to connect to docker: {e}")))
}

pub async fn ensure_docker(docker: &Docker) -> Result<(), DockerError> {
    // First attempt — check for permission errors
    match docker.ping().await {
        Ok(_) => {}
        Err(e) => {
            let msg = e.to_string().to_lowercase();
            if msg.contains("permission denied") {
                return Err(DockerError::Failed(
                    "docker permission denied. add your user to the docker group:\n  \
                     sudo usermod -aG docker $USER\n  \
                     then log out and back in (or run: newgrp docker)".to_string()
                ));
            }

            'retry: {
                for _ in 0..DOCKER_DAEMON_PING_RETRIES {
                    if docker.ping().await.is_ok() {
                        break 'retry;
                    }
                    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                }
                return Err(DockerError::Failed("docker daemon is not running. start it with: sudo systemctl start docker".into()));
            }
        }
    }

    Ok(())
}

pub fn ensure_docker_sync(docker: &Docker) -> Result<(), DockerError> {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| DockerError::Failed(format!("failed to create runtime: {e}")))?;
    rt.block_on(ensure_docker(docker))
}

// --- Pure / sync helpers ---

pub fn container_name(name: &str) -> String {
    format!("vesta-{}-{}", current_user(), name)
}

// Modern containers carry `vesta.agent_name`, so this fallback only exists for
// older managed containers that predate that label.
pub fn name_from_cname(cname: &str) -> String {
    crate::migrations::legacy_agent_name_from_container_name(cname, &current_user())
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

// --- Tar helpers ---

fn tar_single_file(file_name: &str, content: &[u8]) -> Result<Vec<u8>, DockerError> {
    let mut builder = tar::Builder::new(Vec::new());
    let mut header = tar::Header::new_gnu();
    header.set_path(file_name)
        .map_err(|e| DockerError::Failed(format!("tar header path: {e}")))?;
    header.set_size(content.len() as u64);
    header.set_mode(0o644);
    header.set_cksum();
    builder.append(&header, content)
        .map_err(|e| DockerError::Failed(format!("tar append: {e}")))?;
    builder.into_inner()
        .map_err(|e| DockerError::Failed(format!("tar finish: {e}")))
}

pub async fn upload_to_container(
    docker: &Docker,
    cname: &str,
    container_dir: &str,
    file_name: &str,
    content: &[u8],
) -> Result<(), DockerError> {
    let tar_data = tar_single_file(file_name, content)?;
    docker.upload_to_container(
        cname,
        Some(UploadToContainerOptions {
            path: container_dir.to_string(),
            ..Default::default()
        }),
        tar_data.into(),
    ).await?;
    Ok(())
}

pub async fn download_from_container(
    docker: &Docker,
    cname: &str,
    container_path: &str,
) -> Option<String> {
    let stream = docker.download_from_container(cname, Some(bollard::container::DownloadFromContainerOptions {
        path: container_path.to_string(),
    }));

    let mut bytes = Vec::new();
    let mut stream = std::pin::pin!(stream);
    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(data) => bytes.extend_from_slice(&data),
            Err(e) => {
                tracing::debug!(container = %cname, path = %container_path, error = %e, "download_from_container failed");
                return None;
            }
        }
    }

    let mut archive = tar::Archive::new(bytes.as_slice());
    let mut entries = archive.entries().ok()?;
    let entry = entries.next()?;
    let mut entry = entry.ok()?;
    let mut content = String::new();
    std::io::Read::read_to_string(&mut entry, &mut content).ok()?;
    let trimmed = content.trim().to_string();
    if trimmed.is_empty() { None } else { Some(trimmed) }
}

// --- Container query operations ---

pub struct ContainerInfo {
    pub status: ContainerStatus,
    pub port: Option<u16>,
    pub id: Option<String>,
    pub agent_name: Option<String>,
}

pub async fn combined_status(docker: &Docker, cname: &str, info: &ContainerInfo) -> &'static str {
    match info.status {
        ContainerStatus::Running => {
            let authenticated = is_authenticated(docker, cname).await;
            if !authenticated {
                return "not_authenticated";
            }
            let agent_ready = info.port.is_some_and(is_agent_ready_sync);
            if agent_ready { "alive" } else { "starting" }
        }
        ContainerStatus::Dead => "dead",
        ContainerStatus::Stopped => "stopped",
        ContainerStatus::NotFound => "not_found",
    }
}

/// Read the agent name from the `vesta.agent_name` Docker label. Older managed
/// containers may not have that label yet, so we fall back to the legacy
/// `vesta-{user}-{agent}` container naming scheme via migrations.rs.
pub async fn get_agent_name(docker: &Docker, cname: &str) -> String {
    match docker.inspect_container(cname, None).await {
        Ok(info) => {
            info.config
                .and_then(|c| c.labels)
                .and_then(|labels| labels.get(LABEL_AGENT_NAME).cloned())
                .filter(|s| !s.trim().is_empty())
                .unwrap_or_else(|| name_from_cname(cname))
        }
        Err(_) => name_from_cname(cname),
    }
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

pub(crate) async fn inspect_container(docker: &Docker, cname: &str, agents_dir: Option<&std::path::Path>) -> ContainerInfo {
    match docker.inspect_container(cname, None).await {
        Ok(info) => {
            let status = info.state.as_ref()
                .and_then(|s| s.status)
                .map(|s| {
                    let status_str = format!("{:?}", s).to_lowercase();
                    match status_str.as_str() {
                        "running" | "restarting" | "paused" => ContainerStatus::Running,
                        "exited" | "created" => ContainerStatus::Stopped,
                        "dead" | "removing" => ContainerStatus::Dead,
                        _ => ContainerStatus::Stopped,
                    }
                })
                .unwrap_or(ContainerStatus::Stopped);
            let id = info.id.as_ref()
                .map(|id| id.chars().take(12).collect::<String>());
            let agent_name = info.config.as_ref()
                .and_then(|c| c.labels.as_ref())
                .and_then(|labels| labels.get(LABEL_AGENT_NAME).cloned())
                .filter(|s| !s.trim().is_empty());
            let name = agent_name.clone().unwrap_or_else(|| name_from_cname(cname));
            let port = agents_dir.and_then(|dir| read_env_value(dir, &name, "WS_PORT"))
                .and_then(|v| v.parse().ok());
            ContainerInfo { status, port, id, agent_name }
        }
        Err(_) => ContainerInfo {
            status: ContainerStatus::NotFound,
            port: None,
            id: None,
            agent_name: None,
        },
    }
}

pub async fn container_status(docker: &Docker, cname: &str) -> ContainerStatus {
    inspect_container(docker, cname, None).await.status
}

pub async fn read_container_file(docker: &Docker, cname: &str, container_path: &str) -> Option<String> {
    download_from_container(docker, cname, container_path).await
}

pub async fn is_authenticated(docker: &Docker, cname: &str) -> bool {
    let Some(content) = read_container_file(docker, cname, CREDENTIALS_PATH).await else {
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

/// Sync TCP-only readiness check (no marker file).
pub fn is_agent_ready_sync(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(AGENT_READY_TIMEOUT_MS),
    )
    .is_ok()
}

/// Full async readiness check: TCP + marker file.
pub async fn is_agent_ready(docker: &Docker, port: u16, cname: &str) -> bool {
    let tcp_ok = is_agent_ready_sync(port);
    tcp_ok && read_container_file(docker, cname, AGENT_READY_MARKER_PATH).await.is_some()
}

pub async fn ensure_exists(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    match container_status(docker, cname).await {
        ContainerStatus::NotFound => Err(DockerError::NotFound(format!("agent '{}' not found", name_from_cname(cname)))),
        ContainerStatus::Dead => Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name_from_cname(cname)))),
        _ => Ok(()),
    }
}

pub async fn ensure_running(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    let cs = container_status(docker, cname).await;
    match cs {
        ContainerStatus::NotFound => Err(DockerError::NotFound(format!("agent '{}' not found", name_from_cname(cname)))),
        ContainerStatus::Dead => Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name_from_cname(cname)))),
        ContainerStatus::Running => Ok(()),
        ContainerStatus::Stopped => Err(DockerError::NotRunning(format!("agent '{}' is not running", name_from_cname(cname)))),
    }
}

/// Read an environment variable from a container's config (baked-in env vars).
pub async fn read_container_env(docker: &Docker, cname: &str, key: &str) -> Option<String> {
    let info = docker.inspect_container(cname, None).await.ok()?;
    let envs = info.config?.env?;
    let prefix = format!("{}=", key);
    envs.iter()
        .find(|e| e.starts_with(&prefix))
        .map(|e| e[prefix.len()..].to_string())
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

/// Build a tar archive of the given directory for use with `build_image`.
/// Respects `.dockerignore` if present. Uses `sparse(false)` to avoid GNU sparse
/// headers (type 83) which Docker's daemon cannot parse.
fn build_context_tar(context: &std::path::Path) -> Result<bytes::Bytes, DockerError> {
    let mut builder = tar::Builder::new(Vec::new());
    builder.sparse(false);
    builder.follow_symlinks(true);

    let ignore_patterns = load_dockerignore(context);

    fn visit_dir(
        builder: &mut tar::Builder<Vec<u8>>,
        base: &std::path::Path,
        dir: &std::path::Path,
        ignore: &[String],
    ) -> Result<(), DockerError> {
        let entries = std::fs::read_dir(dir)
            .map_err(|e| DockerError::Failed(format!("failed to read directory {}: {e}", dir.display())))?;
        for entry in entries {
            let entry = entry
                .map_err(|e| DockerError::Failed(format!("failed to read entry in {}: {e}", dir.display())))?;
            let path = entry.path();
            let rel = path.strip_prefix(base).unwrap_or(&path);
            let rel_str = rel.to_string_lossy();

            if is_dockerignored(&rel_str, ignore) {
                continue;
            }

            let ft = entry.file_type()
                .map_err(|e| DockerError::Failed(format!("failed to stat {}: {e}", path.display())))?;
            if ft.is_dir() {
                visit_dir(builder, base, &path, ignore)?;
            } else if ft.is_file() || ft.is_symlink() {
                builder.append_path_with_name(&path, rel)
                    .map_err(|e| DockerError::Failed(format!("failed to add {} to tar: {e}", path.display())))?;
            }
        }
        Ok(())
    }

    visit_dir(&mut builder, context, context, &ignore_patterns)?;

    let tar_bytes = builder.into_inner()
        .map_err(|e| DockerError::Failed(format!("failed to finalize tar: {e}")))?;
    Ok(bytes::Bytes::from(tar_bytes))
}

/// Load and parse `.dockerignore` patterns from a directory.
fn load_dockerignore(context: &std::path::Path) -> Vec<String> {
    let path = context.join(".dockerignore");
    let Ok(content) = std::fs::read_to_string(&path) else { return Vec::new() };
    content.lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| l.to_string())
        .collect()
}

/// Check if a relative path matches `.dockerignore` patterns.
/// Supports `!` negation, `*` (non-separator wildcard), `**` (multi-directory),
/// and `?` (single character). Last matching pattern wins.
fn is_dockerignored(rel_path: &str, patterns: &[String]) -> bool {
    let mut ignored = false;
    for raw in patterns {
        let (negated, pat) = match raw.strip_prefix('!') {
            Some(p) => (true, p.trim()),
            None => (false, raw.as_str()),
        };
        let pat = pat.trim_end_matches('/');
        if docker_pattern_matches(rel_path, pat) {
            ignored = !negated;
        }
    }
    ignored
}

/// Check if `path` starts with `prefix` as a complete directory segment.
fn is_path_prefix(path: &str, prefix: &str) -> bool {
    path == prefix || (path.starts_with(prefix) && path.as_bytes().get(prefix.len()) == Some(&b'/'))
}

/// Match a path against a single dockerignore glob pattern.
fn docker_pattern_matches(path: &str, pattern: &str) -> bool {
    // "**/" prefix: match against any subpath
    if let Some(rest) = pattern.strip_prefix("**/") {
        if docker_pattern_matches(path, rest) {
            return true;
        }
        let mut remaining = path;
        while let Some(pos) = remaining.find('/') {
            remaining = &remaining[pos + 1..];
            if docker_pattern_matches(remaining, rest) {
                return true;
            }
        }
        return false;
    }

    // No slash in pattern.
    if !pattern.contains('/') {
        // Glob patterns (*, ?) match against the filename component at any depth —
        // e.g. "*.pyc" matches "dir/foo.pyc".
        if pattern.contains('*') || pattern.contains('?') {
            let filename = path.rsplit('/').next().unwrap_or(path);
            if glob_match(filename.as_bytes(), pattern.as_bytes()) {
                return true;
            }
        }
        // Literal names match only from the context root — "app" matches "./app"
        // but not "agent/skills/dashboard/app".
        return glob_match(path.as_bytes(), pattern.as_bytes()) || is_path_prefix(path, pattern);
    }

    // Pattern has slashes: match from context root, or as directory prefix
    glob_match(path.as_bytes(), pattern.as_bytes()) || is_path_prefix(path, pattern)
}

/// Simple glob: `*` matches non-`/` chars, `?` matches single non-`/` char,
/// `**` between slashes matches any number of path segments.
fn glob_match(text: &[u8], pattern: &[u8]) -> bool {
    if pattern.is_empty() {
        return text.is_empty();
    }
    match pattern[0] {
        b'*' => {
            // "**/" inside pattern: match zero or more path segments
            if pattern.starts_with(b"**/") {
                let rest = &pattern[3..];
                if glob_match(text, rest) {
                    return true;
                }
                for (i, &byte) in text.iter().enumerate() {
                    if byte == b'/' && glob_match(&text[i + 1..], rest) {
                        return true;
                    }
                }
                return false;
            }
            // Single `*`: match any sequence of non-`/` characters
            let rest = &pattern[1..];
            for i in 0..=text.len() {
                if i > 0 && text[i - 1] == b'/' {
                    break;
                }
                if glob_match(&text[i..], rest) {
                    return true;
                }
            }
            false
        }
        b'?' => !text.is_empty() && text[0] != b'/' && glob_match(&text[1..], &pattern[1..]),
        c => !text.is_empty() && text[0] == c && glob_match(&text[1..], &pattern[1..]),
    }
}

async fn verify_image_runnable(image: &str) -> Result<(), DockerError> {
    let image = image.to_string();
    let output = tokio::task::spawn_blocking(move || {
        std::process::Command::new("docker")
            .args(["run", "--rm", &image, "/bin/true"])
            .output()
    })
    .await
    .map_err(|e| DockerError::Failed(format!("image sanity check task failed: {e}")))?
    .map_err(|e| DockerError::Failed(format!("image sanity check failed to run: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if stderr.to_lowercase().contains("exec format error") {
            return Err(DockerError::Failed(
                "image sanity check failed with 'exec format error'. \
                 docker may be using the containerd snapshotter, which corrupts multi-layer images.\n\
                 \n\
                 Check your storage driver: docker info --format '{{.Driver}}'\n\
                 If it shows 'overlayfs', add to /etc/docker/daemon.json and restart docker:\n\
                 \n\
                 {\n  \"features\": { \"containerd-snapshotter\": false },\n  \"storage-driver\": \"overlay2\"\n}".to_string()
            ));
        }
        return Err(DockerError::Failed(format!("image sanity check failed: {stderr}")));
    }

    Ok(())
}

pub async fn resolve_image(docker: &Docker) -> Result<&'static str, DockerError> {
    if let Ok(context) = find_dockerfile() {
        let tar_body = build_context_tar(&context)?;
        let opts = BuildImageOptions {
            t: LOCAL_IMAGE_TAG,
            q: true,
            rm: true,
            ..Default::default()
        };
        let mut stream = docker.build_image(opts, None, Some(tar_body));
        while let Some(msg) = stream.next().await {
            match msg {
                Err(e) => return Err(DockerError::Failed(format!("image build failed: {e}"))),
                Ok(info) => {
                    if let Some(err) = info.error {
                        return Err(DockerError::Failed(format!("image build failed: {err}")));
                    }
                }
            }
        }
        verify_image_runnable(LOCAL_IMAGE_TAG).await?;
        Ok(LOCAL_IMAGE_TAG)
    } else {
        let opts = CreateImageOptions {
            from_image: VESTA_IMAGE,
            ..Default::default()
        };
        let mut stream = docker.create_image(Some(opts), None, None);
        while let Some(msg) = stream.next().await {
            if let Err(e) = msg {
                return Err(DockerError::Failed(format!("failed to pull image: {e}")));
            }
        }
        verify_image_runnable(VESTA_IMAGE).await?;
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

pub fn allocate_port(agents_dir: &std::path::Path) -> Result<u16, DockerError> {
    let reserved = all_agent_ports(agents_dir);
    for _ in 0..PORT_ALLOC_RETRIES {
        let listener = std::net::TcpListener::bind("127.0.0.1:0")
            .map_err(|e| DockerError::Failed(format!("failed to bind port: {e}")))?;
        let port = listener.local_addr()
            .map_err(|e| DockerError::Failed(format!("failed to get port: {e}")))?
            .port();
        drop(listener);
        if !reserved.contains(&port) {
            return Ok(port);
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
    pub upstream_ref: Option<String>,
}

/// Validate that the config and agents directories exist, are writable, and have
/// no stale entries (e.g. directories where files should be). Fails fast with a
/// clear error instead of producing cryptic permission errors later.
pub fn validate_config_dir(env_config: &AgentEnvConfig) -> Result<(), DockerError> {
    // Ensure dirs exist
    std::fs::create_dir_all(&env_config.agents_dir)
        .map_err(|e| DockerError::Failed(format!(
            "cannot create agents directory {}: {e} — check ownership (try: sudo chown -R $(whoami) {})",
            env_config.agents_dir.display(),
            env_config.config_dir.display(),
        )))?;

    // Check agents_dir is writable by writing a temp file
    let probe = env_config.agents_dir.join(".vestad-probe");
    std::fs::write(&probe, b"")
        .map_err(|e| DockerError::Failed(format!(
            "agents directory {} is not writable: {e} — check ownership (try: sudo chown -R $(whoami) {})",
            env_config.agents_dir.display(),
            env_config.config_dir.display(),
        )))?;
    std::fs::remove_file(&probe).ok();

    // Check for stale entries (directories where .env files should be)
    if let Ok(entries) = std::fs::read_dir(&env_config.agents_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if name_str.ends_with(".env") && path.is_dir() {
                tracing::warn!(
                    path = %path.display(),
                    "removing stale directory where env file should be"
                );
                std::fs::remove_dir_all(&path).map_err(|e| DockerError::Failed(format!(
                    "cannot remove stale directory {}: {e} — check ownership (try: sudo chown -R $(whoami) {})",
                    path.display(),
                    env_config.config_dir.display(),
                )))?;
            }
        }
    }

    Ok(())
}

/// Write a sourceable env file for a single agent. Returns the file path.
pub fn write_agent_env_file(
    env_config: &AgentEnvConfig,
    agent_name: &str,
    ws_port: u16,
    agent_token: &str,
    timezone: Option<&str>,
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
    if let Some(upstream) = &env_config.upstream_ref {
        content.push_str(&format!("export VESTA_UPSTREAM_REF={upstream}\n"));
    }
    if let Some(tz) = timezone {
        content.push_str(&format!("export TZ={tz}\n"));
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

/// Update VESTAD_PORT, VESTAD_TUNNEL, and VESTA_UPSTREAM_REF in all existing per-agent env files.
/// Called at vestad startup so running containers pick up the new values on restart.
pub fn update_all_agent_env_files(agents_dir: &std::path::Path, vestad_port: u16, vestad_tunnel: Option<&str>, upstream_ref: Option<&str>) {
    for name in env_file_names(agents_dir) {
        let path = agents_dir.join(format!("{name}.env"));
        let Ok(content) = std::fs::read_to_string(&path) else { continue };
        let mut new_lines: Vec<String> = content
            .lines()
            .filter(|line| {
                let stripped = line.strip_prefix("export ").unwrap_or(line);
                !stripped.starts_with("VESTAD_PORT=")
                    && !stripped.starts_with("VESTAD_TUNNEL=")
                    && !stripped.starts_with("VESTA_UPSTREAM_REF=")
            })
            .map(|l| l.to_string())
            .collect();
        new_lines.push(format!("export VESTAD_PORT={vestad_port}"));
        if let Some(url) = vestad_tunnel {
            new_lines.push(format!("export VESTAD_TUNNEL={url}"));
        }
        if let Some(upstream) = upstream_ref {
            new_lines.push(format!("export VESTA_UPSTREAM_REF={upstream}"));
        }
        new_lines.push(String::new());
        std::fs::write(&path, new_lines.join("\n")).ok();
    }
}

// --- Container listing ---

pub async fn list_managed_containers(docker: &Docker) -> Vec<String> {
    let mut filters = HashMap::new();
    filters.insert("label", vec!["vesta.managed=true"]);

    let opts = ListContainersOptions {
        all: true,
        filters,
        ..Default::default()
    };

    let containers = match docker.list_containers(Some(opts)).await {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let user = current_user();
    containers
        .into_iter()
        .filter_map(|c| {
            let names = c.names?;
            let name = names.first()?.strip_prefix('/')?.to_string();
            let labels = c.labels.unwrap_or_default();
            let owner = labels.get(LABEL_USER).cloned().unwrap_or_default();
            let modern_owned_by_user =
                crate::migrations::modern_container_owned_by_user(&owner, &user);
            let legacy_owned_by_user =
                crate::migrations::legacy_container_owned_by_user(&name, &owner, &user);
            if modern_owned_by_user || legacy_owned_by_user {
                Some(name)
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

async fn gpu_available(docker: &Docker) -> GpuStatus {
    let has_gpu = tokio::process::Command::new("nvidia-smi")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .await
        .map(|s| s.success())
        .unwrap_or(false);

    if !has_gpu {
        return GpuStatus::NoGpu;
    }

    let has_runtime = match docker.info().await {
        Ok(info) => {
            info.runtimes
                .map(|runtimes| runtimes.contains_key("nvidia"))
                .unwrap_or(false)
        }
        Err(_) => false,
    };

    if has_runtime { GpuStatus::Ready } else { GpuStatus::NoRuntime }
}

// --- Container lifecycle helpers (used by backup.rs) ---

pub async fn stop_container_with_timeout(docker: &Docker, cname: &str, timeout_secs: i64) -> Result<(), DockerError> {
    docker.stop_container(cname, Some(StopContainerOptions { t: timeout_secs })).await?;
    Ok(())
}

pub async fn start_container(docker: &Docker, cname: &str) -> bool {
    docker.start_container(cname, None::<StartContainerOptions<String>>).await.is_ok()
}

pub async fn tag_image(docker: &Docker, source: &str, repo: &str, tag: &str) -> Result<(), DockerError> {
    docker.tag_image(source, Some(TagImageOptions { repo, tag })).await?;
    Ok(())
}

pub async fn remove_image(docker: &Docker, image: &str) -> Result<(), DockerError> {
    docker.remove_image(image, Some(RemoveImageOptions { force: true, ..Default::default() }), None).await?;
    Ok(())
}

/// Export a Docker image to a gzip-compressed tar file.
/// Streams from Docker through gzip to disk without buffering the full image in memory.
/// Cleans up the partial file on failure.
pub async fn export_image_gzip(docker: &Docker, image: &str, output: &std::path::Path) -> Result<(), DockerError> {
    let output = output.to_path_buf();
    let (tx, mut rx) = tokio::sync::mpsc::channel::<bytes::Bytes>(8);

    let write_output = output.clone();
    let write_handle = tokio::task::spawn_blocking(move || -> Result<(), DockerError> {
        let file = std::fs::File::create(&write_output)
            .map_err(|e| DockerError::Failed(format!("failed to create output file: {e}")))?;
        let mut encoder = flate2::write::GzEncoder::new(file, flate2::Compression::default());
        while let Some(chunk) = rx.blocking_recv() {
            std::io::Write::write_all(&mut encoder, &chunk)
                .map_err(|e| DockerError::Failed(format!("failed to write export data: {e}")))?;
        }
        encoder.finish()
            .map_err(|e| DockerError::Failed(format!("failed to finalize gzip: {e}")))?;
        Ok(())
    });

    let mut stream = docker.export_image(image);
    let mut stream_err = None;
    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(data) => {
                if tx.send(data).await.is_err() {
                    break;
                }
            }
            Err(e) => {
                stream_err = Some(DockerError::Failed(format!("export stream error: {e}")));
                break;
            }
        }
    }
    drop(tx);

    if let Some(err) = stream_err {
        tokio::fs::remove_file(&output).await.ok();
        return Err(err);
    }

    write_handle.await
        .map_err(|e| DockerError::Failed(format!("export task failed: {e}")))?
        .inspect_err(|_| {
            std::fs::remove_file(&output).ok();
        })
}

/// Import a Docker image from a gzip-compressed tar file (replaces `gunzip | docker load`).
/// Streams the file directly — Docker's load API accepts gzip natively.
/// Returns the loaded image name (e.g. "vesta-backup:name_12345").
pub async fn import_image_gzip(docker: &Docker, input: &std::path::Path) -> Result<String, DockerError> {
    let file = tokio::fs::File::open(input).await
        .map_err(|e| DockerError::Failed(format!("failed to open input file: {e}")))?;
    let byte_stream = tokio_util::codec::FramedRead::new(file, tokio_util::codec::BytesCodec::new())
        .filter_map(|r| async { r.ok().map(|b| b.freeze()) });

    let opts = ImportImageOptions { ..Default::default() };
    let mut stream = docker.import_image_stream(opts, byte_stream, None);
    let mut loaded_image = String::new();
    while let Some(msg) = stream.next().await {
        let info = msg.map_err(|e| DockerError::Failed(format!("import failed: {e}")))?;
        if let Some(status) = info.status {
            if let Some(name) = status.strip_prefix(LOADED_IMAGE_PREFIX) {
                loaded_image = name.to_string();
            }
        }
    }

    if loaded_image.is_empty() {
        return Err(DockerError::Failed("could not determine loaded image from import".into()));
    }
    Ok(loaded_image)
}

pub async fn image_exists(docker: &Docker, image: &str) -> bool {
    docker.inspect_image(image).await.is_ok()
}

pub async fn list_images_by_reference(docker: &Docker, reference: &str) -> Vec<(String, u64)> {
    let mut filters = HashMap::new();
    filters.insert("reference", vec![reference]);
    let opts = ListImagesOptions {
        filters,
        ..Default::default()
    };
    match docker.list_images(Some(opts)).await {
        Ok(images) => {
            images.into_iter()
                .flat_map(|img| {
                    let size = img.size as u64;
                    img.repo_tags.into_iter().map(move |tag| (tag, size))
                })
                .collect()
        }
        Err(_) => Vec::new(),
    }
}

pub async fn docker_root_dir(docker: &Docker) -> String {
    match docker.info().await {
        Ok(info) => info.docker_root_dir.unwrap_or_else(|| "/var/lib/docker".to_string()),
        Err(_) => "/var/lib/docker".to_string(),
    }
}

pub async fn container_size_rw(docker: &Docker, cname: &str) -> Option<u64> {
    let info = docker.inspect_container(cname, Some(bollard::container::InspectContainerOptions { size: true })).await.ok()?;
    info.size_rw.map(|s| s as u64)
}

pub async fn container_created(docker: &Docker, cname: &str) -> Option<String> {
    let info = docker.inspect_container(cname, None).await.ok()?;
    info.created
}

pub async fn remove_container_force(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    docker.remove_container(cname, Some(RemoveContainerOptions { force: true, ..Default::default() })).await?;
    Ok(())
}

// --- Snapshot ---

const SNAPSHOT_TIMEOUT_SECS: u64 = 7200; // 2 hours — 25GB+ containers can take a long time

/// Snapshot a container's filesystem as a new image using `docker export | docker import`.
/// Unlike `docker commit`, this doesn't depend on parent image layers existing.
/// Optional `changes` apply Dockerfile instructions (e.g. LABEL) to the imported image.
pub async fn snapshot_container(_docker: &Docker, cname: &str, tag: &str, changes: &[&str]) -> Result<(), DockerError> {
    let cname = cname.to_string();
    let tag = tag.to_string();
    let changes: Vec<String> = changes.iter().map(|s| s.to_string()).collect();

    tokio::time::timeout(
        std::time::Duration::from_secs(SNAPSHOT_TIMEOUT_SECS),
        tokio::task::spawn_blocking(move || {
            let mut export_child = std::process::Command::new("docker")
                .args(["export", &cname])
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::piped())
                .spawn()
                .map_err(|e| DockerError::Failed(format!("failed to start docker export: {e}")))?;

            let export_stdout = export_child.stdout.take()
                .ok_or_else(|| DockerError::Failed("docker export stdout not available".into()))?;

            let mut import_args = vec!["import".to_string()];
            for change in &changes {
                import_args.push("--change".to_string());
                import_args.push(change.clone());
            }
            import_args.push("-".to_string());
            import_args.push(tag);

            let import_output = std::process::Command::new("docker")
                .args(&import_args)
                .stdin(export_stdout)
                .output()
                .map_err(|e| DockerError::Failed(format!("failed to run docker import: {e}")))?;

            let export_output = export_child.wait_with_output()
                .map_err(|e| DockerError::Failed(format!("docker export wait failed: {e}")))?;
            if !export_output.status.success() {
                let stderr = String::from_utf8_lossy(&export_output.stderr);
                return Err(DockerError::Failed(format!("docker export failed: {stderr}")));
            }
            if !import_output.status.success() {
                let stderr = String::from_utf8_lossy(&import_output.stderr);
                return Err(DockerError::Failed(format!("docker import failed: {stderr}")));
            }
            Ok(())
        }),
    )
    .await
    .map_err(|_| DockerError::Failed(format!("snapshot timed out after {SNAPSHOT_TIMEOUT_SECS}s")))?
    .map_err(|e| DockerError::Failed(format!("snapshot task failed: {e}")))?
}

// --- Container creation ---

#[allow(clippy::too_many_arguments)]
pub async fn create_container(docker: &Docker, cname: &str, image: &str, port: u16, agent_name: &str, env_config: &AgentEnvConfig, manage_core_code: bool, timezone: Option<&str>) -> Result<(), DockerError> {
    let agent_token = generate_agent_token();
    let env_path = write_agent_env_file(env_config, agent_name, port, &agent_token, timezone)?;
    let env_mount = format!("{}:{}:ro,z", env_path.display(), MOUNT_DESTS[0]);

    let code_dir = crate::agent_code::agent_code_dir(&env_config.config_dir);
    let core_mount = format!("{}:{}:ro,z", code_dir.join("core").display(), MOUNT_DESTS[1]);
    let pyproject_mount = format!("{}:{}:ro,z", code_dir.join("pyproject.toml").display(), MOUNT_DESTS[2]);
    let lock_mount = format!("{}:{}:ro,z", code_dir.join("uv.lock").display(), MOUNT_DESTS[3]);

    let mut labels = HashMap::new();
    labels.insert("vesta.managed".to_string(), "true".to_string());
    labels.insert(LABEL_USER.to_string(), current_user());
    labels.insert(LABEL_AGENT_NAME.to_string(), agent_name.to_string());

    let mut binds = vec![env_mount];
    if manage_core_code {
        binds.extend([core_mount, pyproject_mount, lock_mount]);
    }

    let mut device_requests = None;
    match gpu_available(docker).await {
        GpuStatus::Ready => {
            device_requests = Some(vec![bollard::models::DeviceRequest {
                count: Some(-1),
                capabilities: Some(vec![vec!["gpu".to_string()]]),
                ..Default::default()
            }]);
            tracing::info!("GPU detected, enabling passthrough");
        }
        GpuStatus::NoRuntime => {
            tracing::warn!("NVIDIA GPU detected but nvidia-container-toolkit is not installed. Install it to enable GPU passthrough: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html");
        }
        GpuStatus::NoGpu => {}
    }

    tracing::info!(agent = %agent_name, image = %image, manage_core_code, "creating container");

    let host_config = bollard::models::HostConfig {
        binds: Some(binds),
        network_mode: Some(NETWORK_MODE.to_string()),
        restart_policy: Some(bollard::models::RestartPolicy {
            name: Some(bollard::models::RestartPolicyNameEnum::UNLESS_STOPPED),
            ..Default::default()
        }),
        device_requests,
        devices: Some(vec![bollard::models::DeviceMapping {
            path_on_host: Some("/dev/fuse".to_string()),
            path_in_container: Some("/dev/fuse".to_string()),
            cgroup_permissions: Some("rwm".to_string()),
        }]),
        cap_add: Some(vec!["SYS_ADMIN".to_string()]),
        ..Default::default()
    };

    let config = Config {
        image: Some(image.to_string()),
        tty: Some(true),
        labels: Some(labels),
        cmd: Some(agent_container_entrypoint_cmd()),
        working_dir: Some("/root".to_string()),
        host_config: Some(host_config),
        ..Default::default()
    };

    let create_opts = CreateContainerOptions {
        name: cname,
        ..Default::default()
    };

    match docker.create_container(Some(create_opts), config).await {
        Ok(_) => Ok(()),
        Err(e) => {
            delete_agent_env_file(&env_config.agents_dir, agent_name);
            Err(DockerError::from(e))
        }
    }
}

// --- Credential injection ---

pub(crate) async fn docker_cp_content(docker: &Docker, container: &str, content: &str, dest: &str) -> Result<(), DockerError> {
    // dest is a full path like "/root/.claude.json" — split into dir and filename
    let path = std::path::Path::new(dest);
    let parent = path.parent()
        .map(|p| p.to_str().unwrap_or("/"))
        .unwrap_or("/");
    let file_name = path.file_name()
        .map(|f| f.to_str().unwrap_or("file"))
        .unwrap_or("file");
    upload_to_container(docker, container, parent, file_name, content.as_bytes()).await
}

pub async fn inject_credentials(docker: &Docker, container: &str, credentials: &str) -> Result<(), DockerError> {
    // Build a tar with .credentials.json and upload to /root/.claude/
    let tar_data = tar_single_file(".credentials.json", credentials.as_bytes())?;
    docker.upload_to_container(
        container,
        Some(UploadToContainerOptions {
            path: "/root/.claude/".to_string(),
            ..Default::default()
        }),
        tar_data.into(),
    ).await?;

    docker_cp_content(docker, container, "{\"hasCompletedOnboarding\":true}", CLAUDE_JSON_PATH).await?;
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
pub async fn complete_auth_flow(client: &reqwest::Client, input: &str, code_verifier: &str, expected_state: &str) -> Result<String, DockerError> {
    let (auth_code, pasted_state) = match input.split_once('#') {
        Some((code, st)) => (code, st),
        None => (input, expected_state),
    };

    if pasted_state != expected_state {
        return Err(DockerError::Failed("state mismatch — possible CSRF, please retry auth".into()));
    }

    let body = serde_json::json!({
        "grant_type": "authorization_code",
        "code": auth_code,
        "state": pasted_state,
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": code_verifier,
    });

    let response = client.post(OAUTH_TOKEN_URL)
        .header("User-Agent", "axios/1.13.6")
        .json(&body)
        .send()
        .await
        .map_err(|e| DockerError::Failed(format!("token exchange request failed: {e}")))?;

    let response_str = response.text().await
        .map_err(|e| DockerError::Failed(format!("failed to read token response: {e}")))?;

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

// --- High-level operations (used by serve.rs handlers) ---

pub async fn get_status(docker: &Docker, name: &str, agents_dir: &std::path::Path) -> Result<StatusJson, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(docker, &cname, Some(agents_dir)).await;

    Ok(StatusJson {
        name: name.to_string(),
        status: combined_status(docker, &cname, &info).await,
        id: info.id,
        ws_port: info.port.unwrap_or(0),
    })
}

pub async fn list_agents(docker: &Docker, agents_dir: &std::path::Path) -> Vec<ListEntry> {
    let containers = list_managed_containers(docker).await;
    let mut entries = Vec::new();
    for cname in &containers {
        let info = inspect_container(docker, cname, Some(agents_dir)).await;
        let name = info.agent_name.clone().unwrap_or_else(|| name_from_cname(cname));
        entries.push(ListEntry {
            name,
            status: combined_status(docker, cname, &info).await,
            ws_port: info.port.unwrap_or(0),
        });
    }
    entries
}

pub async fn create_agent(docker: &Docker, name: &str, env_config: &AgentEnvConfig, manage_core_code: bool, timezone: Option<&str>) -> Result<String, DockerError> {
    let name = if name == "ignisinextinctus" { "vesta" } else { name };
    validate_name(name)?;
    if name != "vesta" && name.contains("vesta") {
        return Err(DockerError::InvalidName("agent name must not contain 'vesta'".into()));
    }
    let cname = container_name(name);

    if container_status(docker, &cname).await != ContainerStatus::NotFound {
        return Err(DockerError::AlreadyExists(format!("agent '{}' already exists", name)));
    }

    let image = resolve_image(docker).await?;

    if manage_core_code {
        let code_source = if cfg!(debug_assertions) { "local repo" } else { "github" };
        tracing::info!(agent = %name, source = code_source, "fetching agent code");
        crate::agent_code::ensure_agent_code(&env_config.config_dir)
            .map_err(|e| DockerError::Failed(format!("agent code: {e}")))?;
    }

    let port = allocate_port(&env_config.agents_dir)?;
    create_container(docker, &cname, image, port, name, env_config, manage_core_code, timezone).await?;
    Ok(name.to_string())
}

pub async fn start_agent(docker: &Docker, name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(docker, &cname).await;
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        ContainerStatus::Running => return Ok(()),
        ContainerStatus::Stopped => {}
    }
    if !start_container(docker, &cname).await {
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

pub async fn start_all_agents(docker: &Docker) -> Vec<StartAllResult> {
    let containers = list_managed_containers(docker).await;
    let mut results = Vec::new();
    for cname in &containers {
        let name = get_agent_name(docker, cname).await;
        if container_status(docker, cname).await != ContainerStatus::Running {
            if start_container(docker, cname).await {
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

pub async fn stop_agent(docker: &Docker, name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(docker, &cname).await;
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        ContainerStatus::Stopped => return Ok(()),
        ContainerStatus::Running => {}
    }
    docker.stop_container(&cname, Some(StopContainerOptions { t: CONTAINER_STOP_TIMEOUT_SECS })).await?;
    Ok(())
}

pub async fn restart_agent(docker: &Docker, name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    ensure_exists(docker, &cname).await?;
    docker.restart_container(&cname, Some(bollard::container::RestartContainerOptions { t: CONTAINER_RESTART_TIMEOUT_SECS })).await?;
    Ok(())
}

/// Ensure all containers match expected config and running agents are restarted.
/// Called once at startup after agent code and env files are ready.
/// `manages_core_code` returns whether a given agent name has vestad-managed core code mounts (default true).
pub async fn reconcile_containers(docker: &Docker, env_config: &AgentEnvConfig, manages_core_code: &(dyn Fn(&str) -> bool + Send + Sync)) {
    let containers = list_managed_containers(docker).await;
    if containers.is_empty() {
        return;
    }

    // Phase 1: ensure env files exist, track which are running
    let mut was_running = std::collections::HashSet::new();
    for cname in &containers {
        let name = get_agent_name(docker, cname).await;
        if container_status(docker, cname).await == ContainerStatus::Running {
            was_running.insert(name.clone());
        }
        let env_path = env_config.agents_dir.join(format!("{name}.env"));
        if env_path.is_file() {
            tracing::info!(agent = %name, "env file ok");
        } else {
            if env_path.exists() {
                tracing::warn!(agent = %name, path = %env_path.display(), "env path is not a file, removing");
                if let Err(e) = std::fs::remove_dir_all(&env_path) {
                    tracing::error!(agent = %name, error = %e, "failed to remove stale env path");
                    continue;
                }
            }
            tracing::info!(agent = %name, "env file missing, recreating");
            let port = read_container_env(docker, cname, "WS_PORT").await
                .and_then(|v| v.parse::<u16>().ok())
                .or_else(|| allocate_port(&env_config.agents_dir).ok());
            if let Some(port) = port {
                let token = generate_agent_token();
                if let Err(e) = write_agent_env_file(env_config, &name, port, &token, None) {
                    tracing::error!(agent = %name, error = %e, "failed to create env file");
                }
            } else {
                tracing::error!(agent = %name, "could not determine or allocate port for env file");
            }
        }
    }

    // Phase 2: rebuild containers with wrong config
    let mut agent_code_ok = false;
    for cname in &containers {
        let name = get_agent_name(docker, cname).await;
        let manage_core_code = manages_core_code(&name);
        if !needs_rebuild(docker, cname, manage_core_code).await {
            tracing::info!(agent = %name, "config ok, no rebuild needed");
            continue;
        }
        tracing::info!(agent = %name, "rebuild needed");
        if manage_core_code && !agent_code_ok {
            match crate::agent_code::ensure_agent_code(&env_config.config_dir) {
                Ok(_) => agent_code_ok = true,
                Err(e) => {
                    tracing::error!(error = %e, "failed to ensure agent code — skipping rebuilds");
                    break;
                }
            }
        }
        match rebuild_agent(docker, &name, env_config, manage_core_code).await {
            Ok(()) => tracing::info!(agent = %name, "rebuild complete"),
            Err(e) => tracing::error!(agent = %name, error = %e, "rebuild failed"),
        }
    }

    // Phase 3: restart running agents (picks up new env), start rebuilt ones
    for cname in &containers {
        let name = get_agent_name(docker, cname).await;
        match container_status(docker, cname).await {
            ContainerStatus::Running => {
                tracing::info!(agent = %name, "restarting");
                docker.restart_container(cname, Some(bollard::container::RestartContainerOptions { t: CONTAINER_RESTART_TIMEOUT_SECS })).await.ok();
            }
            ContainerStatus::Stopped if was_running.contains(&name) => {
                tracing::info!(agent = %name, "starting after rebuild");
                start_container(docker, cname).await;
            }
            status => {
                tracing::info!(agent = %name, ?status, "not restarting");
            }
        }
    }

    // Summary: log which agents are running after reconciliation
    let mut running = Vec::new();
    let mut stopped = Vec::new();
    for cname in &containers {
        let name = get_agent_name(docker, cname).await;
        if container_status(docker, cname).await == ContainerStatus::Running {
            running.push(name);
        } else {
            stopped.push(name);
        }
    }
    if !running.is_empty() {
        tracing::info!(agents = ?running, "running");
    }
    if !stopped.is_empty() {
        tracing::info!(agents = ?stopped, "stopped");
    }
}

pub async fn destroy_agent(docker: &Docker, name: &str, agents_dir: &std::path::Path) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let cs = container_status(docker, &cname).await;
    match cs {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        ContainerStatus::Running => { docker.stop_container(&cname, Some(StopContainerOptions { t: CONTAINER_STOP_TIMEOUT_SECS })).await.ok(); }
        ContainerStatus::Stopped => {}
    }
    remove_container_force(docker, &cname).await?;
    delete_agent_env_file(agents_dir, name);
    Ok(())
}

/// Check if a container's config diverges from what create_container would produce.
async fn needs_rebuild(docker: &Docker, cname: &str, manage_core_code: bool) -> bool {
    let info = match docker.inspect_container(cname, None).await {
        Ok(i) => i,
        Err(_) => return true,
    };

    // Check mounts
    let mounts = info.mounts.as_deref().unwrap_or(&[]);
    let mount_dests: Vec<&str> = mounts.iter()
        .filter_map(|m| m.destination.as_deref())
        .collect();

    let expected_mounts: &[&str] = if manage_core_code { MOUNT_DESTS } else { &MOUNT_DESTS[..1] };
    let missing: Vec<_> = expected_mounts.iter().filter(|d| !mount_dests.contains(*d)).collect();
    if !missing.is_empty() {
        tracing::info!(container = %cname, missing = ?missing, "rebuild needed: missing mounts");
        return true;
    }
    if !manage_core_code {
        let unexpected: Vec<_> = MOUNT_DESTS[1..].iter().filter(|d| mount_dests.contains(*d)).collect();
        if !unexpected.is_empty() {
            tracing::info!(container = %cname, unexpected = ?unexpected, "rebuild needed: has core code mounts while manage_core_code is false");
            return true;
        }
    }

    // Check cmd
    let cmd = info.config.as_ref()
        .and_then(|c| c.cmd.as_ref());
    let expected_cmd = agent_container_entrypoint_cmd();
    let cmd_ok = cmd
        .map(|actual| {
            actual.len() == expected_cmd.len()
                && actual.iter().zip(expected_cmd.iter()).all(|(a, e)| a == e)
        })
        .unwrap_or(false);
    if !cmd_ok {
        tracing::info!(container = %cname, actual = ?cmd, expected = ?expected_cmd, "rebuild needed: command mismatch");
        return true;
    }

    // Check network mode
    let network = info.host_config.as_ref()
        .and_then(|h| h.network_mode.as_deref())
        .unwrap_or("");
    if network != NETWORK_MODE {
        tracing::info!(container = %cname, actual = network, expected = NETWORK_MODE, "rebuild needed: wrong network mode");
        return true;
    }

    // Check restart policy — bollard returns the enum variant name
    let restart = info.host_config.as_ref()
        .and_then(|h| h.restart_policy.as_ref())
        .and_then(|r| r.name.as_ref())
        .map(|n| format!("{:?}", n).to_lowercase())
        .unwrap_or_default();
    if !restart.contains("unless") {
        tracing::info!(container = %cname, actual = restart, expected = RESTART_POLICY, "rebuild needed: wrong restart policy");
        return true;
    }

    // Check /dev/fuse device
    let devices = info.host_config.as_ref()
        .and_then(|h| h.devices.as_deref())
        .unwrap_or(&[]);
    let has_fuse = devices.iter().any(|d| {
        d.path_on_host.as_deref() == Some("/dev/fuse")
    });
    if !has_fuse {
        tracing::info!(container = %cname, "rebuild needed: missing /dev/fuse device");
        return true;
    }

    // Check SYS_ADMIN capability
    let caps = info.host_config.as_ref()
        .and_then(|h| h.cap_add.as_deref())
        .unwrap_or(&[]);
    if !caps.iter().any(|c| c == "SYS_ADMIN") {
        tracing::info!(container = %cname, "rebuild needed: missing SYS_ADMIN capability");
        return true;
    }

    false
}

/// Recreate a container with the latest container config (entrypoint, mounts, env file)
/// while preserving the filesystem. Commits the old container, removes it, and creates
/// a new one from the committed image.
pub async fn rebuild_agent(docker: &Docker, name: &str, env_config: &AgentEnvConfig, manage_core_code: bool) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(docker, &cname, Some(&env_config.agents_dir)).await;
    match info.status {
        ContainerStatus::NotFound => return Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        _ => {}
    }

    // Get port: try env file first, then container's baked-in env vars, then allocate new
    let container_port = read_container_env(docker, &cname, "WS_PORT").await
        .and_then(|v| v.parse::<u16>().ok());
    let port = match info.port.or(container_port) {
        Some(p) => p,
        None => {
            tracing::warn!(agent = %name, "no port found in env file or container — allocating new port");
            allocate_port(&env_config.agents_dir)?
        }
    };

    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let backup_tag = format!("vesta-rebuild:{}_{}", name, ts);
    let normalized_tag = format!("vesta-rebuild:{}_{}-normalized", name, ts);
    let helper_name = format!("{}-normalize", cname);

    tracing::info!(agent = %name, "[1/3] snapshotting container filesystem...");
    snapshot_container(docker, &cname, &backup_tag, &[]).await?;

    // Chain migrations on the snapshot. Each migration produces a new image
    // tag if it modifies the filesystem; subsequent migrations inspect the
    // latest image's helper container.
    let mut current_image = backup_tag.clone();

    // Migration 1: /root/vesta/ → /root + /root/agent/ (very old layout)
    if crate::migrations::maybe_normalize_legacy_agent_snapshot(
        docker,
        &cname,
        &current_image,
        &helper_name,
        &normalized_tag,
    ).await? {
        current_image = normalized_tag.clone();
    }

    // Migration 2: agent/src/vesta/ → agent/core/ (pre-0.1.135 layout)
    let core_tag = format!("{normalized_tag}-core");
    if crate::migrations::maybe_rename_src_vesta_to_core(
        docker,
        &cname,
        &current_image,
        &helper_name,
        &core_tag,
    ).await? {
        current_image = core_tag;
    }

    // Migration 3: remove old unified upstream skill (replaced by upstream-sync + upstream-pr)
    let upstream_tag = format!("{normalized_tag}-upstream");
    if crate::migrations::maybe_remove_old_upstream_skill(
        docker,
        &cname,
        &current_image,
        &helper_name,
        &upstream_tag,
    ).await? {
        current_image = upstream_tag;
    }

    let rebuild_image = current_image;

    tracing::info!(agent = %name, "[2/3] removing old container...");
    remove_container_force(docker, &cname).await.ok();

    tracing::info!(agent = %name, "[3/3] creating container with new config...");
    create_container(docker, &cname, &rebuild_image, port, name, env_config, manage_core_code, None).await?;

    Ok(())
}

pub async fn wait_ready_async(docker: &Docker, name: &str, timeout_secs: u64, agents_dir: &std::path::Path) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    ensure_running(docker, &cname).await?;
    let port = read_env_value(agents_dir, name, "WS_PORT")
        .and_then(|v| v.parse().ok())
        .ok_or_else(|| DockerError::Failed("agent has no port".into()))?;

    let deadline = tokio::time::Instant::now() + tokio::time::Duration::from_secs(timeout_secs);
    loop {
        if is_agent_ready(docker, port, &cname).await {
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

    // --- Dockerignore pattern matching ---

    fn patterns(pats: &[&str]) -> Vec<String> {
        pats.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn dockerignore_exact_match() {
        let pats = patterns(&["target"]);
        assert!(is_dockerignored("target", &pats));
        assert!(is_dockerignored("target/debug/foo", &pats));
        assert!(!is_dockerignored("targets", &pats));
        assert!(!is_dockerignored("some/nested/target", &pats));
        assert!(!is_dockerignored("some/nested/target/file.txt", &pats));
    }

    #[test]
    fn dockerignore_trailing_slash() {
        let pats = patterns(&["app/"]);
        // Matches root-level app/ directory
        assert!(is_dockerignored("app", &pats));
        assert!(is_dockerignored("app/package.json", &pats));
        // Must NOT match nested directories with the same name
        assert!(!is_dockerignored("agent/skills/dashboard/app", &pats));
        assert!(!is_dockerignored("agent/skills/dashboard/app/src/App.tsx", &pats));
    }

    #[test]
    fn dockerignore_wildcard_extension() {
        let pats = patterns(&["*.pyc"]);
        assert!(is_dockerignored("foo.pyc", &pats));
        assert!(is_dockerignored("dir/bar.pyc", &pats));
        assert!(!is_dockerignored("foo.py", &pats));
    }

    #[test]
    fn dockerignore_question_mark() {
        let pats = patterns(&["?.txt"]);
        assert!(is_dockerignored("a.txt", &pats));
        assert!(!is_dockerignored("ab.txt", &pats));
    }

    #[test]
    fn dockerignore_doublestar() {
        let pats = patterns(&["**/logs"]);
        assert!(is_dockerignored("logs", &pats));
        assert!(is_dockerignored("a/logs", &pats));
        assert!(is_dockerignored("a/b/logs", &pats));
        assert!(is_dockerignored("a/b/logs/debug.log", &pats));
    }

    #[test]
    fn dockerignore_negation() {
        let pats = patterns(&["*.md", "!README.md"]);
        assert!(!is_dockerignored("README.md", &pats));
        assert!(is_dockerignored("CHANGELOG.md", &pats));
    }

    #[test]
    fn dockerignore_path_with_slash() {
        let pats = patterns(&["agent/tests"]);
        assert!(is_dockerignored("agent/tests", &pats));
        assert!(is_dockerignored("agent/tests/test_unit.py", &pats));
        assert!(!is_dockerignored("other/agent/tests", &pats));
    }

    #[test]
    fn dockerignore_no_false_prefix() {
        let pats = patterns(&["app"]);
        assert!(!is_dockerignored("application", &pats));
        assert!(is_dockerignored("app/foo", &pats));
    }

    // --- Docker integration tests (require Docker daemon) ---
    // Run with: cargo test -p vestad -- --ignored

    const TEST_PREFIX: &str = "vesta-integration-test";

    fn test_docker() -> Docker {
        connect().expect("failed to connect to docker")
    }

    /// Best-effort cleanup via docker CLI (safe to call from Drop inside tokio).
    fn docker_cleanup(args: &[&str]) {
        std::process::Command::new("docker")
            .args(args)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .ok();
    }

    /// Create a unique container name for tests and ensure cleanup on drop.
    struct TestContainer {
        name: String,
    }

    impl TestContainer {
        fn new(suffix: &str) -> Self {
            let name = format!("{}-{}-{}", TEST_PREFIX, suffix, std::process::id());
            // Clean up any leftover from previous runs
            docker_cleanup(&["rm", "-f", &name]);
            Self { name }
        }
    }

    impl Drop for TestContainer {
        fn drop(&mut self) {
            docker_cleanup(&["rm", "-f", &self.name]);
        }
    }

    /// Clean up a test image on drop.
    struct TestImage {
        tag: String,
    }

    impl TestImage {
        fn new(suffix: &str) -> Self {
            let tag = format!("{}:{}-{}", TEST_PREFIX, suffix, std::process::id());
            Self { tag }
        }
    }

    impl Drop for TestImage {
        fn drop(&mut self) {
            docker_cleanup(&["rmi", &self.tag]);
        }
    }

    async fn create_test_container_async(docker: &Docker, tc: &TestContainer, mounts: &[(&str, &str)], cmd: Vec<String>, network: &str, restart: &str) {
        let binds: Vec<String> = mounts.iter()
            .map(|(src, dst)| format!("{}:{}:ro,z", src, dst))
            .collect();

        let restart_policy = match restart {
            "unless-stopped" => bollard::models::RestartPolicyNameEnum::UNLESS_STOPPED,
            "no" => bollard::models::RestartPolicyNameEnum::NO,
            "always" => bollard::models::RestartPolicyNameEnum::ALWAYS,
            _ => bollard::models::RestartPolicyNameEnum::NO,
        };

        let mut labels = HashMap::new();
        labels.insert("vesta.managed".to_string(), "true".to_string());

        let host_config = bollard::models::HostConfig {
            binds: Some(binds),
            network_mode: Some(network.to_string()),
            restart_policy: Some(bollard::models::RestartPolicy {
                name: Some(restart_policy),
                ..Default::default()
            }),
            devices: Some(vec![bollard::models::DeviceMapping {
                path_on_host: Some("/dev/fuse".to_string()),
                path_in_container: Some("/dev/fuse".to_string()),
                cgroup_permissions: Some("rwm".to_string()),
            }]),
            cap_add: Some(vec!["SYS_ADMIN".to_string()]),
            ..Default::default()
        };

        let config = bollard::container::Config {
            image: Some(VESTA_IMAGE.to_string()),
            tty: Some(true),
            labels: Some(labels),
            cmd: Some(cmd),
            host_config: Some(host_config),
            ..Default::default()
        };

        docker.create_container(
            Some(CreateContainerOptions { name: tc.name.as_str(), platform: None }),
            config,
        ).await.expect("failed to create test container");
    }

    #[tokio::test]
    #[ignore]
    async fn test_snapshot_roundtrip() {
        let docker = test_docker();
        let tc = TestContainer::new("snapshot-rt");
        let img = TestImage::new("snapshot-rt");

        create_test_container_async(&docker, &tc, &[], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        snapshot_container(&docker, &tc.name, &img.tag, &[]).await.expect("snapshot should succeed");

        // Verify image exists
        assert!(image_exists(&docker, &img.tag).await, "snapshot image should exist");
    }

    #[tokio::test]
    #[ignore]
    async fn test_snapshot_with_changes() {
        let docker = test_docker();
        let tc = TestContainer::new("snapshot-labels");
        let img = TestImage::new("snapshot-labels");

        create_test_container_async(&docker, &tc, &[], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        let label = "LABEL test.marker=integration-test";
        snapshot_container(&docker, &tc.name, &img.tag, &[label]).await.expect("snapshot with changes should succeed");

        // Verify label was applied
        let info = docker.inspect_image(&img.tag).await.expect("image should exist");
        let labels = info.config.as_ref().and_then(|c| c.labels.as_ref());
        let marker = labels.and_then(|l| l.get("test.marker")).map(|s| s.as_str());
        assert_eq!(marker, Some("integration-test"));
    }

    #[tokio::test]
    #[ignore]
    async fn test_snapshot_nonexistent_container() {
        let docker = test_docker();
        let result = snapshot_container(&docker, "vesta-nonexistent-container-xyz", "vesta-test:garbage", &[]).await;
        assert!(result.is_err(), "snapshot of nonexistent container should fail");
        remove_image(&docker, "vesta-test:garbage").await.ok();
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_false_on_fresh_container() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-fresh");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(!needs_rebuild(&docker, &tc.name, false).await, "fresh container should NOT need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_false_with_all_mounts() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-mounts");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();

        let code_dir = tempfile::TempDir::new().expect("tempdir");
        std::fs::create_dir_all(code_dir.path().join("core")).unwrap();
        std::fs::write(code_dir.path().join("pyproject.toml"), "").unwrap();
        std::fs::write(code_dir.path().join("uv.lock"), "").unwrap();

        let src_core = code_dir.path().join("core");
        let pyproject = code_dir.path().join("pyproject.toml");
        let uv_lock = code_dir.path().join("uv.lock");

        let mounts = [
            (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]),
            (src_core.to_str().unwrap(), MOUNT_DESTS[1]),
            (pyproject.to_str().unwrap(), MOUNT_DESTS[2]),
            (uv_lock.to_str().unwrap(), MOUNT_DESTS[3]),
        ];

        create_test_container_async(&docker, &tc, &mounts, agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(!needs_rebuild(&docker, &tc.name, true).await, "container with all mounts should NOT need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_true_on_wrong_cmd() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-cmd");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], vec!["sh".into(), "-c".into(), "echo wrong".into()], NETWORK_MODE, RESTART_POLICY).await;

        assert!(needs_rebuild(&docker, &tc.name, false).await, "container with wrong cmd SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_true_on_missing_mount() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-nomount");

        create_test_container_async(&docker, &tc, &[], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(needs_rebuild(&docker, &tc.name, false).await, "container without env mount SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_true_on_missing_code_mounts() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-nocode");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(needs_rebuild(&docker, &tc.name, true).await, "container missing code mounts SHOULD need rebuild when manage_core_code=true");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_true_on_wrong_network() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-net");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), "bridge", RESTART_POLICY).await;

        assert!(needs_rebuild(&docker, &tc.name, false).await, "container with wrong network SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_true_on_wrong_restart() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-restart");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, "no").await;

        assert!(needs_rebuild(&docker, &tc.name, false).await, "container with wrong restart policy SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_false_after_snapshot_rebuild() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-full");
        let img = TestImage::new("rebuild-full");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        // Create with wrong network to force rebuild
        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), "bridge", RESTART_POLICY).await;
        assert!(needs_rebuild(&docker, &tc.name, false).await, "precondition: should need rebuild");

        // Snapshot
        snapshot_container(&docker, &tc.name, &img.tag, &[]).await.expect("snapshot should succeed");

        // Remove old, create new from snapshot with correct config
        remove_container_force(&docker, &tc.name).await.ok();
        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(!needs_rebuild(&docker, &tc.name, false).await, "rebuilt container should NOT need rebuild");
    }
}
