pub mod client;
pub mod types;

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::LazyLock;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

use client::Client;
use types::ServerConfig;

pub static SERVER: LazyLock<TestServer> = LazyLock::new(|| {
    kill_orphan_vestads();
    cleanup_orphan_test_containers();
    TestServer::start().unwrap_or_else(|e| panic!("failed to start test server: {e}"))
});

/// Name of a shared, never-mutated agent created once per test process. Use for
/// read-only assertions about a fresh agent (env files, container layout) so we
/// don't pay create+destroy on every test. The agent is left unauthenticated;
/// cleanup happens at the next run via `cleanup_orphan_test_containers`.
pub static SHARED_RO_AGENT: LazyLock<String> = LazyLock::new(|| {
    let client = SERVER.client();
    let raw = unique_agent("ro-shared");
    // The shared SERVER runs under the ambient $USER (not a unique per-run test user),
    // so its agent containers aren't matched by `cleanup_orphan_test_containers` and
    // survive across runs. A prior run's `ro-shared-N` therefore still exists on a CI
    // retry. Destroy any leftover first so creation is idempotent — otherwise the retry's
    // create hit "already exists", which panicked here and *poisoned* this LazyLock,
    // cascading a single failure into every read-only test.
    let _ = client.stop_agent(&raw);
    let _ = client.destroy_agent(&raw);
    client
        .create_agent(&raw)
        .unwrap_or_else(|e| panic!("failed to create shared read-only agent: {e}"))
});

static TEST_USER_COUNTER: AtomicU32 = AtomicU32::new(0);
static TEST_AGENT_COUNTER: AtomicU32 = AtomicU32::new(0);

/// curl flags that absorb transient GitHub API/CDN flakes during integration tests.
const CURL_RETRY_ARGS: &[&str] = &["--retry", "5", "--retry-all-errors", "--retry-delay", "2"];

/// Generate a unique user name for test isolation. Includes PID for cross-run
/// uniqueness and an atomic counter for intra-run uniqueness. This prevents
/// tests from seeing each other's Docker containers (vestad scopes by
/// `vesta.user` label).
pub fn unique_user(prefix: &str) -> String {
    let id = TEST_USER_COUNTER.fetch_add(1, Ordering::SeqCst);
    format!("{prefix}-t{}-{id}", std::process::id())
}

/// Generate a unique agent name for parallel test execution.
pub fn unique_agent(prefix: &str) -> String {
    let id = TEST_AGENT_COUNTER.fetch_add(1, Ordering::SeqCst);
    format!("{prefix}-{id}")
}

#[derive(Default)]
pub struct TestServerBuilder {
    user: Option<String>,
    home: Option<PathBuf>,
    vestad_bin: Option<PathBuf>,
    env_remove: Vec<String>,
}

impl TestServerBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set an explicit user name. Prefer `unique_user()` to avoid cross-test
    /// Docker container collisions.
    pub fn user(mut self, user: &str) -> Self {
        self.user = Some(user.to_string());
        self
    }

    pub fn home(mut self, home: PathBuf) -> Self {
        self.home = Some(home);
        self
    }

    pub fn vestad_bin(mut self, vestad_bin: PathBuf) -> Self {
        self.vestad_bin = Some(vestad_bin);
        self
    }

    /// Clear an env var the test process inherited before spawning vestad. The upgrade test
    /// clears `VESTAD_AGENT_IMAGE` for the OLD vestad so it falls back to its own released
    /// image (`ghcr.io/elyxlz/vesta:<tag>`), making the agent a faithful fleet member of that
    /// version rather than running on the checkout's image.
    pub fn env_remove(mut self, key: &str) -> Self {
        self.env_remove.push(key.to_string());
        self
    }

    pub fn start(self) -> Result<TestServer, String> {
        let user = self.user.unwrap_or_else(|| unique_user("test"));
        TestServer::start_with_options(Some(user), self.home, self.vestad_bin, &self.env_remove)
    }
}

/// Remove Docker containers left behind by previous test runs that crashed
/// before TestAgent::drop could clean up. Targets containers from test users
/// (unique_user generates names like "prefix-tPID-N") and e2e test containers.
fn cleanup_orphan_test_containers() {
    let Ok(output) = Command::new("docker")
        .args(["ps", "-a", "--filter", "label=vesta.managed=true", "--format", "{{.Names}}\t{{.Label \"vesta.user\"}}"])
        .output()
    else {
        return;
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines() {
        let parts: Vec<&str> = line.split('\t').collect();
        let (name, user_label) = match parts.as_slice() {
            [n, u] => (n.trim(), u.trim()),
            _ => continue,
        };
        if name.is_empty() { continue; }
        // Test users from unique_user() contain "-t{pid}-"
        // E2e containers use "test-e2e-" prefix
        let is_test_user = user_label.contains("-t") && user_label.chars().any(|c| c.is_ascii_digit());
        let is_e2e = name.contains("test-e2e-");
        if is_test_user || is_e2e {
            let _ = Command::new("docker").args(["rm", "-f", name]).output();
        }
    }
}

fn kill_orphan_vestads() {
    let Ok(output) = Command::new("sh")
        .args(["-c", "ps -eo pid,args | grep '[v]estad serve'"])
        .output()
    else {
        return;
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        let Some(pid_str) = parts.first() else { continue };
        let Ok(pid) = pid_str.parse::<u32>() else { continue };

        // Check if the process's HOME is a temp directory
        let environ_path = format!("/proc/{pid}/environ");
        let Ok(environ) = std::fs::read(&environ_path) else { continue };
        let is_tmp_home = environ
            .split(|&b| b == 0)
            .filter_map(|entry| std::str::from_utf8(entry).ok())
            .any(|entry| {
                entry.starts_with("HOME=") && (entry.contains("/tmp/") || entry.contains("/tmp."))
            });
        if is_tmp_home {
            let _ = Command::new("kill").arg("-9").arg(pid_str).output();
        }
    }
}

pub struct TestServer {
    process: Option<Child>,
    _tmpdir: Option<tempfile::TempDir>,
    home: PathBuf,
    pub config: ServerConfig,
    pub port: u16,
}

impl TestServer {
    pub fn start() -> Result<Self, String> {
        Self::start_with_options(None, None, None, &[])
    }

    fn start_with_options(user: Option<String>, home: Option<PathBuf>, vestad_bin: Option<PathBuf>, env_remove: &[String]) -> Result<Self, String> {
        rustls::crypto::ring::default_provider()
            .install_default()
            .ok();

        let (tmpdir, home) = match home {
            Some(home) => {
                std::fs::create_dir_all(&home).map_err(|e| format!("create home: {e}"))?;
                (None, home)
            }
            None => {
                let tmpdir = tempfile::TempDir::new().map_err(|e| format!("tmpdir: {e}"))?;
                let home = tmpdir.path().to_path_buf();
                (Some(tmpdir), home)
            }
        };
        let vestad = vestad_bin.unwrap_or(find_vestad()?);

        let real_home = std::env::var("HOME").unwrap_or_default();
        let docker_config = format!("{}/.docker", real_home);

        let stderr_path = home.join("vestad-stderr.log");
        let stderr_file = std::fs::File::create(&stderr_path)
            .map_err(|e| format!("create stderr log: {e}"))?;
        // Capture stdout too: vestad's tracing (reconcile/rebuild decisions) goes here, and the
        // upgrade e2e dumps it on failure to explain why an agent didn't come back after update.
        let stdout_path = home.join("vestad-stdout.log");
        let stdout_file = std::fs::File::create(&stdout_path)
            .map_err(|e| format!("create stdout log: {e}"))?;

        let mut cmd = Command::new(&vestad);
        cmd.args(["serve", "--standalone", "--no-tunnel"])
            .env("HOME", &home)
            .env("DOCKER_CONFIG", &docker_config)
            .stdout(Stdio::from(stdout_file))
            .stderr(Stdio::from(stderr_file));

        if let Some(ref user_name) = user {
            cmd.env("USER", user_name);
        }
        for key in env_remove {
            cmd.env_remove(key);
        }

        let process = cmd.spawn().map_err(|e| format!("spawn vestad: {e}"))?;

        let config_dir = home.join(".config/vesta/vestad");
        let port_path = config_dir.join("port");

        let startup_timeout = Duration::from_secs(60);
        let deadline = std::time::Instant::now() + startup_timeout;
        let port = loop {
            if let Ok(content) = std::fs::read_to_string(&port_path) {
                if let Ok(p) = content.trim().parse::<u16>() {
                    let addr: std::net::SocketAddr = ([127, 0, 0, 1], p).into();
                    if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
                        break p;
                    }
                }
            }
            if std::time::Instant::now() > deadline {
                let stderr = std::fs::read_to_string(&stderr_path).unwrap_or_default();
                return Err(format!(
                    "vestad did not start within {}s\nstderr:\n{}",
                    startup_timeout.as_secs(),
                    stderr,
                ));
            }
            std::thread::sleep(Duration::from_millis(100));
        };

        let api_key = std::fs::read_to_string(config_dir.join("api-key"))
            .map_err(|e| format!("read api-key: {e}"))?
            .trim()
            .to_string();
        let cert_pem = std::fs::read_to_string(config_dir.join("tls/cert.pem")).ok();
        let fingerprint = std::fs::read_to_string(config_dir.join("tls/fingerprint"))
            .ok()
            .map(|s| s.trim().to_string());

        Ok(Self {
            process: Some(process),
            home,
            _tmpdir: tmpdir,
            config: ServerConfig {
                url: format!("https://127.0.0.1:{port}"),
                api_key,
                cert_fingerprint: fingerprint,
                cert_pem,
            },
            port,
        })
    }

    pub fn client(&self) -> Client {
        Client::new(&self.config)
    }

    pub fn home_path(&self) -> &std::path::Path {
        &self.home
    }

    pub fn _tmpdir_path(&self) -> &std::path::Path {
        self.home_path()
    }

    pub fn shutdown(&mut self) {
        if let Some(ref mut p) = self.process {
            let _ = p.kill();
            let _ = p.wait();
        }
        self.process = None;
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.shutdown();
    }
}

pub struct TestAgent<'a> {
    pub name: String,
    client: &'a Client,
}

impl<'a> TestAgent<'a> {
    pub fn create(client: &'a Client, name: &str) -> Result<Self, String> {
        let _ = client.stop_agent(name);
        let _ = client.destroy_agent(name);
        let name = client.create_agent(name)?;
        Ok(Self { name, client })
    }

    pub fn create_with_manage_agent_code(client: &'a Client, name: &str) -> Result<Self, String> {
        let _ = client.stop_agent(name);
        let _ = client.destroy_agent(name);
        let name = client.create_agent_ex(name, Some(true))?;
        Ok(Self { name, client })
    }

    pub fn create_without_manage_agent_code(client: &'a Client, name: &str) -> Result<Self, String> {
        let _ = client.stop_agent(name);
        let _ = client.destroy_agent(name);
        let name = client.create_agent_ex(name, Some(false))?;
        Ok(Self { name, client })
    }
}

impl Drop for TestAgent<'_> {
    fn drop(&mut self) {
        let _ = self.client.stop_agent(&self.name);
        let _ = self.client.destroy_agent(&self.name);
    }
}

pub fn find_vestad() -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("VESTAD_BIN") {
        return Ok(PathBuf::from(p));
    }
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf();
    for profile in ["debug", "release"] {
        let p = workspace.join(format!("target/{profile}/vestad"));
        if p.exists() {
            return Ok(p);
        }
    }
    Err("vestad not found. Run `cargo build -p vestad` first, or set VESTAD_BIN".into())
}

pub const FAKE_TOKEN: &str = r#"{"claudeAiOauth":{"accessToken":"test","refreshToken":"test","expiresAt":4102444800000}}"#;

/// Write fake Claude credentials straight into the container fs (works even
/// while the agent is still booting, like the old docker-cp path). The agent
/// derives `authenticated` from this file on its next boot — callers that need
/// the running agent to *report* authenticated must restart it after injecting.
pub fn inject_fake_token(_c: &Client, name: &str) {
    let cname = agent_container_name(name);
    let script = format!("mkdir -p /root/.claude && printf '%s' '{FAKE_TOKEN}' > /root/.claude/.credentials.json");
    exec_in_container(&cname, &script).expect("write fake credentials");
}

/// Pre-mark first-start setup as done so the agent reports `alive` (not `setting_up`)
/// on the next boot without waiting for the SDK to call `mark_setup_done`. Tests run
/// with a fake token, so no real SDK session can drive that tool call.
///
/// Writing state.json while the agent is running isn't enough: the running agent
/// holds `first_start_done=false` in memory and rewrites state.json on its graceful
/// shutdown, clobbering this write on the next restart. So write the flag, SIGKILL
/// the agent (no graceful save), then start it fresh so the boot reads `true`; from
/// then on the in-memory value survives normal restarts.
pub fn mark_first_start_done(name: &str) -> Result<(), String> {
    let cname = agent_container_name(name);
    exec_in_container(
        &cname,
        r#"mkdir -p /root/agent/data && printf '{"first_start_done": true}' > /root/agent/data/state.json"#,
    )?;
    docker_cmd(&["kill", &cname])?;
    docker_cmd(&["start", &cname])?;
    Ok(())
}

pub fn docker_cmd(args: &[&str]) -> Result<String, String> {
    let output = std::process::Command::new("docker")
        .args(args)
        .output()
        .map_err(|e| format!("docker {:?}: {e}", args))?;
    if !output.status.success() {
        return Err(format!(
            "docker {:?} failed: {}",
            args,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

pub fn exec_in_container(container: &str, script: &str) -> Result<String, String> {
    docker_cmd(&["exec", container, "bash", "-lc", script])
}

pub fn agent_container_name(agent_name: &str) -> String {
    let user = std::env::var("USER").unwrap_or_else(|_| "unknown".to_string());
    format!("vesta-{}-{}", user, agent_name)
}

/// Print an agent container's state + logs to stderr. Called when a wait helper
/// times out so CI shows *why* the agent never became ready (crash loop, bind
/// error, etc.) instead of a bare "timeout (status: starting)". Best-effort:
/// every probe is allowed to fail (the container may be mid-restart).
pub fn dump_agent_diagnostics(agent_name: &str) {
    // Multi-user tests name containers vesta-<testuser>-<name>, so the $USER-based
    // name won't match. Fall back to a suffix search over all vesta containers.
    let cname = match docker_cmd(&["ps", "-a", "--format", "{{.Names}}"]) {
        Ok(list) => list
            .lines()
            .find(|n| n.ends_with(&format!("-{agent_name}")) && n.starts_with("vesta-"))
            .map(str::to_string)
            .unwrap_or_else(|| agent_container_name(agent_name)),
        Err(_) => agent_container_name(agent_name),
    };
    eprintln!("\n========== AGENT DIAGNOSTICS: {cname} ==========");
    match docker_cmd(&[
        "inspect",
        &cname,
        "--format",
        "status={{.State.Status}} exitCode={{.State.ExitCode}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}",
    ]) {
        Ok(state) => eprintln!("state: {state}"),
        Err(e) => eprintln!("inspect failed: {e}"),
    }
    eprintln!("--- docker logs (tail 60) ---");
    match docker_cmd(&["logs", "--tail", "60", &cname]) {
        Ok(logs) if !logs.trim().is_empty() => eprintln!("{logs}"),
        Ok(_) => eprintln!("(empty — agent runs with a tty; see vesta.log below)"),
        Err(e) => eprintln!("({e})"),
    }
    // A crash-looping container's overlay fs is unreadable mid-restart, so `docker cp`
    // would fail. Stop the restart loop first to settle the filesystem, then read the
    // agent's own structured log.
    let _ = docker_cmd(&["update", "--restart=no", &cname]);
    let _ = docker_cmd(&["stop", "-t", "2", &cname]);
    eprintln!("--- vesta.log (tail 80) ---");
    match cp_container_file(&cname, "/root/agent/logs/vesta.log") {
        Some(content) if !content.trim().is_empty() => {
            let tail: Vec<&str> = content.lines().rev().take(80).collect();
            for line in tail.iter().rev() {
                eprintln!("{line}");
            }
        }
        _ => eprintln!("(not captured — agent likely crashed before its logger started)"),
    }
    eprintln!("========== END DIAGNOSTICS: {cname} ==========\n");
}

/// Copy a file out of a (possibly restarting) container via `docker cp` and return its text.
fn cp_container_file(cname: &str, container_path: &str) -> Option<String> {
    let tmp = std::env::temp_dir().join(format!("vesta-diag-{}", std::process::id()));
    let tmp_str = tmp.to_str()?;
    docker_cmd(&["cp", &format!("{cname}:{container_path}"), tmp_str]).ok()?;
    let content = std::fs::read_to_string(&tmp).ok();
    let _ = std::fs::remove_file(&tmp);
    content
}

/// Container is up (regardless of auth/readiness state).
pub fn is_up(status: &str) -> bool {
    matches!(status, "not_authenticated" | "unprovisioned" | "starting" | "setting_up" | "alive" | "restarting")
}

pub struct ReleasedVestad {
    _tmpdir: tempfile::TempDir,
    pub tag: String,
    pub bin_path: PathBuf,
}

pub fn download_latest_released_vestad() -> Result<ReleasedVestad, String> {
    let body = github_get("https://api.github.com/repos/elyxlz/vesta/releases/latest")?;
    let data: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| format!("parse latest release metadata: {e}"))?;
    let tag = data
        .get("tag_name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "latest release tag missing".to_string())?
        .to_string();
    download_released_vestad(&tag)
}

/// Parse a `vX.Y.Z` (or `X.Y.Z`) release tag into numeric components for ordering.
/// Returns `None` for tags that don't parse, so the upgrade test ignores any
/// non-standard tag rather than mis-ordering it.
pub fn parse_release_tag(tag: &str) -> Option<Vec<u64>> {
    let parts: Option<Vec<u64>> = tag.trim_start_matches('v').split('.').map(|s| s.parse().ok()).collect();
    parts.filter(|components| components.len() == 3)
}

/// The highest released tag strictly older than `current` (e.g. `0.1.159` -> `v0.1.158`).
///
/// Queries the published releases rather than decrementing the patch number, because the
/// beta channel lets users skip versions — the version directly below `current` may never
/// have been released. Returns `Ok(None)` when no older release exists (nothing to upgrade
/// from). This is the version a fleet member actually runs before taking `current`.
pub fn previous_released_tag(current: &str) -> Result<Option<String>, String> {
    let current_parts = parse_release_tag(current).ok_or_else(|| format!("unparseable current version: {current}"))?;
    let body = github_get("https://api.github.com/repos/elyxlz/vesta/releases?per_page=100")?;
    let releases: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| format!("parse releases list: {e}"))?;
    let entries = releases.as_array().ok_or_else(|| "releases response was not a list".to_string())?;
    let mut best: Option<(Vec<u64>, String)> = None;
    for entry in entries {
        let Some(tag) = entry.get("tag_name").and_then(|value| value.as_str()) else {
            continue;
        };
        let Some(parts) = parse_release_tag(tag) else {
            continue;
        };
        if parts >= current_parts {
            continue;
        }
        if best.as_ref().is_none_or(|(best_parts, _)| parts > *best_parts) {
            best = Some((parts, tag.to_string()));
        }
    }
    Ok(best.map(|(_, tag)| tag))
}

fn github_get(url: &str) -> Result<String, String> {
    let output = Command::new("curl")
        .arg("-fsSL")
        .args(CURL_RETRY_ARGS)
        .args(["-H", "Accept: application/vnd.github+json", "-H", "User-Agent: vesta-tests", url])
        .output()
        .map_err(|e| format!("github GET {url}: {e}"))?;
    if !output.status.success() {
        return Err(format!("github GET {url} failed"));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Download and extract the released `vestad` binary for a specific tag (e.g. `v0.1.158`).
/// The extracted binary carries that release's embedded agent core, so running it produces
/// an agent exactly as that version's fleet members have it.
pub fn download_released_vestad(tag: &str) -> Result<ReleasedVestad, String> {
    let rust_target = match std::env::consts::ARCH {
        "x86_64" => "x86_64-unknown-linux-gnu",
        "aarch64" => "aarch64-unknown-linux-gnu",
        other => return Err(format!("unsupported architecture for released vestad test: {other}")),
    };
    let artifact = format!("vestad-{rust_target}.tar.gz");
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/download/{}/{}",
        tag, artifact
    );

    let tmpdir = tempfile::TempDir::new().map_err(|e| format!("tmpdir: {e}"))?;
    let archive_path = tmpdir.path().join("vestad.tar.gz");
    let output = Command::new("curl")
        .arg("-fsSL")
        .args(CURL_RETRY_ARGS)
        .arg("-o")
        .arg(&archive_path)
        .arg(&url)
        .output()
        .map_err(|e| format!("download released vestad: {e}"))?;
    if !output.status.success() {
        return Err(format!("failed to download released vestad artifact from {url}"));
    }

    let output = Command::new("tar")
        .args(["-xzf"])
        .arg(&archive_path)
        .args(["-C"])
        .arg(tmpdir.path())
        .output()
        .map_err(|e| format!("extract released vestad: {e}"))?;
    if !output.status.success() {
        return Err("failed to extract released vestad artifact".into());
    }

    let bin_path = tmpdir.path().join("vestad");
    if !bin_path.exists() {
        return Err("released vestad binary missing after extraction".into());
    }

    Ok(ReleasedVestad {
        _tmpdir: tmpdir,
        tag: tag.to_string(),
        bin_path,
    })
}
