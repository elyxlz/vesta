#[cfg(not(target_os = "linux"))]
compile_error!("vestad only supports Linux");

use clap::Parser;

mod agent_provider;
mod agent_code;
mod agent_embed;
mod agent_proxy;
mod agent_status;
mod app_static;
mod auth;
mod backup;
mod channel;
mod cloudflared_embed;
mod control_ws;
mod docker;
mod manifest;
mod jwt;
mod paths;
mod providers;
mod restic;
mod restic_embed;
mod time_utils;
mod self_update;
mod serve;
mod status;
mod systemd;
mod tunnel;
mod types;
mod update_check;

use status::{Status, TunnelStatus};


#[derive(Parser)]
#[command(name = "vestad", version, about = "Vesta API server daemon")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(clap::Subcommand)]
enum Command {
    /// Start the server (default). Runs via systemd.
    Serve {
        /// Port to listen on (auto-selected if not specified)
        #[arg(long)]
        port: Option<u16>,
        /// Disable Cloudflare tunnel
        #[arg(long)]
        no_tunnel: bool,
        /// Run in foreground without systemd (for CI/dev)
        #[arg(long)]
        standalone: bool,
        /// Bind the HTTPS API to all interfaces so other devices on the LAN can
        /// connect (default: loopback only). Standalone mode only.
        #[arg(long)]
        expose_lan: bool,
    },
    /// Show vestad service status
    Status,
    /// Stream vestad service logs
    Logs {
        /// Number of lines to show
        #[arg(short, default_value = "50")]
        n: usize,
        /// Don't follow, just print and exit
        #[arg(long)]
        no_follow: bool,
    },
    /// Stop the vestad service
    Stop,
    /// Restart the vestad service
    Restart,
    /// Open a shell inside an agent container
    Shell {
        /// Agent name
        name: String,
    },
    /// Connect a Cloudflare domain so your agent gets a public URL
    Connect,
    /// Manage the Cloudflare tunnel (advanced)
    Tunnel {
        #[command(subcommand)]
        action: TunnelAction,
    },
    /// Export or import agent backups as files
    Backup {
        #[command(subcommand)]
        action: BackupAction,
    },
    /// Update vestad to the latest version
    Update,
    /// Uninstall vestad: stop service, remove config, and delete binary
    Uninstall,
    /// Print version information
    Version,
}

#[derive(clap::Subcommand)]
enum BackupAction {
    /// Export an agent to a compressed file
    Export {
        /// Agent name
        name: String,
        /// Output file path (.tar.gz)
        output: std::path::PathBuf,
    },
    /// Import an agent from a compressed file
    Import {
        /// Agent name to create
        name: String,
        /// Input file path (.tar.gz)
        input: std::path::PathBuf,
    },
}

#[derive(clap::Subcommand)]
enum TunnelAction {
    /// Create a named tunnel with a subdomain
    Setup {
        /// Subdomain name (e.g., "alice" for alice.yourdomain.com)
        subdomain: String,
        /// Emit a single line of JSON ({"tunnel_id","dns_record_id","hostname"})
        /// to stdout instead of human-readable output (for cloud-init / jq).
        #[arg(long)]
        json: bool,
    },
    /// Tear down tunnel and DNS record
    Destroy,
}

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}

/// Run `docker <args>` with the parent's stdio inherited (for interactive TTY
/// sessions), exiting with the child's code if it fails.
fn docker_exec_inherit(args: &[&str]) {
    let status = std::process::Command::new("docker")
        .args(args)
        .stdin(std::process::Stdio::inherit())
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .status()
        .unwrap_or_else(|e| die(format!("docker exec failed: {}", e)));
    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }
}

/// Whether to emit ANSI color: only when stderr is a real terminal and NO_COLOR
/// is unset. Without this, `vestad status > file` / piping captures raw escape
/// codes.
pub(crate) fn color_on() -> bool {
    use std::io::IsTerminal;
    std::io::stderr().is_terminal() && std::env::var_os("NO_COLOR").is_none()
}

/// Wrap `s` in ANSI `code` (e.g. "1;35"), but only when color is enabled.
pub(crate) fn paint(code: &str, s: &str) -> String {
    if color_on() {
        format!("\x1b[{code}m{s}\x1b[0m")
    } else {
        s.to_string()
    }
}

fn find_available_port() -> Option<u16> {
    // serve.rs binds HTTPS on 127.0.0.1:N and HTTP on 127.0.0.1:N+1, so both must be free.
    const MAX_ATTEMPTS: u8 = 16;
    for _ in 0..MAX_ATTEMPTS {
        let port = std::net::TcpListener::bind(("127.0.0.1", 0))
            .ok()
            .and_then(|l| l.local_addr().ok())
            .map(|addr| addr.port())?;
        let Some(http_port) = port.checked_add(1) else { continue };
        if std::net::TcpListener::bind(("127.0.0.1", http_port)).is_ok() {
            return Some(port);
        }
    }
    None
}

/// Read the stored HTTPS port from `<config>/port`, if present and parseable.
fn read_port_file(config: &std::path::Path) -> Option<u16> {
    std::fs::read_to_string(config.join("port")).ok().and_then(|s| s.trim().parse::<u16>().ok())
}

fn resolve_port(explicit: Option<u16>, config: &std::path::Path) -> u16 {
    if let Some(port) = explicit {
        return port;
    }

    if let Some(stored) = read_port_file(config) {
        if std::net::TcpListener::bind(("127.0.0.1", stored)).is_ok()
            && std::net::TcpListener::bind(("127.0.0.1", stored + 1)).is_ok()
        {
            return stored;
        }
        tracing::warn!(stored_port = stored, "stored port unavailable, allocating new one");
    }

    find_available_port()
        .unwrap_or_else(|| die("no free port found — another service may be using the range; try `vestad restart`"))
}

fn config_dir() -> std::path::PathBuf {
    paths::config_dir()
        .unwrap_or_else(|| die("couldn't find your home directory ($HOME) — vestad stores its config there"))
}

/// Read the stored API key from `<config>/api-key`, if present and non-empty.
fn read_api_key(config: &std::path::Path) -> Option<String> {
    std::fs::read_to_string(config.join("api-key"))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

/// True iff this VM is managed by the vesta-cloud control plane.
///
/// `VESTA_CLOUD_MANAGED` is the canonical gate (set by the control plane's
/// cloud-init drop-in); `VESTA_MANAGED` is the legacy name still present on VMs
/// provisioned before the rename. We accept BOTH so a box that self-updates to
/// this binary keeps its managed tunnel + server-identity behavior regardless of
/// which name its drop-in carries. This single bit gates ALL vesta-cloud
/// integration (managed tunnel, the `/info` managed flag, the account-token
/// endpoint).
pub fn is_cloud_managed() -> bool {
    std::env::var("VESTA_CLOUD_MANAGED").as_deref() == Ok("1")
        || std::env::var("VESTA_MANAGED").as_deref() == Ok("1")
}

const RESTART_LOCAL_READY_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(20);
const RESTART_TUNNEL_READY_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(25);
const RESTART_READY_POLL_INTERVAL: std::time::Duration = std::time::Duration::from_millis(500);
const HEALTH_PROBE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3);

/// After `vestad restart`, systemd marks the unit "active" the instant the process is
/// spawned — but the HTTP server is still binding and the Cloudflare tunnel needs several
/// seconds to re-establish its edge connections. In that window the tunnel returns 502
/// (no healthy origin yet), which reads like an error but is just startup. Poll `/health`
/// locally and through the tunnel so the message reflects what is actually reachable.
fn report_restart_readiness(config: &std::path::Path) {
    // The probe below can take tens of seconds (local API + tunnel reconnect), so
    // say what we're doing rather than appearing to hang.
    eprintln!("waiting for vestad to come back up…");
    let runtime = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
        Ok(runtime) => runtime,
        Err(e) => {
            eprintln!("vestad restarted (could not probe readiness: {e}).");
            return;
        }
    };
    runtime.block_on(async {
        let client = match reqwest::Client::builder().timeout(HEALTH_PROBE_TIMEOUT).build() {
            Ok(client) => client,
            Err(e) => {
                eprintln!("vestad restarted (could not probe readiness: {e}).");
                return;
            }
        };

        let local_ready = match local_health_url(config) {
            Some(url) => wait_for_health(&client, &url, RESTART_LOCAL_READY_TIMEOUT).await,
            None => false,
        };
        if !local_ready {
            eprintln!("vestad restarted, but its local API did not come up in time — check 'vestad logs'.");
            return;
        }

        match tunnel::get_tunnel_config(config) {
            None => eprintln!("vestad restarted and serving (no tunnel configured)."),
            Some(tc) => {
                let tunnel_health = format!("https://{}/health", tc.hostname);
                if wait_for_health(&client, &tunnel_health, RESTART_TUNNEL_READY_TIMEOUT).await {
                    eprintln!("vestad restarted and reachable at https://{}", tc.hostname);
                } else {
                    eprintln!(
                        "vestad restarted and serving locally; the tunnel (https://{}) is still \
                         reconnecting — a 502 for a few seconds is expected, not an error.",
                        tc.hostname
                    );
                }
            }
        }
    });
}

/// `http://127.0.0.1:<https_port + 1>/health` — the unauthenticated local HTTP API
/// (serve.rs binds HTTPS on the stored port and plain HTTP on port + 1).
fn local_health_url(config: &std::path::Path) -> Option<String> {
    let https_port = read_port_file(config)?;
    let http_port = https_port.checked_add(1)?;
    Some(format!("http://127.0.0.1:{http_port}/health"))
}

/// Poll `url` until it answers 2xx or `timeout` elapses. A connection refused / 5xx
/// just means "not ready yet", so keep retrying until the deadline.
async fn wait_for_health(client: &reqwest::Client, url: &str, timeout: std::time::Duration) -> bool {
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        if let Ok(resp) = client.get(url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        if tokio::time::Instant::now() >= deadline {
            return false;
        }
        tokio::time::sleep(RESTART_READY_POLL_INTERVAL).await;
    }
}

/// Best-effort primary LAN IPv4 — the source address the kernel uses to reach
/// off-box via the default route, i.e. the address other LAN devices can reach.
/// `ip route get` is used first so Docker/VPN bridge addresses (172.17.x and the
/// like, always present since vestad needs Docker) are skipped; it falls back to
/// the first non-loopback, non-Docker-bridge address from `hostname -I`. Either
/// way the result is covered by the TLS cert SANs. `None` if undeterminable.
fn local_lan_ip() -> Option<String> {
    // `ip -4 route get <external ip>` prints "<dst> via <gw> dev <if> src <LAN_IP> …".
    if let Ok(output) = std::process::Command::new("ip").args(["-4", "route", "get", "1.1.1.1"]).output() {
        let text = String::from_utf8_lossy(&output.stdout);
        if let Some(src) = text.split_whitespace().skip_while(|token| *token != "src").nth(1) {
            if let Ok(ip) = src.parse::<std::net::Ipv4Addr>() {
                if !ip.is_loopback() {
                    return Some(ip.to_string());
                }
            }
        }
    }
    // Fallback: first non-loopback IPv4 from `hostname -I`, skipping Docker's
    // default bridge range (172.17.0.0/16).
    let output = std::process::Command::new("hostname").arg("-I").output().ok()?;
    let ips = String::from_utf8_lossy(&output.stdout);
    ips.split_whitespace()
        .filter_map(|token| token.parse::<std::net::Ipv4Addr>().ok())
        .find(|ip| {
            let octets = ip.octets();
            !ip.is_loopback() && (octets[0] != 172 || octets[1] != 17)
        })
        .map(|ip| ip.to_string())
}

/// Bind the HTTP listener atomically inside the tokio runtime. If the HTTP port
/// (N+1) is in use, re-select a new N via find_available_port and retry. This
/// closes the TOCTOU race where find_available_port's probe was dropped before
/// serve.rs bound the port, letting a parallel vestad steal it.
async fn bind_http_atomically(
    explicit: Option<u16>,
    config: &std::path::Path,
) -> (u16, tokio::net::TcpListener) {
    const MAX_BIND_ATTEMPTS: u8 = 16;
    let mut port = resolve_port(explicit, config);
    for attempt in 0..MAX_BIND_ATTEMPTS {
        let Some(http_port) = port.checked_add(1) else {
            port = find_available_port().unwrap_or_else(|| die("no available port found"));
            continue;
        };
        match tokio::net::TcpListener::bind(("127.0.0.1", http_port)).await {
            Ok(listener) => return (port, listener),
            Err(e) if e.kind() == std::io::ErrorKind::AddrInUse => {
                if attempt + 1 == MAX_BIND_ATTEMPTS {
                    die(format!("http bind retries exhausted on port {}: {}", http_port, e));
                }
                tracing::warn!(port, http_port, "http port raced, reselecting");
                port = find_available_port().unwrap_or_else(|| die("no available port found"));
            }
            Err(e) => die(format!("failed to bind http listener: {}", e)),
        }
    }
    unreachable!()
}

/// How many times startup tries to bring the tunnel up before giving up and
/// starting anyway (with the failure shown in the banner). Absorbs a tunnel that
/// is slow to register right after boot — e.g. the network isn't up yet.
const TUNNEL_STARTUP_ATTEMPTS: u32 = 3;
const TUNNEL_STARTUP_RETRY_DELAY_SECS: u64 = 5;

/// Bring the tunnel up at startup, retrying before giving up. On success the
/// banner advertises the live URL and the supervisor keeps it alive; if every
/// attempt fails, vestad starts ANYWAY (local access + agents) with the error
/// surfaced in the banner — a broken tunnel must not block the rest of the box.
///
/// The /ready pre-flight is credential-free, so this works even on a box that
/// can't reach the Cloudflare API. Managed (vesta.run) boxes are exempt: the
/// control plane owns the tunnel, so we trust the seeded config and let the
/// supervisor (re)connect rather than pre-flighting.
async fn setup_and_verify_tunnel(config: &std::path::Path, port: u16) -> TunnelStatus {
    let status = retry_tunnel(
        TUNNEL_STARTUP_ATTEMPTS,
        std::time::Duration::from_secs(TUNNEL_STARTUP_RETRY_DELAY_SECS),
        |attempt| async move {
            let result = try_establish_tunnel(config, port).await;
            if let Err(reason) = &result {
                tracing::warn!(attempt, attempts = TUNNEL_STARTUP_ATTEMPTS, "tunnel not up: {reason}");
            }
            result
        },
    )
    .await;

    // Gave up. Drop the dead config (unless managed — the control plane owns it)
    // so the supervisor isn't started into a "Tunnel not found" loop. vestad then
    // starts anyway with the reason shown on the banner.
    if matches!(status, TunnelStatus::Failed(_)) && !is_cloud_managed() {
        tunnel::forget_tunnel(config);
    }
    status
}

/// Retry an async tunnel attempt up to `attempts` times, sleeping `delay` between
/// tries. Returns `Active` with the first URL that comes up, or `Failed` carrying
/// the last error once every attempt has failed.
async fn retry_tunnel<F, Fut>(attempts: u32, delay: std::time::Duration, mut attempt: F) -> TunnelStatus
where
    F: FnMut(u32) -> Fut,
    Fut: std::future::Future<Output = Result<String, String>>,
{
    let mut reason = "tunnel could not be established".to_string();
    for n in 1..=attempts {
        match attempt(n).await {
            Ok(url) => return TunnelStatus::Active(url),
            Err(e) => {
                reason = e;
                if n < attempts {
                    tokio::time::sleep(delay).await;
                }
            }
        }
    }
    TunnelStatus::Failed(reason)
}

/// One attempt to bring up and verify the tunnel. `Ok(url)` once it registers an
/// edge connection; `Err(reason)` describes why this attempt failed.
async fn try_establish_tunnel(config: &std::path::Path, port: u16) -> Result<String, String> {
    let tc = tunnel::ensure_cloudflared(config).and_then(|_| tunnel::ensure_tunnel(config))?;

    if is_cloud_managed() {
        return Ok(format!("https://{}", tc.hostname));
    }

    if tunnel::preflight_tunnel(config, port).await {
        return Ok(format!("https://{}", tc.hostname));
    }
    tracing::warn!(hostname = %tc.hostname, "saved tunnel failed to register");

    // With our own creds the tunnel may be fixable — recreate it from scratch
    // (new tunnel + token + DNS) and re-verify.
    if tunnel::has_cf_creds(config) {
        let subdomain = tc.hostname.split('.').next().unwrap_or("");
        let fresh = tunnel::setup_tunnel(config, subdomain)?;
        if tunnel::preflight_tunnel(config, port).await {
            tracing::info!(hostname = %fresh.hostname, "tunnel recreated and registered");
            return Ok(format!("https://{}", fresh.hostname));
        }
        return Err("recreated tunnel still could not register".to_string());
    }
    Err("saved tunnel could not register".to_string())
}

fn run_server_foreground(port: Option<u16>, no_tunnel: bool, expose_lan: bool) {
    let config = config_dir();

    let docker = docker::connect().unwrap_or_else(|e| die(&e));
    docker::ensure_docker_sync(&docker).unwrap_or_else(|e| die(&e));

    let _pid_lock = serve::acquire_pid_lock(&config).unwrap_or_else(|e| die(&e));
    // Kill orphaned cloudflared from a previous crash so it doesn't hold the port
    let cf_config = config.join("cloudflared.yml");
    if cf_config.exists() {
        std::process::Command::new("pkill")
            .args(["-f", &format!("cloudflared.*{}", cf_config.display())])
            .output().ok();
    }

    let api_key = serve::ensure_api_key(&config);
    let (cert_pem, key_pem, _fingerprint) = serve::ensure_tls(&config);

    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async {
            let (port, http_listener) = bind_http_atomically(port, &config).await;
            serve::write_port_file(&config, port);

            let tunnel_status = if no_tunnel {
                TunnelStatus::Disabled
            } else {
                setup_and_verify_tunnel(&config, port).await
            };
            let tunnel_url = tunnel_status.url().map(str::to_string);

            docker::update_all_agent_env_files(&config.join("agents"), port, tunnel_url.as_deref());
            // Only advertise a LAN address when the API is actually bound to the
            // LAN (--expose-lan); otherwise the URL would be unreachable.
            let lan_url = expose_lan
                .then(local_lan_ip)
                .flatten()
                .map(|ip| format!("https://{}:{}", ip, port));
            let user = std::env::var("USER").or_else(|_| std::env::var("LOGNAME")).unwrap_or_else(|_| "unknown".into());
            let dev_mode = cfg!(debug_assertions) || std::env::var("VESTAD_DEV").is_ok();

            // Build the status snapshot, persist it before the API opens (so any
            // reader that sees the daemon reachable also sees status.json), and
            // print the banner from it — the same banner `vestad status` renders.
            let status = Status::new(
                env!("CARGO_PKG_VERSION").to_string(),
                user,
                port,
                dev_mode,
                expose_lan,
                lan_url.clone(),
                tunnel_status,
            );
            status.persist(&config);
            status.print_banner(&api_key);

            // Supervise whenever a tunnel is INTENDED, not only when boot-time
            // setup succeeded: a managed box whose tunnel.json the control plane
            // is still seeding, or a transient ensure_tunnel failure, must not
            // leave the daemon tunnel-less until a manual restart. The supervisor
            // re-reads tunnel.json on every respawn, so late config is picked up.
            let tunnel_intended = tunnel_url.is_some()
                || (!no_tunnel
                    && (is_cloud_managed() || tunnel::get_tunnel_config(&config).is_some()));

            // Keep status.json honest: on a SUSTAINED tunnel outage the supervisor
            // flips the tunnel field to an error and back to enabled on recovery.
            // Transient blips it recovers from on its own don't change it.
            let status = std::sync::Arc::new(std::sync::Mutex::new(status));
            let on_tunnel_up: std::sync::Arc<dyn Fn(bool) + Send + Sync> = {
                let status = status.clone();
                let config = config.clone();
                let tunnel_url = tunnel_url.clone();
                std::sync::Arc::new(move |up: bool| {
                    let next = if up {
                        match tunnel_url.clone().or_else(|| {
                            tunnel::get_tunnel_config(&config).map(|tc| format!("https://{}", tc.hostname))
                        }) {
                            Some(url) => TunnelStatus::Active(url),
                            None => return, // can't name the URL; leave the field as-is
                        }
                    } else {
                        TunnelStatus::Failed("tunnel connection lost".to_string())
                    };
                    if let Ok(mut s) = status.lock() {
                        s.set_tunnel(next);
                        s.persist(&config);
                    }
                })
            };
            let tunnel_supervisor = tunnel_intended
                .then(|| tunnel::supervise_tunnel(config.clone(), port, on_tunnel_up));

            serve::run_server(serve::ServerConfig {
                port,
                http_listener,
                api_key,
                cert_pem,
                key_pem,
                tunnel_url,
                config_dir: config.clone(),
                docker: docker.clone(),
                dev_mode,
                expose_lan,
                lan_url,
            }).await;

            if let Some(supervisor) = tunnel_supervisor {
                supervisor.shutdown().await;
            }
        });
}

fn run_server_systemd(port: Option<u16>, no_tunnel: bool) {
    if port.is_some() || no_tunnel {
        eprintln!("note: --port and --no-tunnel only apply with --standalone");
    }

    let docker = docker::connect().unwrap_or_else(|e| die(&e));
    docker::ensure_docker_sync(&docker).unwrap_or_else(|e| die(&e));
    systemd::ensure_service_installed().unwrap_or_else(|e| die(&e));

    if systemd::is_active() {
        if let Some(pid) = systemd::main_pid() {
            eprintln!("vestad is already running (pid {}).", pid);
        } else {
            eprintln!("vestad is already running.");
        }
        eprintln!("run 'vestad logs' to see output, or 'vestad restart' to restart.");
        return;
    }

    // Forced BYOK: the service runs the tunnel non-interactively, so collect the
    // self-hoster's Cloudflare credentials HERE (while we still have a terminal),
    // before starting it. Skipped when: a tunnel is already configured, creds
    // already exist, or this is a managed (vesta.run) VM whose tunnel.json the
    // control plane seeds. `--no-tunnel` is honored only in --standalone mode.
    let config = config_dir();
    if !is_cloud_managed()
        && tunnel::get_tunnel_config(&config).is_none()
        && !tunnel::has_cf_creds(&config)
    {
        tunnel::setup_cf_creds_interactive(&config).unwrap_or_else(|e| die(e));
    }

    systemd::start().unwrap_or_else(|e| die(&e));
    systemd::wait_for_start().unwrap_or_else(|e| die(&e));

    eprintln!();
    eprintln!("  \x1b[1;35mvestad\x1b[0m v{} is now running as a systemd service.", env!("CARGO_PKG_VERSION"));
    eprintln!("  run {} to see your connection info.", paint("1", "vestad status"));
    eprintln!();

    eprintln!("manage with:");
    eprintln!("  vestad status     show status + your URL");
    eprintln!("  vestad connect    connect a domain for a public URL");
    eprintln!("  vestad logs       show service logs");
    eprintln!("  vestad restart    restart the service");
    eprintln!("  vestad update     update to the latest version");
    eprintln!("  vestad stop       stop the service");
}

fn main() {
    dotenvy::dotenv().ok();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(false)
        .init();

    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install crypto provider");

    let cli = Cli::parse();

    match cli.command.unwrap_or(Command::Serve { port: None, no_tunnel: false, standalone: false, expose_lan: false }) {
        Command::Serve { port, no_tunnel, standalone, expose_lan } => {
            if standalone {
                run_server_foreground(port, no_tunnel, expose_lan);
            } else {
                if expose_lan {
                    eprintln!("note: --expose-lan only applies with --standalone");
                }
                run_server_systemd(port, no_tunnel);
            }
        }

        Command::Status => {
            let config = config_dir();
            let binary_path = std::env::current_exe()
                .map(|p| p.display().to_string())
                .unwrap_or_else(|_| "<unknown>".into());
            let agent_count = std::fs::read_dir(config.join("agents"))
                .map(|rd| rd.filter_map(Result::ok)
                    .filter(|e| e.file_name().to_string_lossy().ends_with(".env"))
                    .count())
                .unwrap_or(0);

            eprintln!();
            eprintln!(
                "  \x1b[1;35mvestad\x1b[0m v{} \x1b[2m({}, {} agent{})\x1b[0m",
                env!("CARGO_PKG_VERSION"),
                binary_path,
                agent_count,
                if agent_count == 1 { "" } else { "s" },
            );

            status::print_status_banner(&config, read_api_key(&config).as_deref());

            systemd::print_status();
        }

        Command::Logs { n, no_follow } => {
            systemd::exec_journal(n, !no_follow);
        }

        Command::Stop => {
            systemd::stop().unwrap_or_else(|e| die(&e));
            eprintln!("vestad stopped.");
        }

        Command::Restart => {
            systemd::restart().unwrap_or_else(|e| die(&e));
            report_restart_readiness(&config_dir());
        }

        Command::Shell { name } => {
            docker::validate_name(&name).unwrap_or_else(|e| die(&e));
            let docker = docker::connect().unwrap_or_else(|e| die(&e));
            let cname = docker::container_name(&name);
            let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
            rt.block_on(docker::ensure_running(&docker, &cname)).unwrap_or_else(|e| die(&e));

            eprintln!("entering {name} (exit with `exit`, or detach with Ctrl-Q)…");
            docker_exec_inherit(&["exec", "-it", "--detach-keys=ctrl-q", &cname, "bash"]);
        }

        Command::Backup { action } => {
            let docker = docker::connect().unwrap_or_else(|e| die(&e));
            let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();

            match action {
                BackupAction::Export { name, output } => {
                    docker::validate_name(&name).unwrap_or_else(|e| die(&e));
                    let _lock = backup::agent_file_lock(&name).unwrap_or_else(|e| die(&e));
                    let cname = docker::container_name(&name);

                    rt.block_on(async {
                        let cs = docker::container_status(&docker, &cname).await;
                        if cs == docker::ContainerStatus::NotFound {
                            die(format!("agent '{}' not found", name));
                        }

                        let was_running = cs == docker::ContainerStatus::Running;
                        if was_running {
                            eprintln!("stopping agent...");
                            docker::stop_container_with_timeout(&docker, &cname, backup::BACKUP_STOP_TIMEOUT_SECS).await
                                .unwrap_or_else(|e| die(format!("failed to stop container: {}", e)));
                        }

                        eprintln!("snapshotting container...");
                        let temp_tag = format!("vesta-export:{}-temp", name);
                        if let Err(e) = docker::snapshot_container(&docker, &cname, &temp_tag, &[]).await {
                            if was_running {
                                docker::start_container(&docker, &cname).await;
                            }
                            die(format!("snapshot failed: {}", e));
                        }

                        if was_running {
                            docker::start_container(&docker, &cname).await;
                        }

                        eprintln!("exporting to {}...", output.display());
                        docker::export_image_gzip(&docker, &temp_tag, &output).await
                            .unwrap_or_else(|e| die(format!("export failed: {}", e)));

                        docker::remove_image(&docker, &temp_tag).await
                            .unwrap_or_else(|e| die(format!("failed to remove temp image: {}", e)));

                        eprintln!("exported: {}", output.display());
                    });
                }
                BackupAction::Import { name, input } => {
                    docker::validate_name(&name).unwrap_or_else(|e| die(&e));
                    let _lock = backup::agent_file_lock(&name).unwrap_or_else(|e| die(&e));

                    if !input.exists() {
                        die(format!("file not found: {}", input.display()));
                    }

                    let cname = docker::container_name(&name);

                    rt.block_on(async {
                        if docker::container_status(&docker, &cname).await != docker::ContainerStatus::NotFound {
                            die(format!("agent '{}' already exists — destroy it first or pick a different name", name));
                        }

                        eprintln!("loading image from {}...", input.display());
                        let loaded_image = docker::import_image_gzip(&docker, &input).await
                            .unwrap_or_else(|e| die(format!("import failed: {}", e)));
                        let loaded_image = loaded_image.as_str();

                        eprintln!("creating agent '{}'...", name);
                        let config = config_dir();
                        let vestad_port = read_port_file(&config).unwrap_or(0);
                        let vestad_tunnel = tunnel::get_tunnel_config(&config)
                            .map(|tc| format!("https://{}", tc.hostname));
                        let env_config = docker::AgentEnvConfig {
                            config_dir: config.clone(),
                            agents_dir: config.join("agents"),
                            vestad_port,
                            vestad_tunnel,
                        };
                        agent_code::ensure_agent_code(&config)
                            .unwrap_or_else(|e| die(format!("failed to populate agent code: {e}")));
                        let port = docker::allocate_port(&env_config.agents_dir).unwrap_or_else(|e| die(&e));
                        docker::create_container(&docker, &cname, loaded_image, port, &name, &env_config, true).await
                            .unwrap_or_else(|e| die(&e));

                        if !docker::start_container(&docker, &cname).await {
                            die("failed to start imported agent");
                        }
                        eprintln!("imported: {} (port {})", name, port);
                    });
                }
            }
        },

        Command::Connect => {
            let config = config_dir();
            // Collect the user's own Cloudflare creds, create the tunnel, then
            // restart the running service so it picks the tunnel up.
            let tc = tunnel::connect_interactive(&config).unwrap_or_else(|e| die(e));
            if systemd::is_active() {
                systemd::restart().unwrap_or_else(|e| die(&e));
            }
            eprintln!();
            eprintln!(
                "  {} your agent is live at {}",
                paint("32", "✓"),
                paint("1", &format!("https://{}/app", tc.hostname)),
            );
            eprintln!();
        }

        Command::Tunnel { action } => {
            let config = config_dir();
            match action {
                TunnelAction::Setup { subdomain, json } => {
                    let tc = tunnel::setup_tunnel(&config, &subdomain)
                        .unwrap_or_else(|e| die(e));
                    if json {
                        println!("{}", serde_json::json!({
                            "tunnel_id": tc.tunnel_id,
                            "dns_record_id": tc.dns_record_id,
                            "hostname": tc.hostname,
                        }));
                    } else {
                        eprintln!("✓ tunnel ready at https://{}", tc.hostname);
                    }
                }
                TunnelAction::Destroy => {
                    tunnel::destroy_tunnel(&config).unwrap_or_else(|e| die(e));
                    eprintln!("✓ tunnel removed");
                }
            }
        }

        Command::Update => {
            let outcome =
                self_update::perform_update(channel::Channel::effective()).unwrap_or_else(|e| die(e.to_string()));
            if !outcome.updated {
                println!("vestad already at the latest version (v{})", outcome.current);
            } else {
                println!("✓ updated v{} → v{}", outcome.current, outcome.latest);
                println!(
                    "{}",
                    if outcome.restarted {
                        "  service restarted on the new version."
                    } else {
                        "  run `vestad` to start the new version."
                    },
                );
            }
        }

        Command::Version => {
            println!("v{}", env!("CARGO_PKG_VERSION"));
        }

        Command::Uninstall => {
            eprint!("This will stop vestad, remove its systemd service, config, and binary. Continue? [y/N] ");
            use std::io::Write;
            std::io::stderr().flush().ok();
            let mut answer = String::new();
            if std::io::stdin().read_line(&mut answer).is_err() {
                eprintln!("failed to read input");
                std::process::exit(1);
            }
            if !answer.trim().eq_ignore_ascii_case("y") {
                eprintln!("Aborted.");
                std::process::exit(0);
            }

            if systemd::is_active() {
                eprintln!("stopping vestad service...");
                systemd::stop().unwrap_or_else(|e| eprintln!("warning: {}", e));
            }
            if let Err(err) = systemd::uninstall() {
                eprintln!("warning: {}", err);
            } else {
                eprintln!("  removed systemd service");
            }

            let config = config_dir();
            match std::fs::remove_dir_all(&config) {
                Ok(()) => eprintln!("  removed {}", config.display()),
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
                Err(err) => eprintln!("warning: failed to remove config: {}", err),
            }

            if let Some(tunnel_dir) = config.parent().map(|p| p.join("cloudflared")) {
                match std::fs::remove_dir_all(&tunnel_dir) {
                    Ok(()) => eprintln!("  removed {}", tunnel_dir.display()),
                    Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
                    Err(err) => eprintln!("warning: failed to remove cloudflared: {}", err),
                }
            }

            if let Ok(exe) = std::env::current_exe() {
                if let Err(err) = std::fs::remove_file(&exe) {
                    eprintln!("warning: could not remove binary {}: {}", exe.display(), err);
                    eprintln!("  remove it manually: rm {}", exe.display());
                } else {
                    eprintln!("  removed {}", exe.display());
                }
            }

            eprintln!("\nvestad has been uninstalled.");
            eprintln!("Note: Docker containers and images for agents are still intact.");
            eprintln!("To remove them too, run: docker rm -f $(docker ps -aq --filter name=vesta-)");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn retry_tunnel_succeeds_without_retrying_when_first_attempt_works() {
        let calls = std::cell::Cell::new(0u32);
        let status = retry_tunnel(3, std::time::Duration::ZERO, |_| {
            calls.set(calls.get() + 1);
            async { Ok::<String, String>("https://host".to_string()) }
        })
        .await;
        assert!(matches!(status, TunnelStatus::Active(url) if url == "https://host"));
        assert_eq!(calls.get(), 1, "should not retry once an attempt succeeds");
    }

    #[tokio::test]
    async fn retry_tunnel_retries_until_an_attempt_succeeds() {
        let calls = std::cell::Cell::new(0u32);
        let status = retry_tunnel(3, std::time::Duration::ZERO, |attempt| {
            calls.set(calls.get() + 1);
            async move {
                if attempt < 3 {
                    Err(format!("not up yet (attempt {attempt})"))
                } else {
                    Ok("https://up".to_string())
                }
            }
        })
        .await;
        assert!(matches!(status, TunnelStatus::Active(url) if url == "https://up"));
        assert_eq!(calls.get(), 3);
    }

    #[tokio::test]
    async fn retry_tunnel_gives_up_with_the_last_error_after_all_attempts() {
        let calls = std::cell::Cell::new(0u32);
        let status = retry_tunnel(3, std::time::Duration::ZERO, |attempt| {
            calls.set(calls.get() + 1);
            async move { Err::<String, String>(format!("boom {attempt}")) }
        })
        .await;
        assert!(matches!(status, TunnelStatus::Failed(reason) if reason == "boom 3"));
        assert_eq!(calls.get(), 3, "should try exactly `attempts` times before giving up");
    }

    #[test]
    fn local_health_url_targets_http_port_plus_one() {
        let dir = tempfile::tempdir().expect("tempdir");
        std::fs::write(dir.path().join("port"), "39565").expect("write port");
        assert_eq!(
            local_health_url(dir.path()).as_deref(),
            Some("http://127.0.0.1:39566/health"),
        );
    }

    #[test]
    fn local_health_url_none_without_port_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        assert_eq!(local_health_url(dir.path()), None);
    }
}
