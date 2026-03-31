use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::LazyLock;
use std::time::Duration;

use vesta_common::client::Client;
use vesta_common::ServerConfig;

pub static SERVER: LazyLock<Option<TestServer>> = LazyLock::new(|| {
    match TestServer::start() {
        Ok(s) => Some(s),
        Err(e) => {
            eprintln!("skipping server tests: {e}");
            None
        }
    }
});

/// Get the test server or skip the test if unavailable.
#[macro_export]
macro_rules! server {
    () => {
        match harness::SERVER.as_ref() {
            Some(s) => s,
            None => {
                eprintln!("SKIPPED: vestad not available");
                return;
            }
        }
    };
}

pub struct TestServer {
    process: Option<Child>,
    _tmpdir: tempfile::TempDir,
    pub config: ServerConfig,
    #[allow(dead_code)]
    pub port: u16,
}

impl TestServer {
    pub fn start() -> Result<Self, String> {
        rustls::crypto::ring::default_provider()
            .install_default()
            .ok();

        let tmpdir = tempfile::TempDir::new().map_err(|e| format!("tmpdir: {e}"))?;
        let home = tmpdir.path().to_path_buf();
        let port = free_port()?;
        let vestad = find_vestad()?;

        // Preserve real HOME's Docker config so vestad can pull images
        let real_home = std::env::var("HOME").unwrap_or_default();
        let docker_config = format!("{}/.docker", real_home);

        let process = Command::new(&vestad)
            .args(["serve", "--port", &port.to_string()])
            .env("HOME", &home)
            .env("DOCKER_CONFIG", &docker_config)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("spawn vestad: {e}"))?;

        let addr: std::net::SocketAddr = ([127, 0, 0, 1], port).into();
        let deadline = std::time::Instant::now() + Duration::from_secs(30);
        loop {
            if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
                break;
            }
            if std::time::Instant::now() > deadline {
                return Err("vestad did not start within 30s".into());
            }
            std::thread::sleep(Duration::from_millis(100));
        }

        let config_dir = home.join(".config/vesta");
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
}

impl Drop for TestServer {
    fn drop(&mut self) {
        if let Some(ref mut p) = self.process {
            let _ = p.kill();
            let _ = p.wait();
        }
    }
}

/// RAII guard — destroys the agent on drop.
pub struct TestAgent<'a> {
    pub name: String,
    client: &'a Client,
}

impl<'a> TestAgent<'a> {
    pub fn create(client: &'a Client, name: &str) -> Result<Self, String> {
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

fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| format!("bind: {e}"))?;
    Ok(listener.local_addr().map_err(|e| format!("addr: {e}"))?.port())
}

fn find_vestad() -> Result<PathBuf, String> {
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
