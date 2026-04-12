pub mod client;
pub mod types;

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::LazyLock;
use std::time::Duration;

use client::Client;
use types::ServerConfig;

pub static SERVER: LazyLock<TestServer> = LazyLock::new(|| {
    kill_orphan_vestads();
    TestServer::start().unwrap_or_else(|e| panic!("failed to start test server: {e}"))
});

#[derive(Default)]
pub struct TestServerBuilder {
    user: Option<String>,
}

impl TestServerBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn user(mut self, user: &str) -> Self {
        self.user = Some(user.to_string());
        self
    }

    pub fn start(self) -> Result<TestServer, String> {
        TestServer::start_with_user(self.user)
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
    _tmpdir: tempfile::TempDir,
    pub config: ServerConfig,
    pub port: u16,
}

impl TestServer {
    pub fn start() -> Result<Self, String> {
        Self::start_with_user(None)
    }

    fn start_with_user(user: Option<String>) -> Result<Self, String> {
        rustls::crypto::ring::default_provider()
            .install_default()
            .ok();

        let tmpdir = tempfile::TempDir::new().map_err(|e| format!("tmpdir: {e}"))?;
        let home = tmpdir.path().to_path_buf();
        let vestad = find_vestad()?;

        let real_home = std::env::var("HOME").unwrap_or_default();
        let docker_config = format!("{}/.docker", real_home);

        let mut cmd = Command::new(&vestad);
        cmd.args(["serve", "--standalone", "--no-tunnel"])
            .env("HOME", &home)
            .env("DOCKER_CONFIG", &docker_config)
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        if let Some(ref user_name) = user {
            cmd.env("USER", user_name);
        }

        let process = cmd.spawn().map_err(|e| format!("spawn vestad: {e}"))?;

        let config_dir = home.join(".config/vesta/vestad");
        let port_path = config_dir.join("port");

        let startup_timeout = Duration::from_secs(30);
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
                return Err("vestad did not start within 30s".into());
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

    pub fn _tmpdir_path(&self) -> &std::path::Path {
        self._tmpdir.path()
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        if let Some(ref mut p) = self.process {
            let _ = p.kill();
            let _ = p.wait();
        }
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
