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
    /// Manage Cloudflare tunnel
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
    /// Connect a Cloudflare account + domain for a self-hosted stable tunnel (BYOK)
    Login,
}

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}

fn find_available_port() -> Option<u16> {
    // serve.rs binds HTTPS on 0.0.0.0:N and HTTP on 127.0.0.1:N+1, so both must be free.
    const MAX_ATTEMPTS: u8 = 16;
    for _ in 0..MAX_ATTEMPTS {
        let port = std::net::TcpListener::bind(("0.0.0.0", 0))
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

fn resolve_port(explicit: Option<u16>, config: &std::path::Path) -> u16 {
    if let Some(port) = explicit {
        return port;
    }

    if let Some(stored) = std::fs::read_to_string(config.join("port"))
        .ok()
        .and_then(|s| s.trim().parse::<u16>().ok())
    {
        if std::net::TcpListener::bind(("0.0.0.0", stored)).is_ok()
            && std::net::TcpListener::bind(("127.0.0.1", stored + 1)).is_ok()
        {
            return stored;
        }
        tracing::warn!(stored_port = stored, "stored port unavailable, allocating new one");
    }

    find_available_port().unwrap_or_else(|| die("no available port found"))
}

fn config_dir() -> std::path::PathBuf {
    paths::config_dir().unwrap_or_else(|| die("HOME not set"))
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
    let https_port = std::fs::read_to_string(config.join("port"))
        .ok()
        .and_then(|stored| stored.trim().parse::<u16>().ok())?;
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

fn print_server_info(tunnel_url: Option<&str>, local_url: &str, api_key: &str) {
    eprintln!();
    if let Some(url) = tunnel_url {
        eprintln!("  \x1b[36mtunnel\x1b[0m  \x1b[1m{}\x1b[0m", url);
    }
    eprintln!("  \x1b[36mkey\x1b[0m     \x1b[33m{}\x1b[0m", api_key);
    eprintln!("  \x1b[36mapp\x1b[0m     \x1b[2m(open in a browser and paste the key)\x1b[0m");
    if let Some(url) = tunnel_url {
        eprintln!("    \x1b[36mremote\x1b[0m  \x1b[1m{}/app\x1b[0m  \x1b[32m(recommended)\x1b[0m", url);
    }
    eprintln!("    \x1b[36mlocal\x1b[0m   \x1b[1m{}/app\x1b[0m  \x1b[2m(same machine only)\x1b[0m", local_url);
    if tunnel_url.is_none() {
        eprintln!();
        eprintln!("  \x1b[33mtip:\x1b[0m run without --no-tunnel to get a remote URL");
    }
    eprintln!();
}

fn read_server_info(config: &std::path::Path) -> (Option<String>, Option<String>, Option<String>) {
    let api_key = std::fs::read_to_string(config.join("api-key"))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());

    let local_url = std::fs::read_to_string(config.join("port"))
        .ok()
        .and_then(|s| s.trim().parse::<u16>().ok())
        .map(|port| format!("http://localhost:{}", port + 1));

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

            let tunnel_child = if tunnel_url.is_some() {
                match tunnel::start_tunnel(&config, port).await {
                    Ok((child, _url)) => Some(child),
                    Err(e) => {
                        tracing::warn!("failed to start tunnel: {e}");
                        None
                    }
                }
            } else {
                None
            };

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

            if let Some(mut child) = tunnel_child {
                child.kill().await.ok();
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
    if std::env::var("VESTA_MANAGED").is_err()
        && tunnel::get_tunnel_config(&config).is_none()
        && !tunnel::has_cf_creds(&config)
    {
        tunnel::setup_cf_creds_interactive(&config).unwrap_or_else(|e| die(e));
    }

    systemd::start().unwrap_or_else(|e| die(&e));
    systemd::wait_for_start().unwrap_or_else(|e| die(&e));

    let (tunnel_url, local_url, api_key) = read_server_info(&config);

    eprintln!();
    eprintln!("  \x1b[1;35mvestad\x1b[0m v{} is now running as a systemd service.", env!("CARGO_PKG_VERSION"));

    if let Some(api_key) = &api_key {
        print_server_info(
            tunnel_url.as_deref(),
            local_url.as_deref().unwrap_or("http://localhost:?"),
            api_key,
        );
    }

    eprintln!("manage with:");
    eprintln!("  vestad status     show service status");
    eprintln!("  vestad logs       show service logs");
    eprintln!("  vestad restart    restart the service");
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

            let (tunnel_url, local_url, api_key) = read_server_info(&config);
            if let Some(api_key) = &api_key {
                print_server_info(
                    tunnel_url.as_deref(),
                    local_url.as_deref().unwrap_or("http://localhost:?"),
                    api_key,
                );
            }

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

            // Keep the docker exec -it subprocess as-is for TTY support
            let status = std::process::Command::new("docker")
                .args(["exec", "-it", "--detach-keys=ctrl-q", &cname, "bash"])
                .stdin(std::process::Stdio::inherit())
                .stdout(std::process::Stdio::inherit())
                .stderr(std::process::Stdio::inherit())
                .status()
                .unwrap_or_else(|e| die(format!("docker exec failed: {}", e)));
            if !status.success() {
                std::process::exit(status.code().unwrap_or(1));
            }
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
                        let vestad_port = std::fs::read_to_string(config.join("port"))
                            .ok()
                            .and_then(|s| s.trim().parse::<u16>().ok())
                            .unwrap_or(0);
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
                        docker::create_container(&docker, &cname, loaded_image, port, &name, &env_config, true, None, None, None).await
                            .unwrap_or_else(|e| die(&e));

                        if !docker::start_container(&docker, &cname).await {
                            die("failed to start imported agent");
                        }
                        eprintln!("imported: {} (port {})", name, port);
                    });
                }
            }
        },

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
                    }
                }
                TunnelAction::Destroy => {
                    tunnel::destroy_tunnel(&config)
                        .unwrap_or_else(|e| die(e));
                }
                TunnelAction::Login => {
                    tunnel::setup_cf_creds_interactive(&config)
                        .unwrap_or_else(|e| die(e));
                    eprintln!("Cloudflare connected. Run `vestad` to bring up your tunnel.");
                }
            }
        }

        Command::Update => {
            let outcome =
                self_update::perform_update(channel::Channel::effective()).unwrap_or_else(|e| die(e.to_string()));
            if !outcome.updated {
                println!("vestad already at latest version (v{})", outcome.current);
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
}
