#[cfg(not(target_os = "linux"))]
compile_error!("vestad only supports Linux");

use clap::Parser;

mod agent_code;
mod backup;
mod docker;
mod jwt;
mod self_update;
mod serve;
mod service_proxy;
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
    let home = std::env::var("HOME").unwrap_or_else(|_| die("HOME not set"));
    std::path::PathBuf::from(home).join(".config/vesta/vestad")
}


fn print_server_info(tunnel_url: Option<&str>, local_url: &str, api_key: &str) {
    eprintln!();
    eprintln!("  \x1b[36mhost\x1b[0m  \x1b[2m(enter in the app's host field)\x1b[0m");
    if let Some(url) = tunnel_url {
        eprintln!("    \x1b[36mremote\x1b[0m  \x1b[1m{}\x1b[0m  \x1b[32m(recommended)\x1b[0m", url);
    }
    eprintln!("    \x1b[36mlocal\x1b[0m   \x1b[1m{}\x1b[0m  \x1b[2m(same machine only)\x1b[0m", local_url);
    eprintln!("  \x1b[36mkey\x1b[0m   \x1b[33m{}\x1b[0m", api_key);
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
    let port = resolve_port(port, &config);
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

    serve::update_agent_env_files(&config, port, tunnel_url.as_deref());

    let local_url = format!("http://localhost:{}", port + 1);

    let user = std::env::var("USER").or_else(|_| std::env::var("LOGNAME")).unwrap_or_else(|_| "unknown".into());
    eprintln!();
    eprintln!("  \x1b[1;35mvestad\x1b[0m v{} \x1b[2m(user: {}, port: {})\x1b[0m", env!("CARGO_PKG_VERSION"), user, port);
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

            let dev_mode = cfg!(debug_assertions) || std::env::var("VESTAD_DEV").is_ok();
            serve::run_server(port, api_key, cert_pem, key_pem, tunnel_url, config.clone(), docker.clone(), dev_mode).await;

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

    systemd::start().unwrap_or_else(|e| die(&e));
    systemd::wait_for_start().unwrap_or_else(|e| die(&e));

    let config = config_dir();
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
            eprintln!("  \x1b[1;35mvestad\x1b[0m v{}", env!("CARGO_PKG_VERSION"));

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
            eprintln!("vestad restarted.");
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
            self_update::perform_update().unwrap_or_else(|e| die(e.to_string()));
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
