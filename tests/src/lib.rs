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
    TestServer::start().unwrap_or_else(|e| panic!("failed to start test server: {e}"))
});

static TEST_USER_COUNTER: AtomicU32 = AtomicU32::new(0);
static TEST_AGENT_COUNTER: AtomicU32 = AtomicU32::new(0);

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

    pub fn start(self) -> Result<TestServer, String> {
        let user = self.user.unwrap_or_else(|| unique_user("test"));
        TestServer::start_with_options(Some(user), self.home, self.vestad_bin)
    }
}

/// Kill vestad processes left behind by previous test runs (those whose HOME is a
/// temp directory). Ignores the user's real vestad instance.
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
        Self::start_with_options(None, None, None)
    }

    fn start_with_options(user: Option<String>, home: Option<PathBuf>, vestad_bin: Option<PathBuf>) -> Result<Self, String> {
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

        let mut cmd = Command::new(&vestad);
        cmd.args(["serve", "--standalone", "--no-tunnel"])
            .env("HOME", &home)
            .env("DOCKER_CONFIG", &docker_config)
            .stdout(Stdio::null())
            .stderr(Stdio::from(stderr_file));

        if let Some(ref user_name) = user {
            cmd.env("USER", user_name);
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
        let name = client.create_agent(name, false)?;
        Ok(Self { name, client })
    }

    pub fn create_built(client: &'a Client, name: &str) -> Result<Self, String> {
        let _ = client.stop_agent(name);
        let _ = client.destroy_agent(name);
        let name = client.create_agent(name, true)?;
        Ok(Self { name, client })
    }

    pub fn create_with_manage_agent_code(client: &'a Client, name: &str) -> Result<Self, String> {
        let _ = client.stop_agent(name);
        let _ = client.destroy_agent(name);
        let name = client.create_agent_ex(name, false, Some(true))?;
        Ok(Self { name, client })
    }

    pub fn create_without_manage_agent_code(client: &'a Client, name: &str) -> Result<Self, String> {
        let _ = client.stop_agent(name);
        let _ = client.destroy_agent(name);
        let name = client.create_agent_ex(name, false, Some(false))?;
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

pub fn inject_fake_token(c: &Client, name: &str) {
    c.inject_token(name, FAKE_TOKEN).unwrap();
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

/// Container is up (regardless of auth/readiness state).
pub fn is_up(status: &str) -> bool {
    matches!(status, "not_authenticated" | "starting" | "alive" | "restarting")
}

pub struct ReleasedVestad {
    _tmpdir: tempfile::TempDir,
    pub tag: String,
    pub bin_path: PathBuf,
}

pub fn download_latest_released_vestad() -> Result<ReleasedVestad, String> {
    let output = Command::new("curl")
        .args([
            "-fsSL",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "User-Agent: vesta-tests",
            "https://api.github.com/repos/elyxlz/vesta/releases/latest",
        ])
        .output()
        .map_err(|e| format!("fetch latest release metadata: {e}"))?;
    if !output.status.success() {
        return Err("failed to fetch latest release metadata".into());
    }
    let body = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| format!("parse latest release metadata: {e}"))?;
    let tag = data
        .get("tag_name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "latest release tag missing".to_string())?
        .to_string();

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
        .args(["-fsSL", "-o"])
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
        tag,
        bin_path,
    })
}
