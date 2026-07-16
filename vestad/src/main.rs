#[cfg(not(target_os = "linux"))]
compile_error!("vestad only supports Linux");

use clap::Parser;

mod agent_code;
mod agent_embed;
mod agent_provider;
mod agent_proxy;
mod agent_status;
mod app_static;
mod auth;
mod backup;
mod channel;
mod control_ws;
mod docker;
mod jwt;
mod manifest;
mod mounts;
mod paths;
mod providers;
mod restic;
mod self_log;
mod self_update;
mod serve;
mod settings;
mod state;
mod status;
mod systemd;
mod time_utils;
mod tunnel;
mod types;
mod update_check;
mod upstream;
mod vendored_bin;

use status::{paint, AgentEntry, Status, TunnelStatus};

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
        /// Expose the HTTPS API to other devices on your LAN (default: loopback only)
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
        /// Emit a single line of JSON ({"`tunnel_id","dns_record_id","hostname`"})
        /// to stdout instead of human-readable output (for cloud-init / jq).
        #[arg(long)]
        json: bool,
    },
    /// Tear down tunnel and DNS record
    Destroy,
}

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("error: {msg}");
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
        .unwrap_or_else(|e| die(format!("docker exec failed: {e}")));
    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
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
        let Some(http_port) = port.checked_add(1) else {
            continue;
        };
        if std::net::TcpListener::bind(("127.0.0.1", http_port)).is_ok() {
            return Some(port);
        }
    }
    None
}

/// Read the stored HTTPS port from `<config>/port`, if present and parseable.
fn read_port_file(config: &std::path::Path) -> Option<u16> {
    std::fs::read_to_string(config.join("port"))
        .ok()
        .and_then(|s| s.trim().parse::<u16>().ok())
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
        tracing::warn!(
            stored_port = stored,
            "stored port unavailable, allocating new one"
        );
    }

    find_available_port().unwrap_or_else(|| {
        die("no free port found — another service may be using the range; try `vestad restart`")
    })
}

fn config_dir() -> std::path::PathBuf {
    paths::config_dir().unwrap_or_else(|| {
        die("couldn't find your home directory ($HOME) — vestad stores its config there")
    })
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
/// `VESTA_CLOUD_MANAGED` is the sole gate (set by the control plane's cloud-init
/// drop-in). This single bit gates ALL vesta-cloud integration (managed tunnel,
/// the `/info` managed flag, the account-token endpoint).
pub fn is_cloud_managed() -> bool {
    std::env::var("VESTA_CLOUD_MANAGED").as_deref() == Ok("1")
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
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(e) => {
            eprintln!("vestad restarted (could not probe readiness: {e}).");
            return;
        }
    };
    runtime.block_on(async {
        let client = match reqwest::Client::builder()
            .timeout(HEALTH_PROBE_TIMEOUT)
            .build()
        {
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
            eprintln!(
                "vestad restarted, but its local API did not come up in time. check 'vestad logs'."
            );
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
    let health_port = https_port.checked_add(1)?;
    Some(format!("http://127.0.0.1:{health_port}/health"))
}

/// Poll `url` until it answers 2xx or `timeout` elapses. A connection refused / 5xx
/// just means "not ready yet", so keep retrying until the deadline.
async fn wait_for_health(
    client: &reqwest::Client,
    url: &str,
    timeout: std::time::Duration,
) -> bool {
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
    if let Ok(output) = std::process::Command::new("ip")
        .args(["-4", "route", "get", "1.1.1.1"])
        .output()
    {
        let text = String::from_utf8_lossy(&output.stdout);
        if let Some(src) = text
            .split_whitespace()
            .skip_while(|token| *token != "src")
            .nth(1)
        {
            if let Ok(ip) = src.parse::<std::net::Ipv4Addr>() {
                if !ip.is_loopback() {
                    return Some(ip.to_string());
                }
            }
        }
    }
    // Fallback: first non-loopback IPv4 from `hostname -I`, skipping Docker's
    // default bridge range (172.17.0.0/16).
    let output = std::process::Command::new("hostname")
        .arg("-I")
        .output()
        .ok()?;
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
/// (N+1) is in use, re-select a new N via `find_available_port` and retry. This
/// closes the TOCTOU race where `find_available_port`'s probe was dropped before
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
                    die(format!(
                        "http bind retries exhausted on port {http_port}: {e}"
                    ));
                }
                tracing::warn!(port, http_port, "http port raced, reselecting");
                port = find_available_port().unwrap_or_else(|| die("no available port found"));
            }
            Err(e) => die(format!("failed to bind http listener: {e}")),
        }
    }
    unreachable!()
}

fn run_server_foreground(port: Option<u16>, no_tunnel: bool, expose_lan: bool) {
    let config = config_dir();

    // The systemd unit launches `serve --standalone` with no flag, so the
    // persisted preference is the source of truth; an explicit --standalone
    // --expose-lan (CI/dev) still wins.
    let expose_lan = expose_lan || settings::expose_lan_setting();

    let docker = docker::connect().unwrap_or_else(|e| die(&e));
    docker::ensure_docker_sync(&docker).unwrap_or_else(|e| die(&e));

    let _pid_lock = serve::acquire_pid_lock(&config).unwrap_or_else(|e| die(&e));
    // Kill orphaned cloudflared from a previous crash so it doesn't hold the port
    let cf_config = config.join("cloudflared.yml");
    if cf_config.exists() {
        std::process::Command::new("pkill")
            .args(["-f", &format!("cloudflared.*{}", cf_config.display())])
            .output()
            .ok();
    }

    let api_key = serve::ensure_api_key(&config).unwrap_or_else(|e| die(&e));
    let (cert_pem, key_pem, _fingerprint) = serve::ensure_tls(&config).unwrap_or_else(|e| die(&e));

    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime builds")
        .block_on(async {
            let (port, http_listener) = bind_http_atomically(port, &config).await;
            serve::write_port_file(&config, port);

            // Best-effort convergence before the surfaces below read
            // tunnel.json: create a missing tunnel (fresh BYOK box) or
            // reconcile a changed pinned subdomain, so agent env files, /info,
            // and the banner get the right identity URL on first boot. Failure
            // is fine here; the supervisor keeps converging after boot.
            let byok_tunnel_wanted =
                tunnel::has_cf_creds(&config) && !tunnel::has_declined_tunnel(&config);
            if !no_tunnel && !is_cloud_managed() && byok_tunnel_wanted {
                if let Err(e) = tunnel::ensure_tunnel(&config) {
                    tracing::warn!("boot tunnel converge failed (supervisor will retry): {e}");
                }
            }

            // Boot renders no verdict on tunnel health: the supervisor owns
            // establish/verify/repair and mirrors sustained state into
            // status.json via on_tunnel_up. Boot only decides whether a tunnel
            // is intended and advertises the identity URL from tunnel.json
            // (read after the converge above, which may have just created it).
            let saved_url = tunnel::get_tunnel_config(&config).map(|tc| tc.url());
            let tunnel_intended =
                !no_tunnel && (is_cloud_managed() || saved_url.is_some() || byok_tunnel_wanted);
            let tunnel_url = if tunnel_intended { saved_url } else { None };
            let tunnel_status = if no_tunnel {
                TunnelStatus::Disabled
            } else if tunnel_intended {
                TunnelStatus::Connecting(tunnel_url.clone())
            } else {
                TunnelStatus::Failed(
                    "no tunnel configured: run `vestad connect` to connect a domain".to_string(),
                )
            };

            docker::update_all_agent_env_files(&config.join("agents"), port, tunnel_url.as_deref());
            // Only advertise a LAN address when the API is actually bound to the
            // LAN (--expose-lan); otherwise the URL would be unreachable.
            let lan_url = expose_lan
                .then(local_lan_ip)
                .flatten()
                .map(|ip| format!("https://{ip}:{port}"));
            let user = std::env::var("USER")
                .or_else(|_| std::env::var("LOGNAME"))
                .unwrap_or_else(|_| "unknown".into());
            let dev_mode = cfg!(debug_assertions) || std::env::var("VESTAD_DEV").is_ok();

            // Build the status snapshot, persist it before the API opens (so any
            // reader that sees the daemon reachable also sees status.json), and
            // print the banner from it — the same banner `vestad status` renders.
            // Agents are seeded by name only (statuses unknown until the status
            // cache polls the just-started containers).
            let agents = docker::env_file_names(&config.join("agents"))
                .into_iter()
                .map(|name| AgentEntry { name, status: None })
                .collect();
            let status = Status {
                version: env!("CARGO_PKG_VERSION").to_string(),
                user,
                port,
                dev_mode,
                expose_lan,
                lan_url: lan_url.clone(),
                tunnel: tunnel_status,
                agents,
                pid: std::process::id(),
            };
            status.persist(&config);
            status.print_banner(&api_key);

            // Keep status.json honest: on a SUSTAINED tunnel outage the supervisor
            // flips the tunnel field to an error and back to enabled on recovery.
            // Transient blips it recovers from on its own don't change it.
            // Recovery guidance differs by who owns the tunnel: a managed
            // (vesta.run) tunnel is the control plane's to fix, a self-hosted
            // one is re-created by `vestad connect`.
            let tunnel_down_hint = if is_cloud_managed() {
                "tunnel down 2+ min; the vesta.run control plane owns it and should recover it"
            } else {
                "tunnel down 2+ min; if it persists, run vestad connect"
            };
            let status = std::sync::Arc::new(std::sync::Mutex::new(status));
            let on_tunnel_up: std::sync::Arc<dyn Fn(bool) + Send + Sync> = {
                let status = status.clone();
                let config = config.clone();
                let tunnel_url = tunnel_url.clone();
                std::sync::Arc::new(move |up: bool| {
                    let next = if up {
                        match tunnel::get_tunnel_config(&config)
                            .map(|tc| tc.url())
                            .or_else(|| tunnel_url.clone())
                        {
                            Some(url) => TunnelStatus::Active(url),
                            None => return, // can't name the URL; leave the field as-is
                        }
                    } else {
                        // Fired once the tunnel has been unregistered for
                        // TUNNEL_DOWN_SUSTAINED_SECS, whatever the failure mode
                        // (wedged connector, fast-exiting cloudflared, dead
                        // config): a general recovery hint, not revoked-specific.
                        TunnelStatus::Failed(tunnel_down_hint.to_string())
                    };
                    if let Ok(mut s) = status.lock() {
                        s.set_tunnel(next);
                        s.persist(&config);
                    }
                })
            };
            let tunnel_supervisor = tunnel_intended
                .then(|| tunnel::supervise_tunnel(config.clone(), port, on_tunnel_up));

            // Keep the agents section of status.json fresh: the agent-status cache
            // task invokes this whenever the polled agent list actually changes.
            let on_agents_changed: agent_status::OnAgentsChanged = {
                let status = status.clone();
                let config = config.clone();
                std::sync::Arc::new(move |entries: &[docker::ListEntry]| {
                    let agents = entries
                        .iter()
                        .map(|entry| AgentEntry {
                            name: entry.name.clone(),
                            status: Some(entry.status),
                        })
                        .collect();
                    if let Ok(mut s) = status.lock() {
                        s.set_agents(agents);
                        s.persist(&config);
                    }
                })
            };

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
                on_agents_changed,
            })
            .await;

            if let Some(supervisor) = tunnel_supervisor {
                supervisor.shutdown().await;
            }
        });
}

fn run_server_systemd(port: Option<u16>, no_tunnel: bool, expose_lan: bool) {
    if port.is_some() || no_tunnel {
        eprintln!("note: --port and --no-tunnel only apply with --standalone");
    }

    let docker = docker::connect().unwrap_or_else(|e| die(&e));
    docker::ensure_docker_sync(&docker).unwrap_or_else(|e| die(&e));
    systemd::ensure_service_installed().unwrap_or_else(|e| die(&e));

    // --expose-lan is a persisted binding preference (like the port file), not part
    // of the static unit. Write it before the daemon (re)starts so it reads the new
    // value; a running daemon only re-binds on restart.
    let lan_changed = settings::set_expose_lan(expose_lan);

    if systemd::is_active() {
        if lan_changed {
            systemd::restart().unwrap_or_else(|e| die(&e));
            eprintln!("vestad restarted to apply the --expose-lan change.");
            return;
        }
        if let Some(pid) = systemd::main_pid() {
            eprintln!("vestad is already running (pid {pid}).");
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
        && !tunnel::has_declined_tunnel(&config)
    {
        tunnel::setup_cf_creds_interactive(&config).unwrap_or_else(|e| die(e));
    }

    let start_time = std::time::SystemTime::now();
    systemd::start().unwrap_or_else(|e| die(&e));
    systemd::wait_for_start().unwrap_or_else(|e| die(&e));
    // The unit is not Type=notify, so being "active" only means the process
    // launched, not that async startup (tunnel dial, etc.) finished and wrote a
    // fresh status.json; wait for that so the banner below isn't stale/empty.
    Status::wait_for_fresh(&config, start_time);

    eprintln!();
    eprintln!(
        "  \x1b[1;35mvestad\x1b[0m v{} is now running as a systemd service.",
        env!("CARGO_PKG_VERSION")
    );
    status::print_status_banner(&config, read_api_key(&config).as_deref());
    eprintln!("scan the QR or open the link to create your first agent. manage with vestad status | logs | restart.");
}

/// Log to stdout (journald under systemd, the terminal under `cargo run`) and to a
/// rolling file under the config dir; the file is what the gateway logs viewer tails,
/// so the viewer works regardless of how vestad is run. A failed appender (no HOME,
/// unwritable dir) degrades to stdout-only rather than crashing the daemon.
///
/// ANSI is disabled on both sinks: the two fmt layers share one span-field cache in
/// the span extensions, so a colored stdout layer would bleed escape codes into the
/// plain file; the gateway logs viewer adds its own per-level color in the browser.
fn init_tracing() {
    use tracing_subscriber::prelude::*;

    let filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));

    let log_dir = paths::config_dir_or_relative();
    let file_layer = std::fs::create_dir_all(&log_dir)
        .ok()
        .and_then(|()| self_log::build_appender(&log_dir).ok())
        .map(|appender| {
            tracing_subscriber::fmt::layer()
                .with_target(false)
                .with_ansi(false)
                .with_writer(appender)
        });

    tracing_subscriber::registry()
        .with(filter)
        .with(
            tracing_subscriber::fmt::layer()
                .with_target(false)
                .with_ansi(false),
        )
        .with(file_layer)
        .init();
}

fn main() {
    dotenvy::dotenv().ok();

    init_tracing();

    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install crypto provider");

    let cli = Cli::parse();

    match cli.command.unwrap_or(Command::Serve {
        port: None,
        no_tunnel: false,
        standalone: false,
        expose_lan: false,
    }) {
        Command::Serve {
            port,
            no_tunnel,
            standalone,
            expose_lan,
        } => {
            if standalone {
                run_server_foreground(port, no_tunnel, expose_lan);
            } else {
                run_server_systemd(port, no_tunnel, expose_lan);
            }
        }

        Command::Status => {
            let config = config_dir();
            let binary_path = std::env::current_exe().map_or_else(|_| "<unknown>".into(), |p| p.display().to_string());
            let agent_count = std::fs::read_dir(config.join("agents"))
                .map(|rd| {
                    rd.filter_map(Result::ok)
                        .filter(|e| e.file_name().to_string_lossy().ends_with(".env"))
                        .count()
                })
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
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("tokio runtime builds");
            rt.block_on(docker::ensure_running(&docker, &cname))
                .unwrap_or_else(|e| die(&e));

            eprintln!("entering {name} (exit with `exit`, or detach with Ctrl-Q)…");
            docker_exec_inherit(&["exec", "-it", "--detach-keys=ctrl-q", &cname, "bash"]);
        }

        Command::Backup { action } => {
            let docker = docker::connect().unwrap_or_else(|e| die(&e));
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("tokio runtime builds");

            match action {
                BackupAction::Export { name, output } => {
                    docker::validate_name(&name).unwrap_or_else(|e| die(&e));
                    let _lock = backup::agent_file_lock(&name).unwrap_or_else(|e| die(&e));
                    let cname = docker::container_name(&name);

                    rt.block_on(async {
                        let cs = docker::container_status(&docker, &cname).await;
                        if cs == docker::ContainerStatus::NotFound {
                            die(format!("agent '{name}' not found"));
                        }

                        let was_running = cs == docker::ContainerStatus::Running;
                        if was_running {
                            eprintln!("stopping agent...");
                            docker::stop_container_with_timeout(
                                &docker,
                                &cname,
                                backup::BACKUP_STOP_TIMEOUT_SECS,
                            )
                            .await
                            .unwrap_or_else(|e| die(format!("failed to stop container: {e}")));
                        }

                        eprintln!("snapshotting container...");
                        let temp_tag = format!("vesta-export:{name}-temp");
                        if let Err(e) =
                            docker::snapshot_container(&docker, &cname, &temp_tag, &[]).await
                        {
                            if was_running {
                                docker::start_container(&docker, &cname).await;
                            }
                            die(format!("snapshot failed: {e}"));
                        }

                        if was_running {
                            docker::start_container(&docker, &cname).await;
                        }

                        eprintln!("exporting to {}...", output.display());
                        docker::export_image_gzip(&docker, &temp_tag, &output)
                            .await
                            .unwrap_or_else(|e| die(format!("export failed: {e}")));

                        docker::remove_image(&docker, &temp_tag)
                            .await
                            .unwrap_or_else(|e| die(format!("failed to remove temp image: {e}")));

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
                            die(format!("agent '{name}' already exists — destroy it first or pick a different name"));
                        }

                        eprintln!("loading image from {}...", input.display());
                        let loaded_image = docker::import_image_gzip(&docker, &input).await
                            .unwrap_or_else(|e| die(format!("import failed: {e}")));
                        let loaded_image = loaded_image.as_str();

                        eprintln!("creating agent '{name}'...");
                        let config = config_dir();
                        let vestad_port = read_port_file(&config).unwrap_or(0);
                        let vestad_tunnel = tunnel::get_tunnel_config(&config).map(|tc| tc.url());
                        let env_config = docker::AgentEnvConfig {
                            config_dir: config.clone(),
                            agents_dir: config.join("agents"),
                            vestad_port,
                            vestad_tunnel,
                        };
                        let code_dir = agent_code::ensure_agent_code(&config)
                            .unwrap_or_else(|e| die(format!("failed to populate agent code: {e}")));
                        // The container bind-mounts the upstream dir; build it here like server
                        // startup does, or rootful Docker would create the missing host path as
                        // root and the next vestad startup could no longer write into it.
                        upstream::ensure_upstream(&config, &code_dir).unwrap_or_else(|e| die(e.to_string()));
                        let port = docker::allocate_port(&env_config.agents_dir).unwrap_or_else(|e| die(&e));
                        docker::create_container(
                            &docker,
                            &env_config,
                            docker::ContainerSpec {
                                cname: &cname,
                                image: loaded_image,
                                port,
                                agent_name: &name,
                                manage_core_code: true,
                                user_mounts: &[],
                            },
                        )
                        .await
                        .unwrap_or_else(|e| die(&e));

                        if !docker::start_container(&docker, &cname).await {
                            die("failed to start imported agent");
                        }
                        eprintln!("imported: {name} (port {port})");
                    });
                }
            }
        }

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
                    let tc = tunnel::setup_tunnel(&config, &subdomain).unwrap_or_else(|e| die(e));
                    if json {
                        println!(
                            "{}",
                            serde_json::json!({
                                "tunnel_id": tc.tunnel_id,
                                "dns_record_id": tc.dns_record_id,
                                "hostname": tc.hostname,
                            })
                        );
                    } else {
                        eprintln!("✓ tunnel ready at https://{}", tc.hostname);
                    }
                }
                TunnelAction::Destroy => {
                    tunnel::destroy_tunnel(&config).unwrap_or_else(|e| die(e));
                    if let Err(e) = tunnel::decline_tunnel(&config) {
                        eprintln!(
                            "warning: tunnel destroyed but failed to persist the no-tunnel preference: {e}"
                        );
                    }
                    eprintln!("✓ tunnel removed");
                }
            }
        }

        Command::Update => {
            let outcome = self_update::perform_update(channel::Channel::effective())
                .unwrap_or_else(|e| die(e.to_string()));
            if outcome.updated {
                println!("✓ updated v{} → v{}", outcome.current, outcome.latest);
                println!(
                    "{}",
                    if outcome.restarted {
                        "  service restarted on the new version."
                    } else {
                        "  run `vestad` to start the new version."
                    },
                );
            } else {
                println!(
                    "vestad already at the latest version (v{})",
                    outcome.current
                );
            }
        }

        Command::Version => {
            println!("v{}", env!("CARGO_PKG_VERSION"));
        }

        Command::Uninstall => {
            use std::io::Write;

            eprint!("This will stop vestad, remove its systemd service, config, and binary. Continue? [y/N] ");
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
                systemd::stop().unwrap_or_else(|e| eprintln!("warning: {e}"));
            }
            if let Err(err) = systemd::uninstall() {
                eprintln!("warning: {err}");
            } else {
                eprintln!("  removed systemd service");
            }

            let config = config_dir();
            match std::fs::remove_dir_all(&config) {
                Ok(()) => eprintln!("  removed {}", config.display()),
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
                Err(err) => eprintln!("warning: failed to remove config: {err}"),
            }

            if let Some(tunnel_dir) = config.parent().map(|p| p.join("cloudflared")) {
                match std::fs::remove_dir_all(&tunnel_dir) {
                    Ok(()) => eprintln!("  removed {}", tunnel_dir.display()),
                    Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
                    Err(err) => eprintln!("warning: failed to remove cloudflared: {err}"),
                }
            }

            if let Ok(exe) = std::env::current_exe() {
                if let Err(err) = std::fs::remove_file(&exe) {
                    eprintln!(
                        "warning: could not remove binary {}: {}",
                        exe.display(),
                        err
                    );
                    eprintln!("  remove it manually: rm {}", exe.display());
                } else {
                    eprintln!("  removed {}", exe.display());
                }
            }

            eprintln!("\nvestad has been uninstalled.");
            eprintln!("Note: Docker containers and images for agents are still intact.");
            eprintln!(
                "To remove them too, run: docker rm -f $(docker ps -aq --filter name=vesta-)"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
