use clap::Parser;

mod docker;
mod jwt;
mod serve;
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
    /// Start HTTP+WS server (default)
    Serve {
        /// Port to listen on (auto-selected if not specified)
        #[arg(long)]
        port: Option<u16>,
        /// Disable Cloudflare tunnel
        #[arg(long)]
        no_tunnel: bool,
    },
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
    /// Print host URL and API key for client connections
    Info,
    /// Update vestad to the latest version
    Update,
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

fn main() {
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install crypto provider");

    let cli = Cli::parse();

    match cli.command.unwrap_or(Command::Serve { port: None, no_tunnel: false }) {
        Command::Serve { port, no_tunnel } => {
            let config = config_dir();

            docker::ensure_docker().unwrap_or_else(|e| die(&e));

            let port = port.unwrap_or_else(|| find_available_port().unwrap_or_else(|| die("no available port found")));

            let _pid_lock = serve::acquire_pid_lock(&config).unwrap_or_else(|e| die(&e));

            let api_key = serve::ensure_api_key(&config);
            let (cert_pem, key_pem, _fingerprint) = serve::ensure_tls(&config);

            let tunnel_url = if !no_tunnel {
                match tunnel::ensure_tunnel(&config) {
                    Ok(tc) => Some(format!("https://{}", tc.hostname)),
                    Err(e) => {
                        eprintln!("warning: tunnel setup failed ({}), running without tunnel", e);
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
                            Ok((child, _url)) => {

                                Some(child)
                            }
                            Err(e) => {
                                eprintln!("warning: failed to start tunnel: {}", e);
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

            let api_key = match std::fs::read_to_string(config.join("api-key")) {
                Ok(k) if !k.trim().is_empty() => k.trim().to_string(),
                _ => die("no API key found — has vestad been started?"),
            };

            let local_url = match std::fs::read_to_string(config.join("port")) {
                Ok(p) => format!("https://localhost:{}", p.trim()),
                _ => die("no port file found — is vestad running?"),
            };

            let tunnel_url = tunnel::get_tunnel_config(&config)
                .map(|tc| format!("https://{}", tc.hostname));

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

            eprintln!("downloading update...");
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
            eprintln!("updated. restart vestad to use new version.");
        }
    }
}

