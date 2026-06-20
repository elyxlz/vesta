#[cfg(not(target_os = "linux"))]
compile_error!("vestad only supports Linux");

use clap::Parser;
use qrcode::{render::unicode, QrCode};

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
mod defaults;
mod docker;
mod jwt;
mod paths;
mod providers;
mod restic;
mod restic_embed;
mod time_utils;
mod self_update;
mod serve;
mod systemd;
mod tunnel;
mod types;
mod update_check;


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
    /// Attach to the agent's live claude session to watch (read-only) what it's doing
    Attach {
        /// Agent name
        name: String,
        /// Allow typing into the session. Risky: keystrokes race the agent's own driver
        #[arg(long)]
        write: bool,
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

/// Shell run inside the agent container to attach to the live claude session.
///
/// The claude TUI runs under a cc_sdk-named tmux socket (`ccsdk_<suffix>`) in the default
/// per-uid socket dir; discover the newest one and attach to its session. Attaches read-only
/// (`-r`) unless `write` is set: the agent's own driver is writing this same pane, so an
/// unguarded second writer would inject keystrokes into claude's input and race it.
fn attach_script(name: &str, write: bool) -> String {
    let attach_flags = if write { "" } else { "-r" };
    format!(
        "sock=$(ls -t /tmp/tmux-0/ccsdk_* 2>/dev/null | head -1); \
         if [ -z \"$sock\" ]; then echo 'no live claude session found for {name}'; exit 1; fi; \
         exec tmux -S \"$sock\" attach {attach_flags}"
    )
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
fn color_on() -> bool {
    use std::io::IsTerminal;
    std::io::stderr().is_terminal() && std::env::var_os("NO_COLOR").is_none()
}

/// Wrap `s` in ANSI `code` (e.g. "1;35"), but only when color is enabled.
fn paint(code: &str, s: &str) -> String {
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

/// Build the one-click connect link: the app reads the key from the URL
/// fragment (`#k=...`), which browsers never send to the server, so the key
/// stays out of vestad's and Cloudflare's request logs. Opening the link
/// connects automatically, no copy-pasting the key.
fn connect_link(base_url: &str, api_key: &str) -> String {
    format!("{base_url}/app#k={api_key}")
}

/// Render `data` as a QR code of half-block characters, inverted (light
/// modules on a dark glyph) so it scans correctly against a dark terminal.
/// Silently skips on the rare encode failure rather than failing the command.
fn print_qr(data: &str) {
    if let Ok(code) = QrCode::new(data.as_bytes()) {
        let rendered = code
            .render::<unicode::Dense1x2>()
            .dark_color(unicode::Dense1x2::Light)
            .light_color(unicode::Dense1x2::Dark)
            .quiet_zone(true)
            .build();
        for line in rendered.lines() {
            eprintln!("  {line}");
        }
    }
}

fn print_server_info(tunnel_url: Option<&str>, local_url: &str, api_key: &str) {
    eprintln!();
    match tunnel_url {
        Some(url) => {
            let link = connect_link(url, api_key);
            eprintln!("  {} {}", paint("36", "connect"), paint("1", &link));
            eprintln!("          {}", paint("2", "open this link to connect the app; the key is built in"));
            eprintln!();
            print_qr(&link);
            eprintln!("  {}", paint("2", "or scan to connect your phone"));
        }
        // A missing tunnel is a first-class, visible state — never a silent
        // "local only". Tell the user the exact command to fix it.
        None => {
            eprintln!(
                "  {} {}  {}",
                paint("36", "connect"),
                paint("1", &connect_link(local_url, api_key)),
                paint("2", "(same machine only)"),
            );
            eprintln!(
                "          run {} for a public URL + a phone QR code",
                paint("1", "vestad connect"),
            );
            eprintln!();
            return;
        }
    }
    eprintln!();
    eprintln!(
        "  {} {}  {}",
        paint("36", "local  "),
        paint("1", &connect_link(local_url, api_key)),
        paint("2", "(same machine only)"),
    );
    eprintln!();
}

/// Print connection info when an API key is present (the shape shared by `status`
/// and the systemd start path), taking the `read_server_info` tuple directly.
fn print_server_info_opt(info: (Option<String>, Option<String>, Option<String>)) {
    let (tunnel_url, local_url, api_key) = info;
    if let Some(api_key) = &api_key {
        print_server_info(tunnel_url.as_deref(), local_url.as_deref().unwrap_or("http://localhost:?"), api_key);
    }
}

fn read_server_info(config: &std::path::Path) -> (Option<String>, Option<String>, Option<String>) {
    let api_key = std::fs::read_to_string(config.join("api-key"))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());

    let local_url = read_port_file(config).map(|port| format!("http://localhost:{}", port + 1));

    let tunnel_url = tunnel::get_tunnel_config(config)
        .map(|tc| format!("https://{}", tc.hostname));

    (tunnel_url, local_url, api_key)
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

fn run_server_foreground(port: Option<u16>, no_tunnel: bool) {
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

            let tunnel_url = if no_tunnel {
                None
            } else {
                match tunnel::ensure_cloudflared(&config).and_then(|_| tunnel::ensure_tunnel(&config)) {
                    Ok(tc) => Some(format!("https://{}", tc.hostname)),
                    Err(e) => {
                        tracing::warn!("tunnel setup failed: {e}, running without tunnel");
                        None
                    }
                }
            };

            docker::update_all_agent_env_files(&config.join("agents"), port, tunnel_url.as_deref());
            let local_url = format!("http://localhost:{}", port + 1);
            let user = std::env::var("USER").or_else(|_| std::env::var("LOGNAME")).unwrap_or_else(|_| "unknown".into());
            eprintln!();
            eprintln!("  \x1b[1;35mvestad\x1b[0m v{} \x1b[2m(user: {}, port: {})\x1b[0m", env!("CARGO_PKG_VERSION"), user, port);
            print_server_info(tunnel_url.as_deref(), &local_url, &api_key);

            // Supervise whenever a tunnel is INTENDED, not only when boot-time
            // setup succeeded: a managed box whose tunnel.json the control plane
            // is still seeding, or a transient ensure_tunnel failure, must not
            // leave the daemon tunnel-less until a manual restart. The supervisor
            // re-reads tunnel.json on every respawn, so late config is picked up.
            let tunnel_intended = tunnel_url.is_some()
                || (!no_tunnel
                    && (is_cloud_managed() || tunnel::get_tunnel_config(&config).is_some()));
            let tunnel_supervisor =
                tunnel_intended.then(|| tunnel::supervise_tunnel(config.clone(), port));

            let dev_mode = cfg!(debug_assertions) || std::env::var("VESTAD_DEV").is_ok();
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

    print_server_info_opt(read_server_info(&config));

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

    match cli.command.unwrap_or(Command::Serve { port: None, no_tunnel: false, standalone: false }) {
        Command::Serve { port, no_tunnel, standalone } => {
            if standalone {
                run_server_foreground(port, no_tunnel);
            } else {
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

            print_server_info_opt(read_server_info(&config));

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

        Command::Attach { name, write } => {
            docker::validate_name(&name).unwrap_or_else(|e| die(&e));
            let docker = docker::connect().unwrap_or_else(|e| die(&e));
            let cname = docker::container_name(&name);
            let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
            rt.block_on(docker::ensure_running(&docker, &cname)).unwrap_or_else(|e| die(&e));

            let script = attach_script(&name, write);
            let mode = if write { "read-write" } else { "read-only" };
            eprintln!("attaching to {name}'s claude session ({mode}; detach with Ctrl-Q)…");
            docker_exec_inherit(&["exec", "-it", "--detach-keys=ctrl-q", &cname, "bash", "-lc", &script]);
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
                        docker::create_container(&docker, &cname, loaded_image, port, &name, &env_config, true, None).await
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

    #[test]
    fn attach_script_is_read_only_by_default() {
        let script = attach_script("vesta", false);
        assert!(script.contains("tmux -S \"$sock\" attach -r"));
        assert!(script.contains("ccsdk_*"));
        assert!(script.contains("no live claude session found for vesta"));
    }

    #[test]
    fn attach_script_drops_read_only_guard_when_write() {
        let script = attach_script("vesta", true);
        assert!(script.contains("tmux -S \"$sock\" attach "));
        assert!(!script.contains("attach -r"));
    }
}
