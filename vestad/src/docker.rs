use bollard::models::ContainerCreateBody;
use bollard::query_parameters::{
    BuildImageOptions, CreateContainerOptions, CreateImageOptions, DownloadFromContainerOptions,
    ImportImageOptions, InspectContainerOptions, ListContainersOptions,
    RemoveContainerOptions, RemoveImageOptions, RestartContainerOptions, StopContainerOptions,
    UploadToContainerOptions,
};
use bollard::Docker;
use bytes::Bytes;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
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

impl std::error::Error for DockerError {}

impl From<bollard::errors::Error> for DockerError {
    fn from(e: bollard::errors::Error) -> Self {
        let msg = e.to_string();
        match e {
            bollard::errors::Error::DockerResponseServerError { status_code: 404, .. } => DockerError::NotFound(msg),
            bollard::errors::Error::DockerResponseServerError { status_code: 409, .. } => DockerError::AlreadyExists(msg),
            _ => DockerError::Failed(msg),
        }
    }
}

/// The agent image registry repository. The tag is vestad's own version (see
/// [`vesta_image`]), not a floating `:latest`, so the running agent image always
/// matches the vestad binary and its embedded agent core. This keeps the channel a
/// single knob (which version vestad targets) and removes the skew where `:latest`
/// could advance ahead of the running vestad.
pub const VESTA_IMAGE_REPO: &str = "ghcr.io/elyxlz/vesta";

/// The agent image this vestad pulls: `ghcr.io/elyxlz/vesta:vX.Y.Z` pinned to the
/// running vestad version. CI publishes this exact tag for every release (stable or
/// prerelease), so it exists on both channels.
pub fn vesta_image() -> String {
    format!("{}:v{}", VESTA_IMAGE_REPO, env!("CARGO_PKG_VERSION"))
}
pub const VESTA_LOG_PATH: &str = "/root/agent/logs/vesta.log";
pub const LOCAL_IMAGE_TAG: &str = "vesta:local";
/// Env var that pins the agent image, skipping the local build / registry pull.
/// Used by CI to test against an image built from the PR checkout.
pub const AGENT_IMAGE_ENV: &str = "VESTAD_AGENT_IMAGE";
const MAX_DOCKERFILE_SEARCH_DEPTH: usize = 5;
const AGENT_TOKEN_BYTES: usize = 32;
const PORT_ALLOC_RETRIES: usize = 10;
const NAME_MAX_LEN: usize = 32;
const DOCKER_DAEMON_PING_RETRIES: usize = 10;
const AGENT_READY_TIMEOUT_MS: u64 = 200;
const DEFAULT_TOKEN_EXPIRES_SECS: u64 = 28800;
const LABEL_USER: &str = "vesta.user";
const LABEL_AGENT_NAME: &str = "vesta.agent_name";

const OAUTH_HTTP_TIMEOUT_SECS: u64 = 30;

pub const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
pub const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
pub const OAUTH_TOKEN_URL: &str = "https://platform.claude.com/v1/oauth/token";
pub const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

// --- Expected container config (single source of truth) ---

const NETWORK_MODE: &str = "host";
// on-failure (not unless-stopped) so Docker recovers genuine crashes but never auto-starts a
// stale container on daemon/host boot: vestad owns boot-start (reconcile -> rebuild -> start),
// so an agent that needs a rebuild is never reachable on its pre-update container. The bound caps
// a hard crash-loop so a wedged agent eventually stays down instead of thrashing forever.
const RESTART_MAX_RETRIES: i64 = 5;
const ENV_MOUNT_DEST: &str = "/run/vestad-env";
const CORE_MOUNT_DEST: &str = "/root/agent/core";
/// User-authored charter, bind-mounted read-only so the agent reads but cannot edit it.
/// Lives in host config (keyed by agent name), separate from the core-code mount, so
/// agent-code updates never touch it.
pub(crate) const CONSTITUTION_MOUNT_DEST: &str = "/root/agent/constitution.md";
// INVARIANT for any mount destination UNDER /root/agent/: the box's $HOME is a git
// checkout of the workspace snapshot, and a mount puts a file/dir on disk that the
// snapshot does not contain -- so git reports it as untracked ("?? path") noise on every
// box unless it is kept out of git status one of two ways:
//   - a directory: never listed in the sparse cone (agent/core), so it stays out of cone.
//   - a file: gitignored in agent/.gitignore (agent/constitution.md -> `/constitution.md`).
// Adding a new /root/agent/ mount without doing this dirties every box's tree. The
// workspace attach integration test (vestad/tests/server/workspace.rs) asserts a clean
// tree after attach and fails if you forget. (ENV_MOUNT_DEST is under /run, so exempt.)
pub(crate) const MOUNT_DESTS: &[&str] = &[ENV_MOUNT_DEST, CORE_MOUNT_DEST, CONSTITUTION_MOUNT_DEST];

pub(crate) fn agent_container_entrypoint_cmd() -> Vec<String> {
    let steps: [String; 11] = [
        "export PATH=\"/root/.local/bin:/root/.claude/local/bin:$PATH\"".into(),
        // The venv must live outside the read-only core mount (uv would default to
        // /root/agent/core/.venv, inside it).
        "export UV_PROJECT_ENVIRONMENT=/root/agent/.venv".into(),
        ". /run/vestad-env".into(),
        ". ~/.bashrc || true".into(),
        // LEGACY(remove-when: fleet converged to vestad-served workspaces — the workspace
        // branch never tracks .claude, so migrated workspaces cannot hit this):
        // The agent's $HOME is a sparse git checkout of the vesta repo, which tracks dev tooling
        // under .claude/ -- but ~/.claude is ALSO the agent's runtime dir (credentials, sessions).
        // If the git workspace tracks .claude, a `git sparse-checkout reapply` (run by skills-install
        // and by migrations) sparsifies the out-of-cone .claude/ and, on the image's git (2.39),
        // deletes the untracked ~/.claude/.credentials.json with it, de-authing the agent. Self-heal
        // at boot, before the agent runs anything that could reapply: drop .claude from the index and
        // exclude it locally, so .claude is untracked and no reapply can touch it on ANY git version.
        // Same rationale as tmux above -- this is the one place the fix reliably reaches already-
        // snapshotted agents, since the skill scripts only update on a sync (itself a dangerous
        // reapply). No-op outside a git repo (fresh agents before init); `|| true` never aborts boot.
        "if gd=$(git -C ~ rev-parse --absolute-git-dir 2>/dev/null); then git -C ~ ls-files -z -- .claude | xargs -0r git -C ~ update-index --force-remove; grep -qxF '/.claude/' \"$gd/info/exclude\" 2>/dev/null || printf '/.claude/\\n' >> \"$gd/info/exclude\"; fi || true".into(),
        // tmux is a hard runtime dependency of cc_sdk (it drives the real claude TUI in a
        // private tmux server). Fresh images bake it in via the Dockerfile, but `rebuild`
        // recreates a container from a `docker export|import` snapshot and never re-runs the
        // Dockerfile, so an agent snapshotted before tmux was added boots without it and
        // crash-loops on FileNotFoundError deep in cc_sdk. Self-heal at boot: a no-op (no
        // network) once tmux is on PATH, and the next snapshot captures the install so it
        // persists across future rebuilds. `|| true` so a failed install never aborts boot.
        "command -v tmux >/dev/null 2>&1 || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tmux) || true".into(),
        // LEGACY(remove-when: unmanaged boxes have pulled a post-engine-move snapshot):
        // unmanaged boxes keep the old layout (pyproject at /root/agent) until they rebase
        // onto an agent-v* snapshot; tolerate both so they never crash-loop.
        "if [ -f /root/agent/core/pyproject.toml ]; then uv sync --frozen --project /root/agent/core; else uv sync --frozen --project /root/agent; fi".into(),
        // ~/.claude/skills is a real directory of per-skill symlinks. Both
        // /root/agent/skills/ and /root/agent/core/skills/ are flattened in;
        // core entries are linked last so they win any name collision. Reset
        // every boot so uninstalled skills don't leave dangling symlinks.
        "rm -rf ~/.claude/skills && mkdir -p ~/.claude/skills".into(),
        "for d in /root/agent/skills/*/SKILL.md /root/agent/core/skills/*/SKILL.md; do [ -f \"$d\" ] || continue; s=$(dirname \"$d\"); ln -sfn \"$s\" ~/.claude/skills/$(basename \"$s\"); done".into(),
        "test -f ~/.claude/settings.json || printf '{\"permissions\":{\"allow\":[]}}\\n' > ~/.claude/settings.json".into(),
        "cd /root/agent && if [ -f core/pyproject.toml ]; then exec uv run --frozen --project core python -m core.main; else exec uv run --frozen python -m core.main; fi".into(),
    ];
    vec!["sh".into(), "-c".into(), steps.join("; \\\n")]
}

const CONTAINER_STOP_TIMEOUT_SECS: i32 = 10;
const CONTAINER_RESTART_TIMEOUT_SECS: i32 = 10;
/// `docker rm --force` can return before the container name is actually released, and a transient
/// daemon error can leave it present; poll-and-retry until it's gone so a follow-up create under the
/// same name (rebuild_agent) can't collide. Bounded so a genuinely stuck removal fails loudly.
const CONTAINER_REMOVE_MAX_ATTEMPTS: u32 = 5;
const CONTAINER_REMOVE_POLL_MS: u64 = 200;
/// Free space the Docker storage filesystem must have before vestad will rebuild or
/// restart agent containers at startup. Below this, reconcile is skipped entirely so a
/// full disk can't corrupt a container's writable layer (events.db, session) mid-restart.
const MIN_RECONCILE_DISK_BYTES: u64 = 500_000_000; // 500 MB
const LOADED_IMAGE_PREFIX: &str = "Loaded image: ";

// Override bollard's 120s default to absorb slow image builds under CI contention.
const DOCKER_TIMEOUT_SECS: u64 = 600;
#[cfg(unix)]
const DOCKER_SOCKET: &str = "unix:///var/run/docker.sock";
#[cfg(windows)]
const DOCKER_NAMED_PIPE: &str = "npipe:////./pipe/docker_engine";

#[derive(Debug, PartialEq, Clone, Copy)]
pub enum ContainerStatus {
    Running,
    Stopped,
    NotFound,
    Dead,
}

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum AgentStatus {
    Alive,
    /// Authenticated and reachable, but first-start setup hasn't completed yet
    /// (the agent hasn't called `mark_setup_done`). Transient on a fresh agent;
    /// distinct from `Alive` so callers don't treat a half-provisioned agent as ready.
    SettingUp,
    Starting,
    NotAuthenticated,
    /// Reachable, but no provider is chosen yet (fresh agent, or signed out) — needs first sign-in,
    /// distinct from `NotAuthenticated` (a chosen provider whose credential is invalid/expired).
    Unprovisioned,
    Stopped,
    Dead,
    NotFound,
}

impl AgentStatus {
    /// Human-readable form for terminal surfaces (the status banner): the
    /// snake_case wire name with spaces.
    pub fn human_text(self) -> &'static str {
        match self {
            AgentStatus::Alive => "alive",
            AgentStatus::SettingUp => "setting up",
            AgentStatus::Starting => "starting",
            AgentStatus::NotAuthenticated => "not authenticated",
            AgentStatus::Unprovisioned => "unprovisioned",
            AgentStatus::Stopped => "stopped",
            AgentStatus::Dead => "dead",
            AgentStatus::NotFound => "not found",
        }
    }
}

#[derive(Serialize, Clone)]
pub struct StatusJson {
    pub name: String,
    pub status: AgentStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub ws_port: u16,
}

#[derive(Serialize, Clone, PartialEq)]
pub struct ListEntry {
    pub name: String,
    pub status: AgentStatus,
    pub ws_port: u16,
}

// --- Docker connection ---

pub fn connect() -> Result<Docker, DockerError> {
    #[cfg(unix)]
    let result = Docker::connect_with_socket(
        DOCKER_SOCKET,
        DOCKER_TIMEOUT_SECS,
        bollard::API_DEFAULT_VERSION,
    );
    #[cfg(windows)]
    let result = Docker::connect_with_named_pipe(
        DOCKER_NAMED_PIPE,
        DOCKER_TIMEOUT_SECS,
        bollard::API_DEFAULT_VERSION,
    );
    result.map_err(|e| DockerError::Failed(format!("failed to connect to docker: {e}")))
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

/// Strip the `vesta-{user}-` prefix from a container name, falling back to the
/// raw name if it does not match. Modern containers carry the `vesta.agent_name`
/// label and prefer that; this is only used as a fallback in error paths.
pub fn name_from_cname(cname: &str) -> String {
    let user = current_user();
    let user_prefix = format!("vesta-{user}-");
    cname.strip_prefix(&user_prefix).unwrap_or(cname).to_string()
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
        bollard::body_full(Bytes::from(tar_data)),
    ).await?;
    Ok(())
}

pub async fn download_from_container(
    docker: &Docker,
    cname: &str,
    container_path: &str,
) -> Option<String> {
    let stream = docker.download_from_container(cname, Some(DownloadFromContainerOptions {
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
}

pub async fn combined_status(
    http_client: &reqwest::Client,
    agents_dir: &std::path::Path,
    cname: &str,
    info: &ContainerInfo,
) -> AgentStatus {
    match info.status {
        ContainerStatus::Running => {
            // WS port not yet bound → agent still booting.
            if !info.port.is_some_and(is_agent_ready) {
                return AgentStatus::Starting;
            }
            // Agent's own GET /config is the source of truth for provider auth.
            // If the WS server is up but /config isn't responding yet (transient
            // mid-boot state), treat as Starting; the next ~3s poll will resolve.
            let agent_name = name_from_cname(cname);
            let provider = crate::agent_provider::AgentProvider::new(http_client, agents_dir, agent_name);
            match provider.status().await {
                Ok(s) => status_from_readiness(s.authed, s.setup_complete, s.provider_configured),
                Err(_) => AgentStatus::Starting,
            }
        }
        ContainerStatus::Dead => AgentStatus::Dead,
        ContainerStatus::Stopped => AgentStatus::Stopped,
        ContainerStatus::NotFound => AgentStatus::NotFound,
    }
}

/// Map the agent's `GET /status` readiness slice to its `AgentStatus`. An authenticated agent is
/// `SettingUp` until first-start finishes, then `Alive`; a not-authenticated agent is `Unprovisioned`
/// when it has no provider chosen at all, else `NotAuthenticated` (a chosen credential is invalid).
fn status_from_readiness(authed: bool, setup_complete: bool, provider_configured: bool) -> AgentStatus {
    match (authed, setup_complete, provider_configured) {
        (true, true, _) => AgentStatus::Alive,
        (true, false, _) => AgentStatus::SettingUp,
        (false, _, true) => AgentStatus::NotAuthenticated,
        (false, _, false) => AgentStatus::Unprovisioned,
    }
}

/// Read a value from a per-agent env file by key (e.g. "WS_PORT").
pub fn read_env_value(agents_dir: &std::path::Path, agent_name: &str, key: &str) -> Option<String> {
    let env_path = agents_dir.join(format!("{}.env", agent_name));
    let content = std::fs::read_to_string(&env_path).ok()?;
    let prefix = format!("{key}=");
    content
        .lines()
        .map(|line| line.strip_prefix("export ").unwrap_or(line))
        .find_map(|line| line.strip_prefix(&prefix).map(str::to_string))
}

pub(crate) fn container_info_from(cname: &str, info: &bollard::models::ContainerInspectResponse, agents_dir: Option<&std::path::Path>) -> ContainerInfo {
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
    let name = info.config.as_ref()
        .and_then(|c| c.labels.as_ref())
        .and_then(|labels| labels.get(LABEL_AGENT_NAME).cloned())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| name_from_cname(cname));
    let port = agents_dir.and_then(|dir| read_env_value(dir, &name, "WS_PORT"))
        .and_then(|v| v.parse().ok());
    ContainerInfo { status, port, id }
}

pub(crate) async fn inspect_container(docker: &Docker, cname: &str, agents_dir: Option<&std::path::Path>) -> ContainerInfo {
    match docker.inspect_container(cname, None).await {
        Ok(info) => container_info_from(cname, &info, agents_dir),
        Err(_) => ContainerInfo {
            status: ContainerStatus::NotFound,
            port: None,
            id: None,
        },
    }
}

pub async fn container_status(docker: &Docker, cname: &str) -> ContainerStatus {
    inspect_container(docker, cname, None).await.status
}

/// Readiness check: the agent binds its WS port only once it's ready to serve requests.
pub fn is_agent_ready(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(AGENT_READY_TIMEOUT_MS),
    )
    .is_ok()
}

/// Reject the two terminal container states (`NotFound`, `Dead`) with their standard
/// errors, passing a live (`Running`/`Stopped`) status through. The single owner of the
/// "agent not found / broken state" wording and the shared precondition guard every
/// name-addressed lifecycle op repeats; `name` is the agent name used in the error text.
fn guard_alive(status: ContainerStatus, name: &str) -> Result<ContainerStatus, DockerError> {
    match status {
        ContainerStatus::NotFound => Err(DockerError::NotFound(format!("agent '{}' not found", name))),
        ContainerStatus::Dead => Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", name))),
        live => Ok(live),
    }
}

pub async fn ensure_exists(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    guard_alive(container_status(docker, cname).await, &name_from_cname(cname)).map(|_| ())
}

pub async fn ensure_running(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    match guard_alive(container_status(docker, cname).await, &name_from_cname(cname))? {
        ContainerStatus::Running => Ok(()),
        _ => Err(DockerError::NotRunning(format!("agent '{}' is not running", name_from_cname(cname)))),
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

/// Relative path of the Dockerfile from the build context root.
pub const DOCKERFILE_REL: &str = "vestad/Dockerfile";

/// Locate the repo root (build context) by finding `vestad/Dockerfile`.
pub fn find_dockerfile() -> Result<std::path::PathBuf, DockerError> {
    let cwd = std::env::current_dir()
        .map_err(|_| DockerError::BuildRequired("cannot determine working directory".into()))?;
    if cwd.join(DOCKERFILE_REL).exists() {
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
        if d.join(DOCKERFILE_REL).exists() {
            return Ok(d);
        }
        dir = d.parent().map(std::path::Path::to_path_buf);
        depth += 1;
    }
    Err(DockerError::BuildRequired("--build requires vestad to have access to the Vesta source code (run vestad from the repo root, which must contain vestad/Dockerfile)".into()))
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

/// Load and parse dockerignore patterns. Prefers `<dockerfile>.dockerignore`
/// next to the Dockerfile (Docker 20.10+ convention); falls back to a
/// `.dockerignore` at the build context root.
fn load_dockerignore(context: &std::path::Path) -> Vec<String> {
    let content = std::fs::read_to_string(context.join(format!("{DOCKERFILE_REL}.dockerignore")))
        .or_else(|_| std::fs::read_to_string(context.join(".dockerignore")))
        .unwrap_or_default();
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

pub async fn resolve_image(docker: &Docker, progress: &BuildProgress) -> Result<String, DockerError> {
    if let Ok(image) = std::env::var(AGENT_IMAGE_ENV) {
        tracing::info!(image = %image, "using agent image from {AGENT_IMAGE_ENV}");
        progress.set(BuildPhase::Pulling);
        verify_image_runnable(&image).await?;
        return Ok(image);
    }
    if let Ok(context) = find_dockerfile() {
        progress.set(BuildPhase::Building);
        let tar_body = build_context_tar(&context)?;
        let opts = BuildImageOptions {
            t: Some(LOCAL_IMAGE_TAG.to_string()),
            dockerfile: DOCKERFILE_REL.to_string(),
            q: true,
            rm: true,
            ..Default::default()
        };
        let mut stream = docker.build_image(opts, None, Some(bollard::body_full(tar_body)));
        while let Some(msg) = stream.next().await {
            match msg {
                Err(e) => return Err(DockerError::Failed(format!("image build failed: {e}"))),
                Ok(info) => {
                    if let Some(err) = info.error_detail.and_then(|d| d.message) {
                        return Err(DockerError::Failed(format!("image build failed: {err}")));
                    }
                }
            }
        }
        verify_image_runnable(LOCAL_IMAGE_TAG).await?;
        Ok(LOCAL_IMAGE_TAG.to_string())
    } else {
        progress.set(BuildPhase::Pulling);
        let image = vesta_image();
        let opts = CreateImageOptions {
            from_image: Some(image.clone()),
            ..Default::default()
        };
        let mut stream = docker.create_image(Some(opts), None, None);
        while let Some(msg) = stream.next().await {
            if let Err(e) = msg {
                return Err(DockerError::Failed(format!("failed to pull image: {e}")));
            }
        }
        verify_image_runnable(&image).await?;
        Ok(image)
    }
}

fn all_agent_ports(agents_dir: &std::path::Path) -> HashSet<u16> {
    env_file_names(agents_dir)
        .iter()
        .filter_map(|name| read_env_value(agents_dir, name, "WS_PORT")?.parse().ok())
        .collect()
}

/// List agent names that have env files in the agents directory.
pub(crate) fn env_file_names(agents_dir: &std::path::Path) -> Vec<String> {
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
    let Ok(content) = std::fs::read_to_string(&env_path) else {
        return (None, None);
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

/// Validate that the config and agents directories exist, are writable, and have
/// no stale entries (e.g. directories where files should be). Fails fast with a
/// clear error instead of producing cryptic permission errors later.
pub fn validate_config_dir(env_config: &AgentEnvConfig) -> Result<(), DockerError> {
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
    let mut append_optional = |key: &str, value: Option<&str>| {
        if let Some(v) = value {
            content.push_str(&format!("export {key}={v}\n"));
        }
    };
    append_optional("VESTAD_TUNNEL", env_config.vestad_tunnel.as_deref());
    // The control-plane base URL the agent's account/onboard skills call. Comes
    // from vestad's own env (the cloud-init managed.conf drop-in); absent on
    // self-hosted boxes. (The referral code is NOT forwarded here: it lives with
    // the control plane and the account skill reads it via GET /api/account.)
    append_optional(
        "VESTA_CLOUD_CONTROL_URL",
        std::env::var("VESTA_CLOUD_CONTROL_URL").ok().as_deref(),
    );
    // The env carries only identity; the agent owns model/provider/personality, timezone, and provider
    // auth in its config store (preferences) and .credentials.json (Claude OAuth blob).
    if std::fs::read_to_string(&env_path).map(|prev| prev == content).unwrap_or(false) {
        return Ok(env_path);
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

/// Host path of an agent's constitution. Per-agent user data, separate from agent code,
/// so it survives code updates, rebuilds, and container destroy/restore.
pub fn constitution_host_path(agents_dir: &std::path::Path, agent_name: &str) -> std::path::PathBuf {
    agents_dir.join(format!("{}.constitution.md", agent_name))
}

/// Ensure the constitution file exists (empty by default) so it can be bind-mounted as a
/// file. Bind-mounting a missing host path would make Docker create a directory there.
fn ensure_constitution_file(agents_dir: &std::path::Path, agent_name: &str) -> Result<std::path::PathBuf, DockerError> {
    std::fs::create_dir_all(agents_dir)
        .map_err(|e| DockerError::Failed(format!("failed to create agents dir: {e}")))?;
    let path = constitution_host_path(agents_dir, agent_name);
    if !path.exists() {
        std::fs::write(&path, "")
            .map_err(|e| DockerError::Failed(format!("failed to create constitution file: {e}")))?;
    }
    Ok(path)
}

/// Read an agent's constitution, returning an empty string when unset.
pub fn read_constitution(agents_dir: &std::path::Path, agent_name: &str) -> Result<String, DockerError> {
    let path = constitution_host_path(agents_dir, agent_name);
    match std::fs::read_to_string(&path) {
        Ok(content) => Ok(content),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        Err(e) => Err(DockerError::Failed(format!("failed to read constitution: {e}"))),
    }
}

/// Overwrite an agent's constitution in place. Writing in place (rather than rename) keeps
/// the inode stable so the read-only bind mount in a running container sees the new content;
/// the agent only re-reads it into its system prompt on restart.
pub fn write_constitution(agents_dir: &std::path::Path, agent_name: &str, content: &str) -> Result<(), DockerError> {
    let path = ensure_constitution_file(agents_dir, agent_name)?;
    std::fs::write(&path, content)
        .map_err(|e| DockerError::Failed(format!("failed to write constitution: {e}")))
}

fn delete_constitution_file(agents_dir: &std::path::Path, agent_name: &str) {
    std::fs::remove_file(constitution_host_path(agents_dir, agent_name)).ok();
}

/// Update VESTAD_PORT and VESTAD_TUNNEL in all existing per-agent env files.
/// Called at vestad startup so running containers pick up the new values on restart.
pub fn update_all_agent_env_files(agents_dir: &std::path::Path, vestad_port: u16, vestad_tunnel: Option<&str>) {
    for name in env_file_names(agents_dir) {
        let path = agents_dir.join(format!("{name}.env"));
        let Ok(content) = std::fs::read_to_string(&path) else { continue };
        // LEGACY(remove-when: no agent env file carries AGENT_SEED_PERSONALITY): rename it to
        // AGENT_PERSONALITY in place, value-preserving, so the agent keeps the chosen voice.
        let has_new_personality = content
            .lines()
            .any(|line| line.strip_prefix("export ").unwrap_or(line).starts_with("AGENT_PERSONALITY="));
        let mut new_lines: Vec<String> = content
            .lines()
            .filter_map(|line| {
                let stripped = line.strip_prefix("export ").unwrap_or(line);
                // LEGACY(remove-when: no agent env file carries VESTA_UPSTREAM_REF or
                // VESTA_WORKSPACE_REF): the workspace ref moved out of env entirely (boxes
                // fetch a bundle from vestad; no branch name needed) - strip stale keys.
                if stripped.starts_with("VESTAD_PORT=") || stripped.starts_with("VESTAD_TUNNEL=") || stripped.starts_with("VESTA_WORKSPACE_REF=") || stripped.starts_with("VESTA_UPSTREAM_REF=") {
                    return None; // re-appended below with the current values
                }
                if stripped.starts_with("AGENT_SEED_PERSONALITY=") {
                    if has_new_personality {
                        return None; // already migrated; drop the stale duplicate
                    }
                    return Some(line.replacen("AGENT_SEED_PERSONALITY=", "AGENT_PERSONALITY=", 1));
                }
                Some(line.to_string())
            })
            .collect();
        new_lines.push(format!("export VESTAD_PORT={vestad_port}"));
        if let Some(url) = vestad_tunnel {
            new_lines.push(format!("export VESTAD_TUNNEL={url}"));
        }
        new_lines.push(String::new());
        let new_content = new_lines.join("\n");
        if new_content == content {
            continue;
        }
        std::fs::write(&path, new_content).ok();
    }
}

// --- Container listing ---

pub struct ManagedAgent {
    pub cname: String,
    pub agent_name: String,
}

/// List all managed containers owned by the current user, paired with the
/// agent name derived from the `vesta.agent_name` label (falling back to the
/// legacy `vesta-{user}-{agent}` naming scheme). One Docker call total.
pub async fn list_managed_agents(docker: &Docker) -> Vec<ManagedAgent> {
    let mut filters = HashMap::new();
    filters.insert("label".to_string(), vec!["vesta.managed=true".to_string()]);

    let opts = ListContainersOptions {
        all: true,
        filters: Some(filters),
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
            let cname = names.first()?.strip_prefix('/')?.to_string();
            let labels = c.labels.unwrap_or_default();
            let owner = labels.get(LABEL_USER).cloned().unwrap_or_default();
            if owner != user {
                return None;
            }
            let agent_name = labels
                .get(LABEL_AGENT_NAME)
                .cloned()
                .filter(|s| !s.trim().is_empty())
                .unwrap_or_else(|| name_from_cname(&cname));
            Some(ManagedAgent { cname, agent_name })
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

    let has_runtime = docker
        .info()
        .await
        .ok()
        .and_then(|info| info.runtimes)
        .map(|runtimes| runtimes.contains_key("nvidia"))
        .unwrap_or(false);

    if has_runtime { GpuStatus::Ready } else { GpuStatus::NoRuntime }
}

// --- Container lifecycle helpers (used by backup.rs) ---

pub async fn stop_container_with_timeout(docker: &Docker, cname: &str, timeout_secs: i32) -> Result<(), DockerError> {
    docker.stop_container(cname, Some(StopContainerOptions { t: Some(timeout_secs), signal: None })).await?;
    Ok(())
}

pub async fn start_container(docker: &Docker, cname: &str) -> bool {
    docker.start_container(cname, None).await.is_ok()
}

/// Ensure a container carries the `on-failure:N` restart policy, updating in place (`docker
/// update`, no recreate) only when it differs. Migrates legacy `unless-stopped` agents at reconcile
/// without a snapshot. `unless-stopped` would auto-start the container on daemon boot, which would
/// defeat vestad owning boot-start; `on-failure` recovers crashes but never auto-starts on boot.
pub async fn ensure_on_failure_policy(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    if container_restart_policy(docker, cname).await == "on-failure" {
        return Ok(());
    }
    let update = bollard::models::ContainerUpdateBody {
        restart_policy: Some(bollard::models::RestartPolicy {
            name: Some(bollard::models::RestartPolicyNameEnum::ON_FAILURE),
            maximum_retry_count: Some(RESTART_MAX_RETRIES),
        }),
        ..Default::default()
    };
    tracing::info!(container = %cname, "migrating restart policy to on-failure");
    docker.update_container(cname, update).await.map_err(DockerError::from)
}

/// Read a container's current restart-policy name (lowercased + hyphenated, e.g. "on-failure" /
/// "unless-stopped"), or empty if unset.
pub async fn container_restart_policy(docker: &Docker, cname: &str) -> String {
    docker.inspect_container(cname, None).await.ok()
        .and_then(|info| info.host_config)
        .and_then(|h| h.restart_policy)
        .and_then(|r| r.name)
        .map(|n| format!("{n:?}").to_lowercase().replace('_', "-"))
        .unwrap_or_default()
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
        .map(|r| r.map(|b| b.freeze()));

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


pub async fn container_size_rw(docker: &Docker, cname: &str) -> Option<u64> {
    let info = docker.inspect_container(cname, Some(InspectContainerOptions { size: true })).await.ok()?;
    info.size_rw.map(|s| s as u64)
}

/// Total size of the container's root filesystem (image layers + writable layer).
/// This is what `docker export` streams out, so it's the right basis for sizing
/// the first, full restic snapshot.
pub async fn container_size_root_fs(docker: &Docker, cname: &str) -> Option<u64> {
    let info = docker.inspect_container(cname, Some(InspectContainerOptions { size: true })).await.ok()?;
    info.size_root_fs.map(|s| s as u64)
}

pub async fn container_created(docker: &Docker, cname: &str) -> Option<String> {
    let info = docker.inspect_container(cname, None).await.ok()?;
    info.created
}

pub async fn remove_container_force(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    docker.remove_container(cname, Some(RemoveContainerOptions { force: true, v: false, link: false })).await?;
    Ok(())
}

/// Force-remove a container and confirm it is actually gone before returning. Needed when the name
/// is reused immediately after (rebuild_agent recreates under the same name): a bare force-remove
/// can return before the name frees, and a transient daemon error can leave the container present —
/// either makes the follow-up create collide on the name and silently leaves the agent down. Retry
/// the remove and poll until docker no longer reports it; error out loudly if it never disappears
/// rather than letting the caller hit a confusing name conflict.
pub async fn ensure_container_removed(docker: &Docker, cname: &str) -> Result<(), DockerError> {
    for _ in 0..CONTAINER_REMOVE_MAX_ATTEMPTS {
        if container_status(docker, cname).await == ContainerStatus::NotFound {
            return Ok(());
        }
        // Per-attempt remove is best-effort: the authoritative signal is the status check above, so
        // a transient error just means we retry; a persistent one falls through to the loud error.
        let _ = docker.remove_container(cname, Some(RemoveContainerOptions { force: true, v: false, link: false })).await;
        tokio::time::sleep(std::time::Duration::from_millis(CONTAINER_REMOVE_POLL_MS)).await;
    }
    if container_status(docker, cname).await == ContainerStatus::NotFound {
        return Ok(());
    }
    Err(DockerError::Failed(format!(
        "container {cname} still present after {CONTAINER_REMOVE_MAX_ATTEMPTS} force-remove attempts"
    )))
}

// --- Snapshot ---

const SNAPSHOT_TIMEOUT_SECS: u64 = 7200; // 2 hours — 25GB+ containers can take a long time
const IMPORT_PIPELINE_MAX_ATTEMPTS: u32 = 3;
const IMPORT_PIPELINE_RETRY_DELAY_SECS: u64 = 3;

/// Retry a self-contained `docker import` pipeline (`docker export | docker import`
/// or `restic dump | docker import`). These occasionally fail mid-stream with a
/// transient daemon error such as "unexpected EOF"; each attempt rebuilds the
/// image from scratch, so retrying is safe. Runs inside `spawn_blocking`, so the
/// blocking sleep between attempts is fine.
pub(crate) fn retry_import_pipeline<F>(label: &str, mut attempt: F) -> Result<(), DockerError>
where
    F: FnMut() -> Result<(), DockerError>,
{
    let mut tries = 0;
    loop {
        tries += 1;
        match attempt() {
            Ok(()) => return Ok(()),
            Err(e) if tries < IMPORT_PIPELINE_MAX_ATTEMPTS => {
                tracing::warn!(
                    "{label} attempt {tries}/{IMPORT_PIPELINE_MAX_ATTEMPTS} failed, retrying in {IMPORT_PIPELINE_RETRY_DELAY_SECS}s: {e}"
                );
                std::thread::sleep(std::time::Duration::from_secs(IMPORT_PIPELINE_RETRY_DELAY_SECS));
            }
            Err(e) => return Err(e),
        }
    }
}

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
            retry_import_pipeline("docker snapshot", || {
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
                import_args.push(tag.clone());

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
            })
        }),
    )
    .await
    .map_err(|_| DockerError::Failed(format!("snapshot timed out after {SNAPSHOT_TIMEOUT_SECS}s")))?
    .map_err(|e| DockerError::Failed(format!("snapshot task failed: {e}")))?
}

// --- Container creation ---

#[allow(clippy::too_many_arguments)]
pub async fn create_container(docker: &Docker, cname: &str, image: &str, port: u16, agent_name: &str, env_config: &AgentEnvConfig, manage_core_code: bool) -> Result<(), DockerError> {
    let agent_token = generate_agent_token();
    let env_path = write_agent_env_file(env_config, agent_name, port, &agent_token)?;
    let env_mount = format!("{}:{}:ro,z", env_path.display(), ENV_MOUNT_DEST);

    let constitution_path = ensure_constitution_file(&env_config.agents_dir, agent_name)?;
    let constitution_mount = format!("{}:{}:ro,z", constitution_path.display(), CONSTITUTION_MOUNT_DEST);

    let code_dir = crate::agent_code::agent_code_dir(&env_config.config_dir);
    let core_mount = format!("{}:{}:ro,z", code_dir.join("core").display(), CORE_MOUNT_DEST);

    let mut labels = HashMap::new();
    labels.insert("vesta.managed".to_string(), "true".to_string());
    labels.insert(LABEL_USER.to_string(), current_user());
    labels.insert(LABEL_AGENT_NAME.to_string(), agent_name.to_string());

    let mut binds = vec![env_mount, constitution_mount];
    if manage_core_code {
        binds.push(core_mount);
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
            name: Some(bollard::models::RestartPolicyNameEnum::ON_FAILURE),
            maximum_retry_count: Some(RESTART_MAX_RETRIES),
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

    let config = ContainerCreateBody {
        image: Some(image.to_string()),
        tty: Some(true),
        labels: Some(labels),
        cmd: Some(agent_container_entrypoint_cmd()),
        working_dir: Some("/root".to_string()),
        host_config: Some(host_config),
        ..Default::default()
    };

    let create_opts = CreateContainerOptions {
        name: Some(cname.to_string()),
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
    let parent = path.parent().and_then(|p| p.to_str()).unwrap_or("/");
    let file_name = path.file_name().and_then(|f| f.to_str()).unwrap_or("file");
    upload_to_container(docker, container, parent, file_name, content.as_bytes()).await
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
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(data)
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

/// Start the OAuth PKCE flow. Returns (auth_url, code_verifier, state).
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
        .timeout(std::time::Duration::from_secs(OAUTH_HTTP_TIMEOUT_SECS))
        .json(&body)
        .send()
        .await
        .map_err(|e| {
            if e.is_timeout() {
                DockerError::Failed(format!("token exchange timed out after {OAUTH_HTTP_TIMEOUT_SECS}s"))
            } else {
                DockerError::Failed(format!("token exchange request failed: {e}"))
            }
        })?;

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

    let expires_at = crate::time_utils::now_epoch_millis() + (expires_in as u128) * 1000;

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

pub async fn get_status(
    docker: &Docker,
    http_client: &reqwest::Client,
    name: &str,
    agents_dir: &std::path::Path,
) -> Result<StatusJson, DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let info = inspect_container(docker, &cname, Some(agents_dir)).await;

    Ok(StatusJson {
        name: name.to_string(),
        status: combined_status(http_client, agents_dir, &cname, &info).await,
        id: info.id,
        ws_port: info.port.unwrap_or(0),
    })
}

pub async fn list_agents(
    docker: &Docker,
    http_client: &reqwest::Client,
    agents_dir: &std::path::Path,
) -> Vec<ListEntry> {
    let agents = list_managed_agents(docker).await;
    let mut entries = Vec::new();
    for ManagedAgent { cname, agent_name } in &agents {
        let info = inspect_container(docker, cname, Some(agents_dir)).await;
        entries.push(ListEntry {
            name: agent_name.clone(),
            status: combined_status(http_client, agents_dir, cname, &info).await,
            ws_port: info.port.unwrap_or(0),
        });
    }
    entries
}

/// Coarse, user-facing stage of first-time agent creation, emitted in order so the
/// onboarding UI can show honest status instead of a decorative loop. The dominant
/// wait is the image step (`Pulling` on a release, `Building` from a local checkout).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BuildPhase {
    Pulling,
    Building,
    Preparing,
    Creating,
    Starting,
}

/// A cheap, clonable sink for `BuildPhase` updates. The create handler wires one
/// that records into shared state for the build-phase endpoint.
#[derive(Clone)]
pub struct BuildProgress {
    sink: std::sync::Arc<dyn Fn(BuildPhase) + Send + Sync>,
}

impl BuildProgress {
    pub fn new(sink: std::sync::Arc<dyn Fn(BuildPhase) + Send + Sync>) -> Self {
        Self { sink }
    }

    pub fn set(&self, phase: BuildPhase) {
        (self.sink)(phase);
    }
}

impl std::fmt::Debug for BuildProgress {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BuildProgress").finish_non_exhaustive()
    }
}

#[allow(clippy::too_many_arguments)]
pub async fn create_agent(docker: &Docker, name: &str, env_config: &AgentEnvConfig, manage_core_code: bool, progress: &BuildProgress) -> Result<String, DockerError> {
    let name = if name == "ignisinextinctus" { "vesta" } else { name };
    validate_name(name)?;
    if name != "vesta" && name.contains("vesta") {
        return Err(DockerError::InvalidName("agent name must not contain 'vesta'".into()));
    }
    let cname = container_name(name);

    if container_status(docker, &cname).await != ContainerStatus::NotFound {
        return Err(DockerError::AlreadyExists(format!("agent '{}' already exists", name)));
    }

    let image = resolve_image(docker, progress).await?;

    progress.set(BuildPhase::Preparing);
    if manage_core_code {
        tracing::info!(agent = %name, "ensuring agent code");
        crate::agent_code::ensure_agent_code(&env_config.config_dir)
            .map_err(|e| DockerError::Failed(format!("agent code: {e}")))?;
    }

    progress.set(BuildPhase::Creating);
    let port = allocate_port(&env_config.agents_dir)?;
    create_container(docker, &cname, &image, port, name, env_config, manage_core_code).await?;

    Ok(name.to_string())
}

pub async fn start_agent(docker: &Docker, name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    if guard_alive(container_status(docker, &cname).await, name)? == ContainerStatus::Running {
        return Ok(());
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
    let mut results = Vec::new();
    for ManagedAgent { cname, agent_name } in list_managed_agents(docker).await {
        let ok = container_status(docker, &cname).await == ContainerStatus::Running
            || start_container(docker, &cname).await;
        let error = (!ok).then(|| "failed to start".to_string());
        results.push(StartAllResult { name: agent_name, ok, error });
    }
    results
}

pub async fn stop_agent(docker: &Docker, name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    if guard_alive(container_status(docker, &cname).await, name)? == ContainerStatus::Stopped {
        return Ok(());
    }
    docker.stop_container(&cname, Some(StopContainerOptions { t: Some(CONTAINER_STOP_TIMEOUT_SECS), signal: None })).await?;
    Ok(())
}

/// Stop every running managed agent (best-effort, graceful). Called on vestad's own shutdown so a
/// vestad update/restart never leaves an agent running on a soon-to-be-stale container: the next
/// vestad boot rebuilds-then-starts the desired-running ones. The graceful stop (SIGTERM, then the
/// stop timeout) lets each agent flush its SQLite/state before exit. Desired-state is untouched —
/// these agents come back on the next boot unless the user marked them stopped.
pub async fn stop_all_agents(docker: &Docker) {
    for ManagedAgent { cname, agent_name } in list_managed_agents(docker).await {
        if container_status(docker, &cname).await == ContainerStatus::Running {
            tracing::info!(agent = %agent_name, "stopping for vestad shutdown");
            docker.stop_container(&cname, Some(StopContainerOptions { t: Some(CONTAINER_STOP_TIMEOUT_SECS), signal: None })).await.ok();
        }
    }
}

pub async fn restart_agent(docker: &Docker, name: &str) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    ensure_exists(docker, &cname).await?;
    docker.restart_container(&cname, Some(RestartContainerOptions { t: Some(CONTAINER_RESTART_TIMEOUT_SECS), signal: None })).await?;
    Ok(())
}

/// Free space (in bytes) on the filesystem backing `path`, or `None` if it can't be read.
fn available_disk_bytes(path: &std::path::Path) -> Option<u64> {
    let stat = nix::sys::statvfs::statvfs(path).ok()?;
    Some(stat.blocks_available() * stat.fragment_size())
}

/// Free space on Docker's storage filesystem (where container writable layers live), or
/// `None` if Docker doesn't report a root dir or it can't be stat'd. We probe Docker's
/// actual data-root rather than assuming `/` so the guard is accurate when Docker stores
/// containers on a separate volume.
async fn docker_storage_available_bytes(docker: &Docker) -> Option<u64> {
    let root = docker.info().await.ok()?.docker_root_dir?;
    available_disk_bytes(std::path::Path::new(&root))
}

/// Whether reconcile must be skipped given the free space probe. Unknown free space
/// (`None`) proceeds, so a probe failure never locks out normal operation.
fn reconcile_blocked_by_disk(available: Option<u64>) -> bool {
    matches!(available, Some(bytes) if bytes < MIN_RECONCILE_DISK_BYTES)
}

/// Ensure all containers match expected config and running agents are restarted.
/// Called once at startup after agent code and env files are ready.
/// `agent_code_changed` is true when this boot re-extracted the embedded core (see
/// `agent_code_is_stale`); running core-mounted agents are restarted to reload it.
/// `manages_core_code` returns whether a given agent name has vestad-managed core code mounts (default true).
pub async fn reconcile_containers(
    docker: &Docker,
    env_config: &AgentEnvConfig,
    agent_code_changed: bool,
    manages_core_code: &(dyn Fn(&str) -> bool + Send + Sync),
    wants_running: &(dyn Fn(&str) -> bool + Send + Sync),
) {
    let agents = list_managed_agents(docker).await;
    if agents.is_empty() {
        return;
    }

    // Skip REBUILDS when the disk is critically full: a snapshot (docker export|import) writes a
    // whole image and a failure mid-rebuild can corrupt an agent's writable layer (events.db,
    // session_id). Starting an existing container is not write-heavy, so boot-start still runs —
    // important now that vestad owns boot-start (on-failure never auto-starts on daemon boot), or a
    // disk-full boot would leave every agent down. If Docker doesn't report free space, proceed.
    let available = docker_storage_available_bytes(docker).await;
    let disk_ok = !reconcile_blocked_by_disk(available);
    if !disk_ok {
        tracing::error!(
            available_mb = available.unwrap_or(0) / 1_000_000,
            required_mb = MIN_RECONCILE_DISK_BYTES / 1_000_000,
            "insufficient disk space, skipping rebuilds (still starting agents); rebuilds retry next boot once space is freed"
        );
    }

    // Phase 1: ensure env files exist
    for ManagedAgent { cname, agent_name: name } in &agents {
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
                if let Err(e) = write_agent_env_file(env_config, name, port, &token) {
                    tracing::error!(agent = %name, error = %e, "failed to create env file");
                }
            } else {
                tracing::error!(agent = %name, "could not determine or allocate port for env file");
            }
        }
    }

    // Phase 2: rebuild containers with wrong config (skipped when disk is critically full — see the
    // guard above). Uses container-derived mount topology (not settings) so a stale settings.json
    // can't redirect the rebuild into wiping bind-mounted core code.
    let mut agent_code_ok = false;
    for ManagedAgent { cname, agent_name: name } in &agents {
        let raw = match docker.inspect_container(cname, None).await {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!(agent = %name, error = %e, "skipping reconcile: inspect failed");
                continue;
            }
        };
        let has_core_mounts = mounts_have_core_code(raw.mounts.as_deref().unwrap_or(&[]));
        let settings_says = manages_core_code(name);
        if has_core_mounts != settings_says {
            tracing::warn!(
                agent = %name,
                settings_says,
                container_has_core_mounts = has_core_mounts,
                "settings.manage_agent_code disagrees with container, using container as source of truth. fix by destroying and recreating the agent."
            );
        }
        if !needs_rebuild(cname, &raw) {
            tracing::info!(agent = %name, "config ok, no rebuild needed");
            continue;
        }
        if !disk_ok {
            tracing::warn!(agent = %name, "rebuild needed but disk is full; deferring rebuild to next boot");
            continue;
        }
        tracing::info!(agent = %name, "rebuild needed");
        if has_core_mounts && !agent_code_ok {
            match crate::agent_code::ensure_agent_code(&env_config.config_dir) {
                Ok(_) => agent_code_ok = true,
                Err(e) => {
                    tracing::error!(error = %e, "failed to ensure agent code, skipping rebuilds");
                    break;
                }
            }
        }
        match rebuild_agent(docker, name, env_config).await {
            Ok(()) => tracing::info!(agent = %name, "rebuild complete"),
            Err(e) => tracing::error!(agent = %name, error = %e, "rebuild failed"),
        }
    }

    // Phase 3: bring container state in line with the user's desired-run state. vestad owns
    // boot-start now — `on-failure` never auto-starts a container on daemon boot — so this is
    // where desired-running agents come up. Rebuilds already happened in phase 2, so a
    // needs-rebuild agent is started only after it's on its new container (never stale). First
    // migrate every agent's policy to on-failure in place (legacy agents created with
    // unless-stopped would otherwise let Docker auto-start them on the next boot, defeating
    // vestad's ownership); then start the desired-running ones that are down and stop any
    // user-stopped one that's somehow up.
    for ManagedAgent { cname, agent_name: name } in &agents {
        if let Err(e) = ensure_on_failure_policy(docker, cname).await {
            tracing::warn!(agent = %name, error = %e, "failed to set on-failure restart policy");
        }
        let raw = docker.inspect_container(cname, None).await.ok();
        let running = raw.as_ref().and_then(|r| r.state.as_ref()).and_then(|s| s.running).unwrap_or(false);
        let has_core_mount = raw.as_ref().map(|r| mounts_have_core_code(r.mounts.as_deref().unwrap_or(&[]))).unwrap_or(false);
        if wants_running(name) {
            if !running {
                tracing::info!(agent = %name, "starting (desired running)");
                start_container(docker, cname).await;
            } else if agent_code_changed && has_core_mount {
                // vestad re-extracted the embedded core this boot. A running agent still holds the
                // old code in memory and its core mount points at the now-replaced dir, so restart
                // it to reload the new core and re-bind the mount. (Boot-started agents above came
                // up fresh already; this catches agents that stayed running across the upgrade.)
                tracing::info!(agent = %name, "restarting to pick up new agent code");
                docker.restart_container(cname, Some(RestartContainerOptions { t: Some(CONTAINER_RESTART_TIMEOUT_SECS), signal: None })).await.ok();
            }
        } else if running {
            tracing::info!(agent = %name, "stopping (user-stopped)");
            docker.stop_container(cname, Some(StopContainerOptions { t: Some(CONTAINER_STOP_TIMEOUT_SECS), signal: None })).await.ok();
        }
    }

    // Summary: log which agents are running after reconciliation
    let mut running = Vec::new();
    let mut stopped = Vec::new();
    for ManagedAgent { cname, agent_name: name } in &agents {
        if container_status(docker, cname).await == ContainerStatus::Running {
            running.push(name.clone());
        } else {
            stopped.push(name.clone());
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
    if guard_alive(container_status(docker, &cname).await, name)? == ContainerStatus::Running {
        docker.stop_container(&cname, Some(StopContainerOptions { t: Some(CONTAINER_STOP_TIMEOUT_SECS), signal: None })).await.ok();
    }
    remove_container_force(docker, &cname).await?;
    delete_agent_env_file(agents_dir, name);
    delete_constitution_file(agents_dir, name);
    crate::restic::remove_repo(name);
    Ok(())
}

/// Returns whether the container's mount list includes the core-code bind mount. This
/// is the source of truth for `manage_agent_code` post-creation: settings.json may drift
/// via hand-edits, but the container's mount config reflects how it was actually created.
fn mounts_have_core_code(mounts: &[bollard::models::MountPoint]) -> bool {
    mounts.iter().any(|m| m.destination.as_deref() == Some(CORE_MOUNT_DEST))
}

/// Check if a container's config diverges from what create_container would produce.
/// Operates on a pre-fetched inspect response so callers can do one Docker round-trip
/// even when they also need other fields (mount topology, port, status). Mount
/// divergence is intentionally NOT a trigger here: it's reported by reconcile as a
/// warning. See `rebuild_agent` for why mount topology must come from the container,
/// not from settings.
fn needs_rebuild(cname: &str, info: &bollard::models::ContainerInspectResponse) -> bool {
    let mounts = info.mounts.as_deref().unwrap_or(&[]);
    let mount_dests: Vec<&str> = mounts.iter()
        .filter_map(|m| m.destination.as_deref())
        .collect();

    if !mount_dests.contains(&ENV_MOUNT_DEST) {
        tracing::info!(container = %cname, "rebuild needed: missing env-file mount");
        return true;
    }

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

    let network = info.host_config.as_ref()
        .and_then(|h| h.network_mode.as_deref())
        .unwrap_or("");
    if network != NETWORK_MODE {
        tracing::info!(container = %cname, actual = network, expected = NETWORK_MODE, "rebuild needed: wrong network mode");
        return true;
    }

    // Restart policy is intentionally NOT a rebuild trigger: it doubles as the persisted
    // desired-run marker (on-failure = running, no = user-stopped) and is reconciled in place
    // with `docker update` (set_restart_policy), so a policy change never costs a snapshot.

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

    let caps = info.host_config.as_ref()
        .and_then(|h| h.cap_add.as_deref())
        .unwrap_or(&[]);
    if !caps.iter().any(|c| c == "SYS_ADMIN") {
        tracing::info!(container = %cname, "rebuild needed: missing SYS_ADMIN capability");
        return true;
    }

    false
}

/// Resolve an existing agent's WS port for a snapshot-and-recreate: prefer the env-file
/// port, fall back to the container's baked-in WS_PORT, then allocate a fresh one.
async fn resolve_existing_port(docker: &Docker, cname: &str, info: &ContainerInfo, name: &str, agents_dir: &std::path::Path) -> Result<u16, DockerError> {
    let baked = read_container_env(docker, cname, "WS_PORT").await.and_then(|v| v.parse::<u16>().ok());
    match info.port.or(baked) {
        Some(port) => Ok(port),
        None => {
            tracing::warn!(agent = %name, "no port found in env file or container, allocating new port");
            allocate_port(agents_dir)
        }
    }
}

/// Recreate a container with the latest container config (entrypoint, mounts, env file)
/// while preserving the filesystem. Snapshots the old container, removes it, and creates
/// a new one from the snapshot. Mount topology is preserved from the existing container,
/// not re-derived from settings: `manage_agent_code` is fixed at create time, so the
/// running container is the source of truth for which bind mounts to attach.
pub async fn rebuild_agent(docker: &Docker, name: &str, env_config: &AgentEnvConfig) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    let raw = docker.inspect_container(&cname, None).await.map_err(DockerError::from)?;
    let info = container_info_from(&cname, &raw, Some(&env_config.agents_dir));
    guard_alive(info.status, name)?;

    let manage_core_code = mounts_have_core_code(raw.mounts.as_deref().unwrap_or(&[]));

    let port = resolve_existing_port(docker, &cname, &info, name, &env_config.agents_dir).await?;

    let ts = crate::time_utils::now_epoch_secs();
    let backup_tag = format!("vesta-rebuild:{}_{}", name, ts);

    // Stop cleanly so the snapshot captures a quiesced filesystem (SQLite mid-write would
    // be the main concern). Best-effort — snapshot will still proceed if stop fails.
    if info.status == ContainerStatus::Running {
        tracing::info!(agent = %name, "[1/4] stopping container...");
        docker.stop_container(&cname, Some(StopContainerOptions { t: Some(CONTAINER_STOP_TIMEOUT_SECS), signal: None })).await.ok();
    }

    tracing::info!(agent = %name, "[2/4] snapshotting container filesystem...");
    snapshot_container(docker, &cname, &backup_tag, &[]).await?;

    tracing::info!(agent = %name, "[3/4] removing old container...");
    // Confirm it's actually gone (don't swallow): the snapshot is safely captured, so failing here
    // and re-running reconcile next boot is far better than letting [4/4] collide on the name and
    // leave the agent stopped.
    ensure_container_removed(docker, &cname).await?;

    tracing::info!(agent = %name, "[4/4] creating container with new config...");
    create_container(docker, &cname, &backup_tag, port, name, env_config, manage_core_code).await?;

    Ok(())
}

/// Rename an agent: snapshot the existing container, destroy it, then create a fresh
/// container from the snapshot under the new name. Preserves the in-container filesystem
/// (events.db, session_id, prompts, ~/.claude auth) but rewrites the env file with the
/// new AGENT_NAME and a fresh AGENT_TOKEN. Caller updates settings.json keys and starts
/// the new container.
pub async fn rename_agent(
    docker: &Docker,
    old_name: &str,
    new_name: &str,
    env_config: &AgentEnvConfig,
) -> Result<(), DockerError> {
    validate_name(old_name)?;
    validate_name(new_name)?;
    if old_name == new_name {
        return Err(DockerError::InvalidName("new name must differ from old name".into()));
    }
    if new_name != "vesta" && new_name.contains("vesta") {
        return Err(DockerError::InvalidName("agent name must not contain 'vesta'".into()));
    }

    let old_cname = container_name(old_name);
    let new_cname = container_name(new_name);

    if container_status(docker, &old_cname).await == ContainerStatus::NotFound {
        return Err(DockerError::NotFound(format!("agent '{}' not found", old_name)));
    }
    if container_status(docker, &new_cname).await != ContainerStatus::NotFound {
        return Err(DockerError::AlreadyExists(format!("agent '{}' already exists", new_name)));
    }

    let raw = docker.inspect_container(&old_cname, None).await.map_err(DockerError::from)?;
    let info = container_info_from(&old_cname, &raw, Some(&env_config.agents_dir));
    if info.status == ContainerStatus::Dead {
        return Err(DockerError::BrokenState(format!("agent '{}' is in a broken state", old_name)));
    }

    let manage_core_code = mounts_have_core_code(raw.mounts.as_deref().unwrap_or(&[]));

    let port = resolve_existing_port(docker, &old_cname, &info, old_name, &env_config.agents_dir).await?;

    // Stop cleanly so the snapshot captures a quiesced filesystem (SQLite mid-write would
    // be the main concern). Best-effort — snapshot will still proceed if stop fails.
    if info.status == ContainerStatus::Running {
        tracing::info!(agent = %old_name, "[1/4] stopping container...");
        docker.stop_container(&old_cname, Some(StopContainerOptions { t: Some(CONTAINER_STOP_TIMEOUT_SECS), signal: None })).await.ok();
    }

    let ts = crate::time_utils::now_epoch_secs();
    let snapshot_tag = format!("vesta-rename:{}-to-{}_{}", old_name, new_name, ts);

    tracing::info!(old = %old_name, new = %new_name, "[2/4] snapshotting container...");
    snapshot_container(docker, &old_cname, &snapshot_tag, &[]).await?;

    tracing::info!(agent = %old_name, "[3/4] removing old container and env file...");
    remove_container_force(docker, &old_cname).await.ok();
    // Carry the constitution across the rename before the new container is created, so its
    // bind mount resolves to the existing content rather than a fresh empty file.
    let old_constitution = read_constitution(&env_config.agents_dir, old_name).unwrap_or_default();
    if !old_constitution.is_empty() {
        write_constitution(&env_config.agents_dir, new_name, &old_constitution).ok();
    }
    delete_agent_env_file(&env_config.agents_dir, old_name);
    delete_constitution_file(&env_config.agents_dir, old_name);

    tracing::info!(new = %new_name, "[4/4] creating renamed container from snapshot...");
    create_container(docker, &new_cname, &snapshot_tag, port, new_name, env_config, manage_core_code).await?;

    // Repos are keyed by agent name, so carry the backup history across the rename.
    crate::restic::rename_repo(old_name, new_name)?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // The agent restart policy, as a string for the Docker-gated test helper below. Production
    // sets it via the bollard enum (create_container / ensure_on_failure_policy); the tests only
    // need a "normal container" policy to build fixtures with.
    const RESTART_POLICY: &str = "on-failure";

    #[test]
    fn status_from_readiness_distinguishes_unprovisioned_from_unauthenticated() {
        use AgentStatus::*;
        // (authed, setup_complete, provider_configured) -> AgentStatus
        assert_eq!(status_from_readiness(true, true, true), Alive);
        assert_eq!(status_from_readiness(true, false, true), SettingUp);
        assert_eq!(status_from_readiness(false, false, true), NotAuthenticated);
        assert_eq!(status_from_readiness(false, false, false), Unprovisioned);
    }

    #[test]
    fn agent_status_human_text_reads_as_words() {
        assert_eq!(AgentStatus::Alive.human_text(), "alive");
        assert_eq!(AgentStatus::SettingUp.human_text(), "setting up");
        assert_eq!(AgentStatus::NotAuthenticated.human_text(), "not authenticated");
        assert_eq!(AgentStatus::NotFound.human_text(), "not found");
    }

    #[test]
    fn agent_status_serializes_unprovisioned_to_snake_case() {
        let to_str = |s: AgentStatus| serde_json::to_value(s).expect("serialize").as_str().expect("string").to_string();
        assert_eq!(to_str(AgentStatus::Unprovisioned), "unprovisioned");
        assert_eq!(to_str(AgentStatus::NotAuthenticated), "not_authenticated");
    }

    #[test]
    fn build_phase_serializes_to_snake_case() {
        let to_str = |phase: BuildPhase| serde_json::to_value(phase).expect("serialize").as_str().expect("string").to_string();
        assert_eq!(to_str(BuildPhase::Pulling), "pulling");
        assert_eq!(to_str(BuildPhase::Building), "building");
        assert_eq!(to_str(BuildPhase::Preparing), "preparing");
        assert_eq!(to_str(BuildPhase::Creating), "creating");
        assert_eq!(to_str(BuildPhase::Starting), "starting");
    }

    #[test]
    fn build_progress_forwards_phases_to_sink() {
        let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let recorder = seen.clone();
        let progress = BuildProgress::new(std::sync::Arc::new(move |phase| {
            recorder.lock().expect("lock").push(phase);
        }));
        progress.set(BuildPhase::Building);
        progress.set(BuildPhase::Preparing);
        progress.set(BuildPhase::Creating);
        assert_eq!(*seen.lock().expect("lock"), vec![BuildPhase::Building, BuildPhase::Preparing, BuildPhase::Creating]);
    }

    #[test]
    fn entrypoint_self_heals_missing_tmux() {
        // cc_sdk hard-depends on tmux; the entrypoint must install it at boot when missing so
        // containers rebuilt from a pre-tmux snapshot self-heal instead of crash-looping.
        let cmd = agent_container_entrypoint_cmd();
        let script = cmd.last().expect("entrypoint script");
        assert!(script.contains("command -v tmux"), "entrypoint must guard on tmux presence: {script}");
        assert!(script.contains("apt-get install -y -qq tmux"), "entrypoint must install tmux when absent: {script}");
        // The install runs before the agent process so cc_sdk finds tmux on first launch.
        let tmux_at = script.find("command -v tmux").expect("tmux step present");
        let main_at = script.find("python -m core.main").expect("main step present");
        assert!(tmux_at < main_at, "tmux install must precede launching core.main");
    }

    #[test]
    fn entrypoint_untracks_claude_from_git_workspace() {
        // ~/.claude holds the agent's credentials but the repo tracks dev tooling there; if the git
        // workspace tracks .claude, a sparse-checkout reapply deletes ~/.claude/.credentials.json.
        // The entrypoint must untrack + exclude .claude at boot, before the agent can reapply.
        let cmd = agent_container_entrypoint_cmd();
        let script = cmd.last().expect("entrypoint script");
        assert!(script.contains("update-index --force-remove"), "entrypoint must untrack .claude: {script}");
        assert!(script.contains("/.claude/"), "entrypoint must exclude .claude: {script}");
        let untrack_at = script.find("update-index --force-remove").expect("untrack step present");
        let main_at = script.find("python -m core.main").expect("main step present");
        assert!(untrack_at < main_at, ".claude untrack must precede launching core.main");
    }

    #[test]
    fn entrypoint_pins_venv_and_tolerates_both_engine_layouts() {
        // The venv must live outside the read-only core mount, and the sync/launch steps
        // must handle both the new layout (pyproject in core/) and the legacy root layout
        // so unmanaged boxes never crash-loop before their first workspace sync.
        let cmd = agent_container_entrypoint_cmd();
        let script = cmd.last().expect("entrypoint script");
        assert!(script.contains("UV_PROJECT_ENVIRONMENT=/root/agent/.venv"), "entrypoint must pin the venv outside core: {script}");
        assert!(script.contains("--project /root/agent/core"), "entrypoint must sync the core project when present: {script}");
        assert!(script.contains("python -m core.main"), "entrypoint must launch core.main: {script}");
    }

    #[test]
    fn mounts_have_core_code_accepts_legacy_and_single_mount_shapes() {
        let mount_with_dest = |dest: &str| bollard::models::MountPoint { destination: Some(dest.to_string()), ..Default::default() };
        let single = vec![mount_with_dest(CORE_MOUNT_DEST)];
        let legacy = vec![
            mount_with_dest(CORE_MOUNT_DEST),
            mount_with_dest("/root/agent/pyproject.toml"),
            mount_with_dest("/root/agent/uv.lock"),
        ];
        let none = vec![mount_with_dest(ENV_MOUNT_DEST)];
        assert!(mounts_have_core_code(&single));
        assert!(mounts_have_core_code(&legacy));
        assert!(!mounts_have_core_code(&none));
    }

    #[test]
    fn guard_alive_rejects_terminal_states_and_passes_live_through() {
        // The two terminal states map to their standard errors with the exact agent-facing
        // wording the lifecycle ops rely on; Running/Stopped pass through unchanged.
        let not_found = guard_alive(ContainerStatus::NotFound, "bot").expect_err("not found errors");
        assert!(matches!(not_found, DockerError::NotFound(_)));
        assert_eq!(not_found.to_string(), "agent 'bot' not found");

        let dead = guard_alive(ContainerStatus::Dead, "bot").expect_err("dead errors");
        assert!(matches!(dead, DockerError::BrokenState(_)));
        assert_eq!(dead.to_string(), "agent 'bot' is in a broken state");

        assert_eq!(guard_alive(ContainerStatus::Running, "bot").expect("running ok"), ContainerStatus::Running);
        assert_eq!(guard_alive(ContainerStatus::Stopped, "bot").expect("stopped ok"), ContainerStatus::Stopped);
    }

    #[test]
    fn reconcile_proceeds_when_free_space_unknown() {
        // A failed probe must not lock out normal startup.
        assert!(!reconcile_blocked_by_disk(None));
    }

    #[test]
    fn reconcile_blocked_only_below_threshold() {
        assert!(reconcile_blocked_by_disk(Some(MIN_RECONCILE_DISK_BYTES - 1)));
        assert!(!reconcile_blocked_by_disk(Some(MIN_RECONCILE_DISK_BYTES)));
        assert!(!reconcile_blocked_by_disk(Some(MIN_RECONCILE_DISK_BYTES + 1)));
    }

    #[test]
    fn available_disk_bytes_reads_real_path_and_rejects_missing() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        assert!(available_disk_bytes(dir.path()).expect("stat tempdir") > 0);
        assert_eq!(available_disk_bytes(std::path::Path::new("/no/such/path/vesta-test")), None);
    }

    #[test]
    fn write_agent_env_file_forwards_control_url_when_set() {
        // The cloud-init managed drop-in sets VESTA_CLOUD_CONTROL_URL on vestad's
        // process; the agent env file must forward it so the on-box skills reach the
        // right control plane. No other test touches this var, so setting it here is
        // race-safe.
        std::env::set_var("VESTA_CLOUD_CONTROL_URL", "https://staging.vesta.run/api");
        let dir = tempfile::TempDir::new().expect("tempdir");
        let cfg = AgentEnvConfig {
            config_dir: dir.path().to_path_buf(),
            agents_dir: dir.path().to_path_buf(),
            vestad_port: 1,
            vestad_tunnel: None,
        };
        let path = write_agent_env_file(&cfg, "agent1", 2, "tok").expect("write env file");
        let content = std::fs::read_to_string(&path).expect("read env file");
        assert!(
            content.contains("export VESTA_CLOUD_CONTROL_URL=https://staging.vesta.run/api"),
            "control url forwarded: {content}"
        );
        std::env::remove_var("VESTA_CLOUD_CONTROL_URL");

        // When unset, no stray line is written (append_optional skips None).
        let path2 = write_agent_env_file(&cfg, "agent2", 3, "tok2").expect("write env file 2");
        let content2 = std::fs::read_to_string(&path2).expect("read env file 2");
        assert!(!content2.contains("VESTA_CLOUD_CONTROL_URL"), "absent when unset: {content2}");
    }

    #[test]
    fn update_env_renames_legacy_personality_var_preserving_value() {
        // The agent dropped the AGENT_SEED_PERSONALITY env alias; the startup normalizer must
        // rename it to AGENT_PERSONALITY in existing files so a legacy non-default voice survives.
        let dir = tempfile::TempDir::new().expect("tempdir");
        let env_path = dir.path().join("vesta.env");
        std::fs::write(&env_path, "export AGENT_TOKEN=t\nexport AGENT_SEED_PERSONALITY=warm\nexport VESTAD_PORT=1\n").expect("write");
        update_all_agent_env_files(dir.path(), 39565, None);
        let content = std::fs::read_to_string(&env_path).expect("read");
        assert!(content.contains("export AGENT_PERSONALITY=warm"), "renamed, value preserved: {content}");
        assert!(!content.contains("AGENT_SEED_PERSONALITY"), "legacy var removed: {content}");
        assert!(content.contains("export AGENT_TOKEN=t"), "identity preserved");
    }

    #[test]
    fn update_env_drops_legacy_personality_when_new_one_present() {
        // If a file already has the new var, the stale legacy duplicate is dropped, not re-added.
        let dir = tempfile::TempDir::new().expect("tempdir");
        let env_path = dir.path().join("vesta.env");
        std::fs::write(&env_path, "export AGENT_PERSONALITY=dry\nexport AGENT_SEED_PERSONALITY=warm\n").expect("write");
        update_all_agent_env_files(dir.path(), 39565, None);
        let content = std::fs::read_to_string(&env_path).expect("read");
        assert!(content.contains("export AGENT_PERSONALITY=dry"));
        assert!(!content.contains("AGENT_SEED_PERSONALITY"));
        assert!(!content.contains("warm"));
    }

    #[test]
    fn constitution_unset_reads_empty() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        assert_eq!(read_constitution(dir.path(), "vesta").expect("read"), "");
    }

    #[test]
    fn constitution_write_then_read_round_trips() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        write_constitution(dir.path(), "vesta", "Always tell the truth.").expect("write");
        assert_eq!(read_constitution(dir.path(), "vesta").expect("read"), "Always tell the truth.");
    }

    #[test]
    fn constitution_write_preserves_inode() {
        // The bind mount in a running container points at this inode; in-place writes keep
        // it stable so the container sees updates without a mount refresh.
        use std::os::unix::fs::MetadataExt;
        let dir = tempfile::TempDir::new().expect("tempdir");
        write_constitution(dir.path(), "vesta", "first").expect("write");
        let ino_before = std::fs::metadata(constitution_host_path(dir.path(), "vesta")).expect("stat").ino();
        write_constitution(dir.path(), "vesta", "second").expect("write");
        let ino_after = std::fs::metadata(constitution_host_path(dir.path(), "vesta")).expect("stat").ino();
        assert_eq!(ino_before, ino_after);
        assert_eq!(read_constitution(dir.path(), "vesta").expect("read"), "second");
    }

    #[test]
    fn constitution_delete_removes_file() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        write_constitution(dir.path(), "vesta", "x").expect("write");
        delete_constitution_file(dir.path(), "vesta");
        assert!(!constitution_host_path(dir.path(), "vesta").exists());
    }

    #[test]
    fn constitution_mount_dest_is_read_only_path() {
        // Ensures the file API refuses to write the constitution from inside the container.
        assert!(MOUNT_DESTS.contains(&CONSTITUTION_MOUNT_DEST));
    }

    #[test]
    fn retry_import_pipeline_recovers_after_transient_failure() {
        let tries = std::cell::Cell::new(0u32);
        let result = retry_import_pipeline("test", || {
            tries.set(tries.get() + 1);
            if tries.get() < 2 {
                Err(DockerError::Failed("unexpected EOF".into()))
            } else {
                Ok(())
            }
        });
        assert!(result.is_ok());
        assert_eq!(tries.get(), 2);
    }

    #[test]
    fn retry_import_pipeline_gives_up_and_returns_last_error() {
        let tries = std::cell::Cell::new(0u32);
        let result = retry_import_pipeline("test", || {
            tries.set(tries.get() + 1);
            Err(DockerError::Failed("always fails".into()))
        });
        assert!(result.is_err());
        assert_eq!(tries.get(), IMPORT_PIPELINE_MAX_ATTEMPTS);
    }

    #[test]
    fn normalize_name_lowercases_and_sanitizes() {
        let cases = [
            ("MyAgent", "myagent"),
            ("My Agent_Name", "my-agent-name"),
            ("hello!@#world", "helloworld"),
            ("--test--", "test"),
            ("a---b", "a-b"),
            ("  hello  ", "hello"),
            ("", ""),
            ("!!!", ""),
        ];
        for (input, expected) in cases {
            assert_eq!(normalize_name(input), expected, "input: {input:?}");
        }
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
    fn validate_name_accepts_dns_labels_rejects_the_rest() {
        let cases = [
            ("hello", true),
            ("a", true),
            ("test-agent", true),
            ("a1", true),
            ("123", true),
            ("vesta", true),
            ("my-vesta", true),
            ("vesta-agent", true),
            ("", false),
            ("Hello", false),
            ("-hello", false),
            ("hello-", false),
            ("hello world", false),
            ("hello_world", false),
        ];
        for (name, ok) in cases {
            assert_eq!(validate_name(name).is_ok(), ok, "name: {name:?}");
        }
    }

    #[test]
    fn validate_rejects_too_long() {
        let long = "a".repeat(33);
        assert!(validate_name(&long).is_err());
    }

    #[test]
    fn container_name_roundtrip() {
        assert_eq!(name_from_cname(&container_name("test")), "test");
        assert_eq!(name_from_cname(&container_name("my-agent")), "my-agent");
    }

    // Property-based tests: normalize_name must uphold these invariants for ANY input,
    // since it processes raw user-supplied agent names.
    proptest::proptest! {
        #[test]
        fn normalize_output_is_valid_or_empty(raw in proptest::prelude::any::<String>()) {
            let normalized = normalize_name(&raw);
            proptest::prop_assert!(
                normalized.is_empty() || validate_name(&normalized).is_ok(),
                "normalize_name({:?}) produced invalid name {:?}", raw, normalized
            );
        }

        #[test]
        fn normalize_is_idempotent(raw in proptest::prelude::any::<String>()) {
            let once = normalize_name(&raw);
            let twice = normalize_name(&once);
            proptest::prop_assert_eq!(&twice, &once, "not idempotent for input {:?}", raw);
        }

        #[test]
        fn normalize_never_exceeds_max_len(raw in proptest::prelude::any::<String>()) {
            proptest::prop_assert!(normalize_name(&raw).len() <= NAME_MAX_LEN);
        }

        #[test]
        fn normalize_output_charset_is_safe(raw in proptest::prelude::any::<String>()) {
            let normalized = normalize_name(&raw);
            proptest::prop_assert!(
                normalized.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-'),
                "normalize_name({:?}) produced unsafe chars: {:?}", raw, normalized
            );
        }

        #[test]
        fn container_name_roundtrips_for_valid_names(raw in "[a-z0-9][a-z0-9-]{0,30}[a-z0-9]") {
            // Only test names that pass validation (the precondition for container_name).
            if validate_name(&raw).is_ok() {
                proptest::prop_assert_eq!(name_from_cname(&container_name(&raw)), raw);
            }
        }
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

    #[test]
    fn dockerignore_matches_paths_against_patterns() {
        // (label, patterns, path, expected)
        let cases: &[(&str, &[&str], &str, bool)] = &[
            ("exact dir name", &["target"], "target", true),
            ("exact dir prefix matches contents", &["target"], "target/debug/foo", true),
            ("exact must not match plural", &["target"], "targets", false),
            ("exact must not match nested dir", &["target"], "some/nested/target", false),
            ("exact must not match nested file", &["target"], "some/nested/target/file.txt", false),
            ("trailing slash matches root dir", &["app/"], "app", true),
            ("trailing slash matches root contents", &["app/"], "app/package.json", true),
            ("trailing slash skips nested dir", &["app/"], "agent/skills/dashboard/app", false),
            ("trailing slash skips nested contents", &["app/"], "agent/skills/dashboard/app/src/App.tsx", false),
            ("extension wildcard matches root", &["*.pyc"], "foo.pyc", true),
            ("extension wildcard matches nested", &["*.pyc"], "dir/bar.pyc", true),
            ("extension wildcard rejects other ext", &["*.pyc"], "foo.py", false),
            ("question mark single char", &["?.txt"], "a.txt", true),
            ("question mark rejects two chars", &["?.txt"], "ab.txt", false),
            ("doublestar matches root", &["**/logs"], "logs", true),
            ("doublestar matches one level", &["**/logs"], "a/logs", true),
            ("doublestar matches two levels", &["**/logs"], "a/b/logs", true),
            ("doublestar matches contents", &["**/logs"], "a/b/logs/debug.log", true),
            ("negation re-includes file", &["*.md", "!README.md"], "README.md", false),
            ("negation leaves others ignored", &["*.md", "!README.md"], "CHANGELOG.md", true),
            ("slash pattern exact", &["agent/tests"], "agent/tests", true),
            ("slash pattern contents", &["agent/tests"], "agent/tests/test_unit.py", true),
            ("slash pattern not nested", &["agent/tests"], "other/agent/tests", false),
            ("no false prefix match", &["app"], "application", false),
            ("prefix dir matches contents", &["app"], "app/foo", true),
        ];
        for (label, pats, path, expected) in cases {
            let pats: Vec<String> = pats.iter().map(|s| s.to_string()).collect();
            assert_eq!(is_dockerignored(path, &pats), *expected, "{label}");
        }
    }

    #[test]
    fn rebuild_agent_stops_running_container_before_snapshot() {
        // rebuild_agent must quiesce a running container before docker export, for the same
        // reason rename_agent does: SQLite WAL + atomic state.json tmp+rename can be torn
        // mid-export if the container is still running, causing silent data loss on rebuild.
        // rename_agent carries the explicit comment and the stop call; rebuild_agent must too.
        let src = include_str!("docker.rs");

        let rebuild_start = src.find("pub async fn rebuild_agent").expect("rebuild_agent present");
        let rename_start = src.find("pub async fn rename_agent").expect("rename_agent present");
        assert!(rebuild_start < rename_start, "rebuild_agent must appear before rename_agent for this test to slice correctly");
        let rebuild_body = &src[rebuild_start..rename_start];

        let stop_pos = rebuild_body.find("stop_container");
        let snapshot_pos = rebuild_body.find("snapshot_container").expect("snapshot_container must be called in rebuild_agent");

        assert!(
            stop_pos.is_some(),
            "rebuild_agent does not call stop_container before snapshotting; \
             a running container is exported live, tearing SQLite WAL and state.json writes \
             (rename_agent stops first for exactly this reason)"
        );
        assert!(
            stop_pos.unwrap() < snapshot_pos,
            "rebuild_agent calls stop_container AFTER snapshot_container; \
             stop must precede the docker export to quiesce the filesystem"
        );
    }

    #[test]
    fn rebuild_agent_confirms_removal_before_create() {
        // rebuild_agent recreates under the SAME name, so the old container must be confirmed gone
        // before [4/4] create. A best-effort `remove_container_force(...).await.ok()` silently left
        // the agent stopped on the old image whenever the remove didn't take (docker rm can return
        // before the name frees, or fail transiently) — the create then collided on the name.
        let src = include_str!("docker.rs");
        let rebuild_start = src.find("pub async fn rebuild_agent").expect("rebuild_agent present");
        let rename_start = src.find("pub async fn rename_agent").expect("rename_agent present");
        let rebuild_body = &src[rebuild_start..rename_start];

        let remove_pos = rebuild_body
            .find("ensure_container_removed")
            .expect("rebuild_agent must confirm the old container is gone via ensure_container_removed before recreating");
        let create_pos = rebuild_body.find("create_container").expect("create_container must be called in rebuild_agent");
        assert!(remove_pos < create_pos, "rebuild_agent must remove the old container before creating the new one");
        assert!(
            !rebuild_body.contains("remove_container_force"),
            "rebuild_agent must use ensure_container_removed (confirms gone), not the best-effort remove_container_force"
        );
    }

    // --- Docker integration tests (require Docker daemon) ---
    // Run with: cargo test -p vestad -- --ignored

    const TEST_PREFIX: &str = "vesta-integration-test";

    fn test_docker() -> Docker {
        connect().expect("failed to connect to docker")
    }

    /// Image for the #[ignore] Docker tests: honors VESTAD_AGENT_IMAGE (set by CI
    /// to an image built from the checkout), falls back to the released image.
    fn test_agent_image() -> String {
        std::env::var(AGENT_IMAGE_ENV).unwrap_or_else(|_| vesta_image())
    }

    async fn inspect_then_needs_rebuild(docker: &Docker, cname: &str) -> bool {
        let info = docker.inspect_container(cname, None).await.expect("inspect");
        needs_rebuild(cname, &info)
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
            "on-failure" => bollard::models::RestartPolicyNameEnum::ON_FAILURE,
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

        let config = ContainerCreateBody {
            image: Some(test_agent_image()),
            tty: Some(true),
            labels: Some(labels),
            cmd: Some(cmd),
            host_config: Some(host_config),
            ..Default::default()
        };

        docker.create_container(
            Some(CreateContainerOptions { name: Some(tc.name.clone()), platform: String::new() }),
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
        assert!(docker.inspect_image(&img.tag).await.is_ok(), "snapshot image should exist");
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

        assert!(!inspect_then_needs_rebuild(&docker, &tc.name).await, "fresh container should NOT need rebuild");
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
        std::fs::write(code_dir.path().join("core").join("pyproject.toml"), "").unwrap();
        std::fs::write(code_dir.path().join("core").join("uv.lock"), "").unwrap();

        let src_core = code_dir.path().join("core");

        let mounts = [
            (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]),
            (src_core.to_str().unwrap(), MOUNT_DESTS[1]),
        ];

        create_test_container_async(&docker, &tc, &mounts, agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(!inspect_then_needs_rebuild(&docker, &tc.name).await, "container with all mounts should NOT need rebuild");
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

        assert!(inspect_then_needs_rebuild(&docker, &tc.name).await, "container with wrong cmd SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_true_on_missing_mount() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-nomount");

        create_test_container_async(&docker, &tc, &[], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(inspect_then_needs_rebuild(&docker, &tc.name).await, "container without env mount SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_needs_rebuild_false_on_missing_code_mounts() {
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-nocode");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(!inspect_then_needs_rebuild(&docker, &tc.name).await, "missing core code mounts should NOT trigger rebuild");
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

        assert!(inspect_then_needs_rebuild(&docker, &tc.name).await, "container with wrong network SHOULD need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn test_restart_policy_is_not_a_rebuild_trigger_and_reconciles_in_place() {
        // The restart policy is reconciled in place (docker update, no snapshot): a legacy
        // unless-stopped container must NOT need a rebuild, and ensure_on_failure_policy must flip
        // it to on-failure live. (Old behavior treated a policy mismatch as a rebuild trigger.)
        let docker = test_docker();
        let tc = TestContainer::new("rebuild-restart");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);

        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, "unless-stopped").await;

        assert!(!inspect_then_needs_rebuild(&docker, &tc.name).await, "a policy mismatch must NOT trigger a rebuild — it's reconciled in place");
        assert_eq!(container_restart_policy(&docker, &tc.name).await, "unless-stopped");
        ensure_on_failure_policy(&docker, &tc.name).await.expect("update policy in place");
        assert_eq!(container_restart_policy(&docker, &tc.name).await, "on-failure", "policy reconciled to on-failure without a rebuild");
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
        assert!(inspect_then_needs_rebuild(&docker, &tc.name).await, "precondition: should need rebuild");

        // Snapshot
        snapshot_container(&docker, &tc.name, &img.tag, &[]).await.expect("snapshot should succeed");

        // Remove old, create new from snapshot with correct config
        remove_container_force(&docker, &tc.name).await.ok();
        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;

        assert!(!inspect_then_needs_rebuild(&docker, &tc.name).await, "rebuilt container should NOT need rebuild");
    }

    #[tokio::test]
    #[ignore]
    async fn ensure_container_removed_removes_and_is_idempotent() {
        let docker = test_docker();
        let tc = TestContainer::new("ensure-removed");
        let env_file = tempfile::NamedTempFile::new().expect("tempfile");
        std::fs::write(env_file.path(), "export WS_PORT=12345\n").unwrap();
        let env_mount = (env_file.path().to_str().unwrap(), MOUNT_DESTS[0]);
        create_test_container_async(&docker, &tc, &[env_mount], agent_container_entrypoint_cmd(), NETWORK_MODE, RESTART_POLICY).await;
        assert_ne!(container_status(&docker, &tc.name).await, ContainerStatus::NotFound, "precondition: container exists");

        ensure_container_removed(&docker, &tc.name).await.expect("removes a present container");
        assert_eq!(container_status(&docker, &tc.name).await, ContainerStatus::NotFound, "container must be gone after ensure_container_removed");

        // Idempotent: the name is free, which is exactly what rebuild_agent's create depends on.
        ensure_container_removed(&docker, &tc.name).await.expect("no-op when already absent");
    }

    // Bound on retries while the container's `mkdir` races its start (200ms apart).
    const RENAME_NOTIF_DROP_TRIES: usize = 25;

    #[tokio::test]
    #[ignore]
    async fn drop_rename_notification_writes_payload_into_container() {
        let docker = test_docker();
        let agent_name = format!("rename-notif-{}", std::process::id());
        let cname = container_name(&agent_name);
        // Explicit name so it matches container_name(agent_name); Drop still cleans up.
        let tc = TestContainer { name: cname.clone() };
        docker_cleanup(&["rm", "-f", &cname]);

        // A bare sleeper that owns the notifications dir but never runs the agent's
        // monitor loop, so nothing deletes the dropped file out from under us. This
        // is what makes the assertion deterministic, unlike driving it through a
        // started agent that races to consume and unlink the notification.
        let cmd = vec![
            "sh".to_string(),
            "-c".to_string(),
            "mkdir -p /root/agent/notifications && sleep 600".to_string(),
        ];
        create_test_container_async(&docker, &tc, &[], cmd, NETWORK_MODE, RESTART_POLICY).await;
        assert!(start_container(&docker, &cname).await, "test container should start");

        // mkdir runs asynchronously after start; retry the drop until the dir exists.
        let mut file_name = None;
        for _ in 0..RENAME_NOTIF_DROP_TRIES {
            match crate::serve::drop_rename_notification(&docker, &agent_name, "old-name").await {
                Ok(name) => {
                    file_name = Some(name);
                    break;
                }
                Err(_) => tokio::time::sleep(std::time::Duration::from_millis(200)).await,
            }
        }
        let file_name = file_name.expect("notification should drop once the dir exists");

        let body = download_from_container(&docker, &cname, &format!("/root/agent/notifications/{file_name}"))
            .await
            .expect("dropped notification file should be readable");
        let payload: serde_json::Value = serde_json::from_str(&body).expect("notification is valid json");
        assert_eq!(payload["source"], "vestad");
        assert_eq!(payload["type"], "rename");
        assert_eq!(payload["interrupt"], true);
        assert_eq!(payload["old_name"], "old-name");
        assert_eq!(payload["new_name"], agent_name);
    }
}
