//! A local stand-in for the release source vestad updates from: the two metadata endpoints and the
//! artifact, on GitHub's path scheme, so a vestad started with `VESTAD_RELEASES_BASE_URL` pointed
//! here installs a release the test built. Also builds that release: a vestad compiled with a
//! `VESTAD_VERSION_OVERRIDE` so the swapped binary really reports a newer version.

use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// Bytes the stalled artifact answers before it goes quiet, so curl has a live response to wait on.
const STALL_PREFIX: &[u8] = b"\x1f\x8b";
/// The length a stalled response claims, so curl keeps waiting for a body that never arrives.
const STALL_CONTENT_LENGTH: usize = 64 * 1024 * 1024;

/// What the artifact route does. The three ways a real download ends: it works, it hangs, or what
/// arrives is not an archive.
pub enum ArtifactMode {
    Serve(Vec<u8>),
    Stall,
    Corrupt,
}

/// A running fake release source. Serving stops when this is dropped.
pub struct FakeReleaseServer {
    base_url: String,
    stop: Arc<AtomicBool>,
    port: u16,
}

impl FakeReleaseServer {
    /// Serve `version` (e.g. `99.0.0`) as the one release, with `mode` deciding what the artifact
    /// download does. Binds an ephemeral loopback port, so suites never collide.
    pub fn start(version: &str, mode: ArtifactMode) -> Result<Self, String> {
        let listener =
            TcpListener::bind(("127.0.0.1", 0)).map_err(|e| format!("bind fake release: {e}"))?;
        let port = listener
            .local_addr()
            .map_err(|e| format!("read fake release port: {e}"))?
            .port();
        let stop = Arc::new(AtomicBool::new(false));

        let routes = Arc::new(Routes::new(version, mode)?);
        let stop_flag = stop.clone();
        std::thread::spawn(move || {
            for incoming in listener.incoming() {
                if stop_flag.load(Ordering::Relaxed) {
                    return;
                }
                let Ok(stream) = incoming else { continue };
                let routes = routes.clone();
                let stop_flag = stop_flag.clone();
                // One thread per connection: a stalled download must not block the next request.
                std::thread::spawn(move || routes.serve(stream, &stop_flag));
            }
        });

        Ok(Self {
            base_url: format!("http://127.0.0.1:{port}"),
            stop,
            port,
        })
    }

    /// What `VESTAD_RELEASES_BASE_URL` is set to for a vestad that should update from here.
    pub fn base_url(&self) -> &str {
        &self.base_url
    }
}

impl Drop for FakeReleaseServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        // Wake the accept loop so it observes the flag instead of parking until the process ends.
        let _ = TcpStream::connect(("127.0.0.1", self.port));
    }
}

struct Routes {
    tag: String,
    artifact_path: String,
    mode: ArtifactMode,
}

impl Routes {
    fn new(version: &str, mode: ArtifactMode) -> Result<Self, String> {
        Ok(Self {
            tag: format!("v{version}"),
            artifact_path: format!(
                "/releases/download/v{version}/vestad-{}.tar.gz",
                rust_target()?
            ),
            mode,
        })
    }

    fn serve(&self, mut stream: TcpStream, stop: &AtomicBool) {
        let Some(path) = read_request_path(&stream) else {
            return;
        };
        if path == "/releases/latest" {
            let body = format!(r#"{{"tag_name": "{}", "prerelease": false}}"#, self.tag);
            let _ = write_json(&mut stream, &body);
            return;
        }
        if path.starts_with("/releases?") {
            let body = format!(r#"[{{"tag_name": "{}", "prerelease": true}}]"#, self.tag);
            let _ = write_json(&mut stream, &body);
            return;
        }
        if path == self.artifact_path {
            self.serve_artifact(stream, stop);
            return;
        }
        let _ = stream.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n");
    }

    fn serve_artifact(&self, mut stream: TcpStream, stop: &AtomicBool) {
        match &self.mode {
            ArtifactMode::Serve(bytes) => {
                let _ = write_binary(&mut stream, bytes);
            }
            ArtifactMode::Corrupt => {
                let _ = write_binary(&mut stream, b"this is not a gzip tarball");
            }
            ArtifactMode::Stall => {
                let header = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/gzip\r\nContent-Length: {STALL_CONTENT_LENGTH}\r\n\r\n"
                );
                let _ = stream.write_all(header.as_bytes());
                let _ = stream.write_all(STALL_PREFIX);
                let _ = stream.flush();
                // Hold the connection open with the body unfinished: the download that never ends,
                // which is what leaves the update stuck on `Applying` for the test to kill.
                while !stop.load(Ordering::Relaxed) {
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
            }
        }
    }
}

fn read_request_path(stream: &TcpStream) -> Option<String> {
    let mut reader = BufReader::new(stream.try_clone().ok()?);
    let mut request_line = String::new();
    reader.read_line(&mut request_line).ok()?;
    request_line.split_whitespace().nth(1).map(str::to_string)
}

fn write_json(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let header = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
        body.len()
    );
    stream.write_all(header.as_bytes())?;
    stream.write_all(body.as_bytes())?;
    stream.flush()
}

fn write_binary(stream: &mut TcpStream, body: &[u8]) -> std::io::Result<()> {
    let header = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/gzip\r\nContent-Length: {}\r\n\r\n",
        body.len()
    );
    stream.write_all(header.as_bytes())?;
    stream.write_all(body)?;
    stream.flush()
}

/// The architecture triple the updater builds its artifact name from.
fn rust_target() -> Result<&'static str, String> {
    match std::env::consts::ARCH {
        "x86_64" => Ok("x86_64-unknown-linux-gnu"),
        "aarch64" => Ok("aarch64-unknown-linux-gnu"),
        other => Err(format!("unsupported architecture for the update e2e: {other}")),
    }
}

/// Pack `binary` the way a published release ships it: `vestad` at the root of a gzipped tar, which
/// is exactly what the updater extracts and swaps itself with.
pub fn release_archive_bytes(binary: &Path) -> Result<Vec<u8>, String> {
    let staging = tempfile::TempDir::new().map_err(|e| format!("archive tmpdir: {e}"))?;
    let staged = staging.path().join("vestad");
    std::fs::copy(binary, &staged).map_err(|e| format!("stage vestad for the archive: {e}"))?;
    let archive = staging.path().join("release.tar.gz");
    let output = Command::new("tar")
        .arg("-czf")
        .arg(&archive)
        .arg("-C")
        .arg(staging.path())
        .arg("vestad")
        .output()
        .map_err(|e| format!("tar the release archive: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "tar failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    std::fs::read(&archive).map_err(|e| format!("read the release archive: {e}"))
}

/// Build a vestad that reports `version` instead of the package version, and return its path. Its
/// own target dir under the workspace, so it neither fights the outer build's lock nor rebuilds the
/// world on every run: the first build in a fresh checkout is a full one (a couple of minutes),
/// every later run is incremental. `VESTAD_SKIP_APP_BUILD` keeps the embedded web app out of it, and
/// debug info is off, which is what keeps this second target dir and the archive it produces small.
pub fn build_vestad_with_version(version: &str) -> Result<PathBuf, String> {
    let crate_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or_else(|| "tests-integration lives inside the vestad crate dir".to_string())?
        .to_path_buf();
    let target_dir = crate_dir.join("target/update-e2e").join(version);
    let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string());
    let output = Command::new(cargo)
        .arg("build")
        .arg("-p")
        .arg("vestad")
        .arg("--manifest-path")
        .arg(crate_dir.join("Cargo.toml"))
        .env("CARGO_TARGET_DIR", &target_dir)
        .env("VESTAD_VERSION_OVERRIDE", version)
        .env("VESTAD_SKIP_APP_BUILD", "1")
        .env("CARGO_PROFILE_DEV_DEBUG", "0")
        // The outer cargo's jobserver is not ours to join; inheriting it warns on every build.
        .env_remove("CARGO_MAKEFLAGS")
        .env_remove("MAKEFLAGS")
        .output()
        .map_err(|e| format!("spawn cargo for the v{version} build: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "building vestad v{version} failed:\n{}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let binary = target_dir.join("debug/vestad");
    if !binary.exists() {
        return Err(format!("vestad v{version} missing at {}", binary.display()));
    }
    Ok(binary)
}
