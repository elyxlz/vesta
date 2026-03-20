use clap::Parser;

mod docker;
mod serve;

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
        /// Port to listen on
        #[arg(long, default_value = "7860")]
        port: u16,
    },
    /// Open a shell inside an agent container
    Shell {
        /// Agent name
        name: String,
    },
    /// Update vestad to the latest version
    Update,
}

fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}

fn config_dir() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| die("HOME not set"));
    std::path::PathBuf::from(home).join(".config/vesta")
}

fn main() {
    let cli = Cli::parse();

    match cli.command.unwrap_or(Command::Serve { port: 7860 }) {
        Command::Serve { port } => {
            let config = config_dir();

            // Ensure Docker is available
            docker::ensure_docker().unwrap_or_else(|e| die(&e));

            // Migrate legacy containers
            docker::maybe_migrate_legacy();

            // Acquire PID lock
            let _pid_lock = serve::acquire_pid_lock(&config).unwrap_or_else(|e| die(&e));

            // Generate/load API key and TLS cert
            let api_key = serve::ensure_api_key(&config);
            let (cert_pem, key_pem, fingerprint) = serve::ensure_tls(&config);

            eprintln!("api key: {}", config.join("api-key").display());
            eprintln!("tls cert fingerprint: {}", fingerprint);

            // Start async runtime and server
            tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .unwrap()
                .block_on(serve::run_server(port, api_key, cert_pem, key_pem));
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
                .unwrap_or_else(|e| die(&format!("docker exec failed: {}", e)));
            if !status.success() {
                std::process::exit(status.code().unwrap_or(1));
            }
        }

        Command::Update => {
            let target = match std::env::consts::ARCH {
                "x86_64" => "x86_64-unknown-linux-gnu",
                "aarch64" => "aarch64-unknown-linux-gnu",
                other => die(&format!("unsupported architecture: {}", other)),
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
                .unwrap_or_else(|e| die(&format!("failed to replace binary: {}", e)));

            std::fs::remove_dir_all(&tmp).ok();
            eprintln!("updated. restart vestad to use new version.");
        }
    }
}
