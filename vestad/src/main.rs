#[cfg(not(target_os = "linux"))]
compile_error!("vestad only supports Linux");

use clap::Parser;

mod docker;
mod jwt;
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
    /// Print host URL and API key for client connections
    Info,
    /// Update vestad to the latest version
    Update,
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
    },
    /// Show current tunnel status
    Status,
    /// Tear down tunnel and DNS record
    Destroy,
}

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}

fn find_available_port() -> Option<u16> {
    std::net::TcpListener::bind(("0.0.0.0", 0))
        .ok()
        .and_then(|l| l.local_addr().ok())
        .map(|addr| addr.port())
}

fn config_dir() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| die("HOME not set"));
    std::path::PathBuf::from(home).join(".config/vesta/vestad")
}

fn read_vestad_port(config_dir: &std::path::Path) -> u16 {
    std::fs::read_to_string(config_dir.join("port"))
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or_else(|| die("could not read vestad port from config — is vestad running?"))
}

fn print_server_info(tunnel_url: Option<&str>, local_url: &str, api_key: &str) {
    eprintln!();
    if let Some(url) = tunnel_url {
        eprintln!("  \x1b[36mhost\x1b[0m    \x1b[1m{}\x1b[0m", url);
        eprintln!("  \x1b[36mlocal\x1b[0m   \x1b[2m{}\x1b[0m", local_url);
    } else {
        eprintln!("  \x1b[36mhost\x1b[0m    \x1b[1m{}\x1b[0m", local_url);
    }
    eprintln!("  \x1b[36mkey\x1b[0m     \x1b[33m{}\x1b[0m", api_key);
    eprintln!();
}

fn read_server_info(config: &std::path::Path) -> (Option<String>, Option<String>, Option<String>) {
    let api_key = std::fs::read_to_string(config.join("api-key"))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());

    let local_url = std::fs::read_to_string(config.join("port"))
        .ok()
        .map(|s| format!("https://0.0.0.0:{}", s.trim()));

    let tunnel_url = tunnel::get_tunnel_config(config)
        .map(|tc| format!("https://{}", tc.hostname));

    (tunnel_url, local_url, api_key)
}

fn run_server_foreground(port: Option<u16>, no_tunnel: bool) {
    let config = config_dir();

    docker::ensure_docker().unwrap_or_else(|e| die(&e));

    let port = port.unwrap_or_else(|| find_available_port().unwrap_or_else(|| die("no available port found")));

    let _pid_lock = serve::acquire_pid_lock(&config).unwrap_or_else(|e| die(&e));
    serve::write_port_file(&config, port);

    let api_key = serve::ensure_api_key(&config);
    let (cert_pem, key_pem, _fingerprint) = serve::ensure_tls(&config);

    let tunnel_url = if !no_tunnel {
        match tunnel::ensure_tunnel(&config) {
            Ok(tc) => Some(format!("https://{}", tc.hostname)),
            Err(e) => {
                tracing::warn!("tunnel setup failed: {e}, running without tunnel");
                None
            }
        }
    } else {
        None
    };

    let local_url = format!("https://0.0.0.0:{}", port);

    eprintln!();
    eprintln!("  \x1b[1;35mvestad\x1b[0m v{}", env!("CARGO_PKG_VERSION"));
    print_server_info(tunnel_url.as_deref(), &local_url, &api_key);

    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async {
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

            serve::run_server(port, api_key, cert_pem, key_pem, tunnel_url).await;

            if let Some(mut child) = tunnel_child {
                child.kill().await.ok();
            }
        });
}

fn run_server_systemd(port: Option<u16>, no_tunnel: bool) {
    if port.is_some() || no_tunnel {
        eprintln!("note: --port and --no-tunnel only apply with --standalone");
    }

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

    systemd::start().unwrap_or_else(|e| die(&e));
    systemd::wait_for_start().unwrap_or_else(|e| die(&e));

    let config = config_dir();
    let (tunnel_url, local_url, api_key) = read_server_info(&config);

    eprintln!();
    eprintln!("  \x1b[1;35mvestad\x1b[0m v{} is now running as a systemd service.", env!("CARGO_PKG_VERSION"));

    if let Some(api_key) = &api_key {
        print_server_info(
            tunnel_url.as_deref(),
            local_url.as_deref().unwrap_or("https://0.0.0.0:?"),
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
            eprintln!("  \x1b[1;35mvestad\x1b[0m v{}", env!("CARGO_PKG_VERSION"));

            let (tunnel_url, local_url, api_key) = read_server_info(&config);
            if let Some(api_key) = &api_key {
                print_server_info(
                    tunnel_url.as_deref(),
                    local_url.as_deref().unwrap_or("https://0.0.0.0:?"),
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
            eprintln!("vestad restarted.");
        }

        Command::Shell { name } => {
            docker::validate_name(&name).unwrap_or_else(|e| die(&e));
            let cname = docker::container_name(&name);
            docker::ensure_running(&cname).unwrap_or_else(|e| die(&e));

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

        Command::Backup { action } => match action {
            BackupAction::Export { name, output } => {
                docker::validate_name(&name).unwrap_or_else(|e| die(&e));
                let cname = docker::container_name(&name);

                let cs = docker::container_status(&cname);
                if cs == docker::ContainerStatus::NotFound {
                    die(format!("agent '{}' not found", name));
                }

                let was_running = cs == docker::ContainerStatus::Running;
                if was_running {
                    eprintln!("stopping agent...");
                    docker::docker_ok(&["stop", &cname]);
                }

                eprintln!("committing snapshot...");
                let temp_tag = format!("vesta-export:{}-temp", name);
                if !docker::docker_ok(&["commit", &cname, &temp_tag]) {
                    if was_running { docker::docker_ok(&["start", &cname]); }
                    die("docker commit failed");
                }

                if was_running {
                    docker::docker_ok(&["start", &cname]);
                }

                eprintln!("exporting to {}...", output.display());
                let output_str = output.to_string_lossy();
                let save_cmd = format!("docker save '{}' | gzip > '{}'", temp_tag, output_str);
                let status = std::process::Command::new("sh")
                    .args(["-c", &save_cmd])
                    .status()
                    .unwrap_or_else(|e| die(format!("docker save failed: {}", e)));

                docker::docker_ok(&["rmi", &temp_tag]);

                if !status.success() {
                    die("export failed");
                }
                eprintln!("exported: {}", output.display());
            }
            BackupAction::Import { name, input } => {
                docker::validate_name(&name).unwrap_or_else(|e| die(&e));

                if !input.exists() {
                    die(format!("file not found: {}", input.display()));
                }

                let cname = docker::container_name(&name);
                if docker::container_status(&cname) != docker::ContainerStatus::NotFound {
                    die(format!("agent '{}' already exists — destroy it first or pick a different name", name));
                }

                eprintln!("loading image from {}...", input.display());
                let input_str = input.to_string_lossy();
                let load_cmd = format!("gunzip -c '{}' | docker load", input_str);
                let output = std::process::Command::new("sh")
                    .args(["-c", &load_cmd])
                    .output()
                    .unwrap_or_else(|e| die(format!("docker load failed: {}", e)));

                if !output.status.success() {
                    die("docker load failed");
                }

                let stdout = String::from_utf8_lossy(&output.stdout);
                let loaded_image = stdout
                    .lines()
                    .filter_map(|l| l.strip_prefix("Loaded image: "))
                    .next_back()
                    .unwrap_or_else(|| die("could not determine loaded image from docker load output"));

                eprintln!("creating agent '{}'...", name);
                let port = find_available_port().unwrap_or_else(|| die("no available port"));
                let vestad_port = read_vestad_port(&config_dir());
                docker::create_container(&cname, loaded_image, port, &name, vestad_port)
                    .unwrap_or_else(|e| die(&e));

                if !docker::docker_ok(&["start", &cname]) {
                    die("failed to start imported agent");
                }
                eprintln!("imported: {} (port {})", name, port);
            }
        },

        Command::Tunnel { action } => {
            let config = config_dir();
            match action {
                TunnelAction::Setup { subdomain } => {
                    tunnel::setup_tunnel(&config, &subdomain)
                        .unwrap_or_else(|e| die(e));
                }
                TunnelAction::Status => {
                    match tunnel::get_tunnel_config(&config) {
                        Some(tc) => {
                            eprintln!("tunnel: https://{}", tc.hostname);
                            eprintln!("tunnel id: {}", tc.tunnel_id);
                        }
                        None => {
                            eprintln!("no tunnel configured");
                        }
                    }
                }
                TunnelAction::Destroy => {
                    tunnel::destroy_tunnel(&config)
                        .unwrap_or_else(|e| die(e));
                }
            }
        }

        Command::Info => {
            let config = config_dir();
            let (tunnel_url, local_url, api_key) = read_server_info(&config);

            let api_key = api_key.unwrap_or_else(|| die("no API key found — has vestad been started?"));
            let local_url = local_url.unwrap_or_else(|| die("no port file found — is vestad running?"));

            print_server_info(tunnel_url.as_deref(), &local_url, &api_key);
        }

        Command::Update => {
            let target = match std::env::consts::ARCH {
                "x86_64" => "x86_64-unknown-linux-gnu",
                "aarch64" => "aarch64-unknown-linux-gnu",
                other => die(format!("unsupported architecture: {}", other)),
            };

            let archive = format!("vestad-{}.tar.gz", target);
            let url = format!(
                "https://github.com/elyxlz/vesta/releases/latest/download/{}",
                archive
            );
            let tmp = format!("/tmp/vestad-update-{}", std::process::id());
            std::fs::create_dir_all(&tmp).ok();

            tracing::info!("downloading update...");
            let status = std::process::Command::new("curl")
                .args(["-fsSL", "-o", &format!("{}/{}", tmp, archive), &url])
                .status();
            if !status.map(|s| s.success()).unwrap_or(false) {
                die("failed to download update");
            }

            let status = std::process::Command::new("tar")
                .args(["-xzf", &format!("{}/{}", tmp, archive), "-C", &tmp])
                .status();
            if !status.map(|s| s.success()).unwrap_or(false) {
                die("failed to extract update");
            }

            let new_binary = format!("{}/vestad", tmp);
            self_replace::self_replace(&new_binary)
                .unwrap_or_else(|e| die(format!("failed to replace binary: {}", e)));

            std::fs::remove_dir_all(&tmp).ok();

            if let Err(e) = systemd::reinstall_service() {
                tracing::warn!("failed to update systemd service: {e}");
            }
            if systemd::is_active() {
                tracing::info!("restarting vestad...");
                systemd::restart().unwrap_or_else(|e| die(&e));
                tracing::info!("updated and restarted.");
            } else {
                tracing::info!("updated. run 'vestad' to start.");
            }
        }
    }
}
