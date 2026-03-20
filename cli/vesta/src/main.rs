use clap::{Parser, Subcommand};
use std::io::{self, Write};
use std::path::PathBuf;
use std::process;

mod client;
mod platform;

fn try_open_browser(url: &str) {
    #[cfg(target_os = "linux")]
    let r = process::Command::new("xdg-open")
        .arg(url)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
    #[cfg(target_os = "macos")]
    let r = process::Command::new("open")
        .arg(url)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
    #[cfg(target_os = "windows")]
    let r = process::Command::new("cmd")
        .args(["/c", "start", "", url])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
    let _ = r;
}

#[derive(Parser)]
#[command(name = "vesta", version, about = "manage your vesta agents")]
struct Cli {
    /// Server host (overrides config)
    #[arg(long, global = true)]
    host: Option<String>,
    /// API token (overrides config)
    #[arg(long, global = true)]
    token: Option<String>,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Create agent, start it, and authenticate Claude
    Setup {
        /// Build the image locally instead of pulling
        #[arg(long)]
        build: bool,
        /// Skip confirmation prompts
        #[arg(long, short)]
        yes: bool,
        /// Agent name (prompted interactively if omitted)
        #[arg(long)]
        name: Option<String>,
    },
    /// Create an agent container (without starting or authenticating)
    Create {
        /// Build the image locally instead of pulling
        #[arg(long)]
        build: bool,
        /// Agent name (prompted interactively if omitted)
        #[arg(long)]
        name: Option<String>,
    },
    /// Start an agent (or all agents if no name given)
    Start {
        /// Agent name (starts all if omitted)
        name: Option<String>,
    },
    /// Stop an agent
    Stop {
        /// Agent name
        name: String,
    },
    /// Restart an agent
    Restart {
        /// Agent name
        name: String,
    },
    /// Authenticate Claude for an agent
    Auth {
        /// Agent name
        name: String,
        /// Provide a token directly (skip interactive flow)
        #[arg(long)]
        token: Option<String>,
    },
    /// Interactive chat with an agent
    Chat {
        /// Agent name
        name: String,
    },
    /// Tail agent logs
    Logs {
        /// Agent name
        name: String,
    },
    /// Show agent status
    Status {
        /// Agent name
        name: String,
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Export an agent to a backup file
    Backup {
        /// Agent name
        name: String,
        /// Output file path (.tar.gz)
        output: PathBuf,
    },
    /// Import an agent from a backup file
    Restore {
        /// Input backup file path (.tar.gz)
        input: PathBuf,
        /// Override agent name from backup
        #[arg(long)]
        name: Option<String>,
        /// Replace existing agent with same name
        #[arg(long)]
        replace: bool,
    },
    /// Destroy an agent (irreversible)
    Destroy {
        /// Agent name
        name: String,
    },
    /// Snapshot, destroy, recreate, restore auth
    Rebuild {
        /// Agent name
        name: String,
    },
    /// Wait for agent to become ready
    WaitReady {
        /// Agent name
        name: String,
        /// Timeout in seconds
        #[arg(long, default_value = "30")]
        timeout: u64,
    },
    /// List all agents
    List {
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Connect to a remote server
    Connect {
        /// Server host:port
        host: String,
    },
    /// Start the server (platform-specific)
    Boot,
    /// Stop the server (platform-specific)
    Shutdown,
    /// Update vesta to the latest version
    Update,
}

fn prompt_name() -> String {
    eprint!("agent name: ");
    io::stderr().flush().ok();
    let mut input = String::new();
    io::stdin().read_line(&mut input).ok();
    let name = input.trim().to_string();
    if name.is_empty() {
        platform::die("agent name is required");
    }
    name
}

fn get_client(host: Option<&str>, token: Option<&str>) -> client::Client {
    let config = platform::load_server_config(host, token)
        .unwrap_or_else(|| platform::die("no server configured. run: vesta setup"));
    client::Client::new(config.url, config.api_key, config.cert_fingerprint)
}

fn version_less_than(a: &str, b: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> {
        v.split('.')
            .filter_map(|s| s.parse().ok())
            .collect()
    };
    parse(a) < parse(b)
}

fn fetch_latest_version(timeout: Option<u64>) -> Option<String> {
    let mut args = vec!["-fsSL"];
    let timeout_connect;
    let timeout_max;
    if let Some(t) = timeout {
        timeout_connect = format!("{}", t);
        timeout_max = format!("{}", t);
        args.extend([
            "--connect-timeout",
            &timeout_connect,
            "--max-time",
            &timeout_max,
        ]);
    }
    args.push("https://api.github.com/repos/elyxlz/vesta/releases/latest");

    let output = process::Command::new("curl")
        .args(&args)
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }

    let body = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value = serde_json::from_str(&body).ok()?;
    let latest = data["tag_name"].as_str()?.trim_start_matches('v');
    if latest.is_empty() {
        return None;
    }
    Some(latest.to_string())
}

fn check_latest_version() -> Option<String> {
    let current = env!("CARGO_PKG_VERSION");
    eprintln!("current version: v{}", current);

    let latest =
        fetch_latest_version(None).unwrap_or_else(|| platform::die("failed to check for updates"));

    if latest == current {
        eprintln!("already up to date");
        return None;
    }
    eprintln!("updating to v{}...", latest);
    Some(latest)
}

fn cli_self_update(rust_target: &str, is_zip: bool, binary_subpath: &str) -> Option<PathBuf> {
    let latest = check_latest_version()?;

    let ext = if is_zip { "zip" } else { "tar.gz" };
    let archive_name = format!("vesta-{}.{}", rust_target, ext);
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/download/v{}/{}",
        latest, archive_name
    );

    let current_exe =
        std::env::current_exe().unwrap_or_else(|e| platform::die(&format!("cannot determine binary path: {}", e)));
    let exe_dir = current_exe
        .parent()
        .unwrap_or_else(|| platform::die("cannot determine binary directory"));

    let tmp_dir = {
        let primary = exe_dir.join(".vesta-update-tmp");
        let _ = std::fs::remove_dir_all(&primary);
        if std::fs::create_dir_all(&primary).is_ok() {
            primary
        } else {
            let fallback = std::env::temp_dir().join("vesta-update");
            let _ = std::fs::remove_dir_all(&fallback);
            std::fs::create_dir_all(&fallback)
                .unwrap_or_else(|e| platform::die(&format!("failed to create temp dir: {}", e)));
            fallback
        }
    };

    let archive = tmp_dir.join(&archive_name);
    let dl = process::Command::new("curl")
        .args(["-fsSL", "-o"])
        .arg(&archive)
        .arg(&url)
        .status()
        .unwrap_or_else(|_| platform::die("curl not found"));
    if !dl.success() {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        platform::die("failed to download update");
    }

    let tar_flag = if is_zip { "-xf" } else { "-xzf" };
    let extract = process::Command::new("tar")
        .arg(tar_flag)
        .arg(&archive)
        .arg("-C")
        .arg(&tmp_dir)
        .status()
        .unwrap_or_else(|_| platform::die("tar not found"));
    if !extract.success() {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        platform::die("failed to extract update");
    }

    let new_binary = tmp_dir.join(binary_subpath);
    self_replace::self_replace(&new_binary).unwrap_or_else(|e| {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        platform::die(&format!("failed to replace binary: {}", e));
    });

    eprintln!("updated to v{}", latest);
    Some(tmp_dir)
}

fn check_update_cached() -> Option<std::thread::JoinHandle<Option<String>>> {
    let cache_dir = dirs::cache_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
    let cache_file = cache_dir.join("vesta-version-check");

    if let Ok(contents) = std::fs::read_to_string(&cache_file) {
        if let Ok(meta) = std::fs::metadata(&cache_file) {
            if let Ok(modified) = meta.modified() {
                if modified.elapsed().unwrap_or_default() < std::time::Duration::from_secs(3600) {
                    let latest = contents.trim();
                    if !latest.is_empty() && latest != env!("CARGO_PKG_VERSION") {
                        if version_less_than(latest, env!("CARGO_PKG_VERSION")) {
                            let _ = std::fs::remove_file(&cache_file);
                        } else {
                            eprintln!(
                                "\nUpdate available: v{} → v{} (run 'vesta update')",
                                env!("CARGO_PKG_VERSION"),
                                latest
                            );
                        }
                    }
                    return None;
                }
            }
        }
    }

    Some(std::thread::spawn(move || {
        let latest = fetch_latest_version(Some(5))?;
        let _ = std::fs::create_dir_all(&cache_dir);
        let _ = std::fs::write(&cache_file, &latest);
        if latest != env!("CARGO_PKG_VERSION") {
            Some(latest)
        } else {
            None
        }
    }))
}

fn print_welcome() {
    println!("vesta — your personal AI assistant");
    println!();
    println!("Quick start:");
    println!("  vesta setup        Create an agent, authenticate, and start");
    println!("  vesta list         List all agents");
    println!();
    println!("Run 'vesta --help' for all commands.");
}

fn run(cli: Cli) {
    let Some(command) = cli.command else {
        print_welcome();
        return;
    };

    let is_update = matches!(command, Command::Update);
    let bg_handle = if is_update {
        None
    } else {
        check_update_cached()
    };

    let host_ref = cli.host.as_deref();
    let token_ref = cli.token.as_deref();

    match command {
        Command::Setup { build, yes, name } => {
            // Platform-specific: boot server
            #[cfg(target_os = "linux")]
            {
                // Check if vestad is running, if not set it up
                let config = platform::load_server_config(host_ref, token_ref);
                if config.is_none() {
                    eprintln!("setting up vestad...");
                    let vestad_path = platform::linux::download_vestad();
                    platform::linux::install_autostart(&vestad_path);
                    platform::linux::boot();

                    // Wait for server
                    eprint!("waiting for server...");
                    io::stderr().flush().ok();
                    for _ in 0..30 {
                        let c = client::Client::new(
                            "https://localhost:7860".to_string(),
                            String::new(),
                            None,
                        );
                        if c.health().is_ok() {
                            eprintln!(" ready");
                            break;
                        }
                        std::thread::sleep(std::time::Duration::from_secs(1));
                        eprint!(".");
                        io::stderr().flush().ok();
                    }

                    // Extract credentials
                    if let Some(creds) = platform::linux::extract_credentials() {
                        platform::save_server_config(&creds);
                    }
                }
            }

            #[cfg(target_os = "macos")]
            {
                platform::macos::setup(name.as_deref(), build, yes);
                let config = platform::load_server_config(host_ref, token_ref);
                if config.is_none() {
                    if let Some(creds) = platform::macos::extract_credentials() {
                        platform::save_server_config(&creds);
                    }
                }
            }

            #[cfg(target_os = "windows")]
            {
                platform::windows::boot();
                let config = platform::load_server_config(host_ref, token_ref);
                if config.is_none() {
                    if let Some(creds) = platform::windows::extract_credentials() {
                        platform::save_server_config(&creds);
                    }
                }
            }

            let c = get_client(host_ref, token_ref);

            let name = name
                .map(|n| n.trim().to_string())
                .unwrap_or_else(prompt_name);

            // Create agent
            match c.create_agent(&name, build) {
                Ok(name) => eprintln!("created agent '{}'", name),
                Err(e) if e.contains("already exists") && yes => {
                    eprintln!("agent '{}' already exists, continuing...", name);
                }
                Err(e) if e.contains("already exists") => {
                    platform::die(&format!("agent '{}' already exists. use --yes to continue", name));
                }
                Err(e) => platform::die(&e),
            }

            // Auth
            eprintln!("authenticating claude...");
            let auth = c.start_auth(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("open this URL to authenticate:");
            eprintln!("  {}", auth.auth_url);
            try_open_browser(&auth.auth_url);

            eprint!("paste the auth code: ");
            io::stderr().flush().ok();
            let mut code = String::new();
            io::stdin()
                .read_line(&mut code)
                .unwrap_or_else(|_| platform::die("failed to read auth code"));
            let code = code.trim();
            if code.is_empty() {
                platform::die("no auth code provided");
            }
            c.complete_auth(&name, &auth.session_id, code)
                .unwrap_or_else(|e| platform::die(&e));
            eprintln!("authenticated!");

            // Start
            c.start_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("agent '{}' is running.", name);

            // Install autostart
            #[cfg(target_os = "linux")]
            {
                // Already installed above
            }
            #[cfg(target_os = "macos")]
            platform::macos::install_autostart();
            #[cfg(target_os = "windows")]
            platform::windows::install_autostart();
        }

        Command::Create { build, name } => {
            let c = get_client(host_ref, token_ref);
            let name = name
                .map(|n| n.trim().to_string())
                .unwrap_or_else(prompt_name);
            let name = c.create_agent(&name, build).unwrap_or_else(|e| platform::die(&e));
            eprintln!(
                "created (run 'vesta auth {}' to authenticate, then 'vesta start {}')",
                name, name
            );
        }

        Command::Start { name } => {
            let c = get_client(host_ref, token_ref);
            match name {
                Some(name) => {
                    c.start_agent(&name).unwrap_or_else(|e| platform::die(&e));
                    eprintln!("{}: started", name);
                }
                None => {
                    let results = c.start_all().unwrap_or_else(|e| platform::die(&e));
                    if results.is_empty() {
                        eprintln!("no agents found. create one with: vesta setup");
                    } else {
                        for r in &results {
                            if r.ok {
                                eprintln!("{}: started", r.name);
                            } else {
                                eprintln!(
                                    "{}: {}",
                                    r.name,
                                    r.error.as_deref().unwrap_or("failed")
                                );
                            }
                        }
                    }
                }
            }
        }

        Command::Stop { name } => {
            let c = get_client(host_ref, token_ref);
            c.stop_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{}: stopped", name);
        }

        Command::Restart { name } => {
            let c = get_client(host_ref, token_ref);
            c.restart_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{}: restarted", name);
        }

        Command::Auth { name, token } => {
            let c = get_client(host_ref, token_ref);
            if let Some(token_str) = token {
                c.inject_token(&name, &token_str)
                    .unwrap_or_else(|e| platform::die(&e));
                eprintln!("{}: authenticated", name);
            } else {
                let auth = c.start_auth(&name).unwrap_or_else(|e| platform::die(&e));
                eprintln!("open this URL to authenticate:");
                eprintln!("  {}", auth.auth_url);
                try_open_browser(&auth.auth_url);

                eprint!("paste the auth code: ");
                io::stderr().flush().ok();
                let mut code = String::new();
                io::stdin()
                    .read_line(&mut code)
                    .unwrap_or_else(|_| platform::die("failed to read auth code"));
                let code = code.trim();
                if code.is_empty() {
                    platform::die("no auth code provided");
                }
                c.complete_auth(&name, &auth.session_id, code)
                    .unwrap_or_else(|e| platform::die(&e));
                eprintln!("{}: authenticated", name);
            }
        }

        Command::Chat { name } => {
            let c = get_client(host_ref, token_ref);
            c.chat(&name).unwrap_or_else(|e| platform::die(&e));
        }

        Command::Logs { name } => {
            let c = get_client(host_ref, token_ref);
            c.stream_logs(&name).unwrap_or_else(|e| platform::die(&e));
        }

        Command::Status { name, json } => {
            let c = get_client(host_ref, token_ref);
            let status = c.agent_status(&name).unwrap_or_else(|e| {
                if json {
                    println!(
                        "{}",
                        serde_json::json!({
                            "name": name,
                            "status": "not_found",
                            "authenticated": false,
                            "ws_port": 7865,
                            "alive": false,
                            "friendly_status": "not found"
                        })
                    );
                    process::exit(0);
                }
                platform::die(&e);
            });
            if json {
                println!("{}", serde_json::to_string(&status).unwrap());
            } else {
                println!("name:   {}", status.name);
                println!("status: {}", status.status);
                if let Some(id) = &status.id {
                    println!("id:     {}", id);
                }
                println!(
                    "auth:   {}",
                    if status.authenticated { "yes" } else { "no" }
                );
                println!("port:   {}", status.ws_port);
                if status.status == "running" {
                    println!(
                        "ready:  {}",
                        if status.agent_ready { "yes" } else { "no" }
                    );
                }
            }
        }

        Command::List { json } => {
            let c = get_client(host_ref, token_ref);
            let agents = c.list_agents().unwrap_or_else(|e| platform::die(&e));
            if json {
                println!("{}", serde_json::to_string(&agents).unwrap());
            } else if agents.is_empty() {
                println!("no agents. run: vesta setup");
            } else {
                for e in &agents {
                    let ready_str = if e.status == "running" {
                        if e.agent_ready {
                            " (ready)"
                        } else {
                            " (not ready)"
                        }
                    } else {
                        ""
                    };
                    let auth_str = if e.authenticated { "" } else { " [no auth]" };
                    println!(
                        "  {} — {}{}{}  (port {})",
                        e.name, e.status, ready_str, auth_str, e.ws_port
                    );
                }
            }
        }

        Command::Backup { name, output } => {
            let c = get_client(host_ref, token_ref);
            c.backup(&name, &output).unwrap_or_else(|e| platform::die(&e));
            eprintln!("backup saved to {}", output.display());
        }

        Command::Restore {
            input,
            name,
            replace,
        } => {
            let c = get_client(host_ref, token_ref);
            let name = c
                .restore(&input, name.as_deref(), replace)
                .unwrap_or_else(|e| platform::die(&e));
            eprintln!("agent '{}' restored. run 'vesta start {}' to start it.", name, name);
        }

        Command::Destroy { name } => {
            let c = get_client(host_ref, token_ref);
            c.destroy_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{}: destroyed", name);
        }

        Command::Rebuild { name } => {
            let c = get_client(host_ref, token_ref);
            c.rebuild_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{}: rebuilt and running", name);
        }

        Command::WaitReady { name, timeout } => {
            let c = get_client(host_ref, token_ref);
            c.wait_ready(&name, timeout).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{}: ready", name);
        }

        Command::Connect { host } => {
            let url = if host.starts_with("https://") || host.starts_with("http://") {
                host.clone()
            } else {
                format!("https://{}", host)
            };

            eprint!("API key: ");
            io::stderr().flush().ok();
            let mut key = String::new();
            io::stdin()
                .read_line(&mut key)
                .unwrap_or_else(|_| platform::die("failed to read API key"));
            let key = key.trim().to_string();
            if key.is_empty() {
                platform::die("API key is required");
            }

            let config = platform::ServerConfig {
                url: url.clone(),
                api_key: key,
                cert_fingerprint: None,
            };

            // Verify connection
            let c = client::Client::new(config.url.clone(), config.api_key.clone(), config.cert_fingerprint.clone());
            c.health()
                .unwrap_or_else(|e| platform::die(&format!("cannot reach server: {}", e)));

            platform::save_server_config(&config);
            eprintln!("connected to {}", url);
        }

        Command::Boot => {
            #[cfg(target_os = "linux")]
            platform::linux::boot();
            #[cfg(target_os = "macos")]
            platform::macos::boot();
            #[cfg(target_os = "windows")]
            platform::windows::boot();
            eprintln!("server started");
        }

        Command::Shutdown => {
            #[cfg(target_os = "linux")]
            platform::linux::shutdown();
            #[cfg(target_os = "macos")]
            platform::macos::shutdown();
            #[cfg(target_os = "windows")]
            platform::windows::shutdown();
            eprintln!("server stopped");
        }

        Command::Update => {
            #[cfg(target_os = "linux")]
            {
                let target = match std::env::consts::ARCH {
                    "x86_64" => "x86_64-unknown-linux-gnu",
                    "aarch64" => "aarch64-unknown-linux-gnu",
                    other => platform::die(&format!("unsupported architecture: {}", other)),
                };
                if let Some(tmp_dir) = cli_self_update(target, false, "vesta") {
                    let _ = std::fs::remove_dir_all(&tmp_dir);
                }
            }
            #[cfg(target_os = "macos")]
            {
                let target = match std::env::consts::ARCH {
                    "x86_64" => "x86_64-apple-darwin",
                    "aarch64" => "aarch64-apple-darwin",
                    other => platform::die(&format!("unsupported architecture: {}", other)),
                };
                if let Some(tmp_dir) = cli_self_update(target, false, "vesta") {
                    let _ = std::fs::remove_dir_all(&tmp_dir);
                }
            }
            #[cfg(target_os = "windows")]
            {
                if let Some(tmp_dir) =
                    cli_self_update("x86_64-pc-windows-msvc", true, "vesta-windows/vesta.exe")
                {
                    let _ = std::fs::remove_dir_all(&tmp_dir);
                }
            }
        }
    }

    // Check update notification
    if let Some(handle) = bg_handle {
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(100);
        while !handle.is_finished() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if handle.is_finished() {
            if let Ok(Some(latest)) = handle.join() {
                eprintln!(
                    "\nUpdate available: v{} → v{} (run 'vesta update')",
                    env!("CARGO_PKG_VERSION"),
                    latest
                );
            }
        }
    }
}

fn main() {
    let cli = Cli::parse();
    run(cli);
}
