use clap::{Parser, Subcommand};
use std::io::{self, Write};
use std::path::PathBuf;
use std::process;
mod client;
mod common;
mod platform;

use common::{fetch_latest_release_tag, version_less_than};

const VERSION_CACHE_TTL_SECS: u64 = 3600;
const UPDATE_CHECK_TIMEOUT_MS: u64 = 100;
const UPDATE_CHECK_POLL_MS: u64 = 10;

fn format_size(bytes: u64) -> String {
    if bytes >= 1_000_000_000 {
        format!("{:.1}GB", bytes as f64 / 1_000_000_000.0)
    } else if bytes >= 1_000_000 {
        format!("{:.1}MB", bytes as f64 / 1_000_000.0)
    } else if bytes >= 1_000 {
        format!("{:.0}kB", bytes as f64 / 1_000.0)
    } else {
        format!("{}B", bytes)
    }
}

fn try_open_browser(url: &str) {
    #[cfg(target_os = "linux")]
    let _child = process::Command::new("xdg-open")
        .arg(url)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
    #[cfg(target_os = "macos")]
    let _child = process::Command::new("open")
        .arg(url)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
    #[cfg(target_os = "windows")]
    let _child = process::Command::new("cmd")
        .args(["/c", "start", "", url])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
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
        /// Number of lines to show initially
        #[arg(long, default_value = "500")]
        tail: u64,
    },
    /// Show agent status
    Status {
        /// Agent name
        name: String,
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Manage agent backups
    Backup {
        #[command(subcommand)]
        action: BackupAction,
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
    /// Connect to a remote server (e.g. vesta connect https://host#apikey)
    Connect {
        /// Server URL, optionally with API key after #
        host: String,
    },
    /// Update vesta to the latest version
    Update,
    /// Uninstall vesta CLI and remove config
    Uninstall,
}

#[derive(Subcommand)]
enum BackupAction {
    /// Create a new backup
    Create {
        /// Agent name
        name: String,
    },
    /// List existing backups
    List {
        /// Agent name
        name: String,
    },
    /// Restore an agent from a backup
    Restore {
        /// Agent name
        name: String,
        /// Backup ID (from `vesta backup list`)
        backup_id: String,
    },
    /// Delete a backup
    Delete {
        /// Agent name
        name: String,
        /// Backup ID (from `vesta backup list`)
        backup_id: String,
    },
    /// Show or set auto-backup status
    AutoBackup {
        /// Set to "on" or "off" (omit to show current status)
        toggle: Option<Toggle>,
    },
    /// Show or set backup retention policy
    Retention {
        /// Daily backups to keep
        #[arg(long)]
        daily: Option<usize>,
        /// Weekly backups to keep
        #[arg(long)]
        weekly: Option<usize>,
        /// Monthly backups to keep
        #[arg(long)]
        monthly: Option<usize>,
    },
}

#[derive(Clone, clap::ValueEnum)]
enum Toggle {
    On,
    Off,
}

fn print_retention(ret: &serde_json::Value) {
    eprintln!("retention: daily={}, weekly={}, monthly={}",
        ret["daily"].as_u64().unwrap_or(0),
        ret["weekly"].as_u64().unwrap_or(0),
        ret["monthly"].as_u64().unwrap_or(0),
    );
}

fn prompt(label: &str) -> String {
    eprint!("{}: ", label);
    io::stderr().flush().ok();
    let mut input = String::new();
    io::stdin()
        .read_line(&mut input)
        .unwrap_or_else(|_| platform::die(&format!("failed to read {label}")));
    let value = input.trim().to_string();
    if value.is_empty() {
        platform::die(&format!("{label} is required"));
    }
    value
}

fn prompt_name() -> String {
    prompt("agent name")
}

fn authenticate_agent(client: &client::Client, name: &str) {
    let auth = client.start_auth(name).unwrap_or_else(|e| platform::die(&e));
    eprintln!("open this URL to authenticate:");
    eprintln!("  {}", auth.auth_url);
    try_open_browser(&auth.auth_url);

    let code = prompt("paste the auth code");
    client
        .complete_auth(name, &auth.session_id, &code)
        .unwrap_or_else(|e| platform::die(&e));
    eprintln!("authenticated!");
}

fn get_client(host: Option<&str>, token: Option<&str>) -> client::Client {
    let config = platform::load_server_config(host, token)
        .unwrap_or_else(|| platform::die("no server configured. run: vesta connect <host>"));
    client::Client::new(&config)
}

fn check_latest_version() -> Option<String> {
    let current = env!("CARGO_PKG_VERSION");
    eprintln!("current version: v{}", current);

    let latest = fetch_latest_release_tag(None)
        .unwrap_or_else(|| platform::die("failed to check for updates"));

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
    let cache_dir = dirs::cache_dir().unwrap_or_else(std::env::temp_dir);
    let cache_file = cache_dir.join("vesta-version-check");

    if let Ok(contents) = std::fs::read_to_string(&cache_file) {
        if let Ok(meta) = std::fs::metadata(&cache_file) {
            if let Ok(modified) = meta.modified() {
                if modified.elapsed().unwrap_or_default() < std::time::Duration::from_secs(VERSION_CACHE_TTL_SECS) {
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
        let latest = fetch_latest_release_tag(Some(5))?;
        let _ = std::fs::create_dir_all(&cache_dir);
        let _ = std::fs::write(&cache_file, &latest);
        if version_less_than(env!("CARGO_PKG_VERSION"), &latest) {
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
            let c = get_client(host_ref, token_ref);

            let name = name
                .map(|name| name.trim().to_string())
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

            eprintln!("authenticating claude...");
            authenticate_agent(&c, &name);

            // Start
            c.start_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("agent '{}' is running.", name);

        }

        Command::Create { build, name } => {
            let c = get_client(host_ref, token_ref);
            let name = name
                .map(|name| name.trim().to_string())
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
                authenticate_agent(&c, &name);
            }
        }

        Command::Chat { name } => {
            let c = get_client(host_ref, token_ref);
            client::chat(&c, &name).unwrap_or_else(|e| platform::die(&e));
        }

        Command::Logs { name, tail } => {
            let c = get_client(host_ref, token_ref);
            c.stream_logs(&name, tail).unwrap_or_else(|e| platform::die(&e));
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
                            "ws_port": 0,
                            "alive": false,
                            "friendly_status": "not found"
                        })
                    );
                    process::exit(0);
                }
                platform::die(&e);
            });
            if json {
                println!("{}", serde_json::to_string(&status).unwrap_or_else(|e| platform::die(&format!("failed to serialize: {e}"))));
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
                println!("{}", serde_json::to_string(&agents).unwrap_or_else(|e| platform::die(&format!("failed to serialize: {e}"))));
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

        Command::Backup { action } => {
            let c = get_client(host_ref, token_ref);
            match action {
                BackupAction::Create { name } => {
                    let backup = c.create_backup(&name).unwrap_or_else(|e| platform::die(&e));
                    eprintln!("backup created: {} ({})", backup.id, format_size(backup.size));
                }
                BackupAction::List { name } => {
                    let backups = c.list_backups(&name).unwrap_or_else(|e| platform::die(&e));
                    if backups.is_empty() {
                        eprintln!("no backups for '{}'", name);
                    } else {
                        eprintln!("  {:<22} {:<13} {:>8}   ID", "DATE", "TYPE", "SIZE");
                        for b in &backups {
                            println!(
                                "  {:<22} {:<13} {:>8}   {}",
                                b.created_at, b.backup_type, format_size(b.size), b.id
                            );
                        }
                    }
                }
                BackupAction::Restore { name, backup_id } => {
                    c.restore_backup(&name, &backup_id)
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("{}: restored from {}", name, backup_id);
                }
                BackupAction::Delete { name, backup_id } => {
                    c.delete_backup(&name, &backup_id)
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("backup deleted: {}", backup_id);
                }
                BackupAction::AutoBackup { toggle } => match toggle {
                    Some(Toggle::On) => {
                        c.set_auto_backup_settings(&serde_json::json!({"enabled": true}))
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("auto-backup: enabled");
                    }
                    Some(Toggle::Off) => {
                        c.set_auto_backup_settings(&serde_json::json!({"enabled": false}))
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("auto-backup: disabled");
                    }
                    None => {
                        let settings = c.get_auto_backup_settings().unwrap_or_else(|e| platform::die(&e));
                        let enabled = settings["enabled"].as_bool().unwrap_or(true);
                        eprintln!("auto-backup: {}", if enabled { "enabled" } else { "disabled" });
                    }
                },
                BackupAction::Retention { daily, weekly, monthly } => {
                    if daily.is_none() && weekly.is_none() && monthly.is_none() {
                        let settings = c.get_auto_backup_settings().unwrap_or_else(|e| platform::die(&e));
                        print_retention(&settings["retention"]);
                    } else {
                        let mut ret = serde_json::Map::new();
                        if let Some(d) = daily { ret.insert("daily".into(), d.into()); }
                        if let Some(w) = weekly { ret.insert("weekly".into(), w.into()); }
                        if let Some(m) = monthly { ret.insert("monthly".into(), m.into()); }
                        let settings = c.set_auto_backup_settings(&serde_json::json!({"retention": ret}))
                            .unwrap_or_else(|e| platform::die(&e));
                        print_retention(&settings["retention"]);
                    }
                },
            }
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
            let (url, key) = if let Some((url, key)) = host.split_once('#') {
                (url.to_string(), key.to_string())
            } else {
                let key = prompt("API key");
                (host, key)
            };

            let url = common::normalize_url(&url);
            if key.is_empty() {
                platform::die("API key is required");
            }

            let config = platform::ServerConfig {
                url: url.clone(),
                api_key: key,
                cert_fingerprint: None,
                cert_pem: None,
            };

            let client = client::Client::new(&config);
            client
                .health()
                .unwrap_or_else(|e| platform::die(&format!("cannot reach server: {e}")));

            platform::save_server_config(&config)
                .unwrap_or_else(|e| platform::die(&e));
            eprintln!("connected to {url}");
        }

        Command::Uninstall => {
            eprint!("This will remove the vesta CLI binary and its config. Continue? [y/N] ");
            io::stdout().flush().ok();
            let mut answer = String::new();
            io::stdin().read_line(&mut answer).ok();
            if !answer.trim().eq_ignore_ascii_case("y") {
                eprintln!("Aborted.");
                process::exit(0);
            }

            // Remove config directory
            let config = common::config_dir();
            if config.exists() {
                if let Err(err) = std::fs::remove_dir_all(&config) {
                    eprintln!("warning: failed to remove config dir {}: {}", config.display(), err);
                } else {
                    eprintln!("  removed {}", config.display());
                }
            }

            // Remove the binary itself (best-effort self-delete)
            if let Ok(exe) = std::env::current_exe() {
                if let Err(err) = std::fs::remove_file(&exe) {
                    eprintln!("warning: could not remove binary {}: {}", exe.display(), err);
                    eprintln!("  remove it manually: rm {}", exe.display());
                } else {
                    eprintln!("  removed {}", exe.display());
                }
            }

            eprintln!("\nvesta has been uninstalled.");
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
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(UPDATE_CHECK_TIMEOUT_MS);
        while !handle.is_finished() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(UPDATE_CHECK_POLL_MS));
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
