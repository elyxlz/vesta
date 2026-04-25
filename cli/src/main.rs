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
// Pads for first-start setup (git fetch, npm install, vite build, etc.).
const START_READY_TIMEOUT_SECS: u64 = 900;

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
        /// Skip confirmation prompts
        #[arg(long, short)]
        yes: bool,
        /// Agent name (prompted interactively if omitted)
        #[arg(long)]
        name: Option<String>,
        /// Use the Docker image's baked-in code instead of vestad-managed core code
        #[arg(long)]
        no_manage_core_code: bool,
    },
    /// Create an agent container (without starting or authenticating)
    Create {
        /// Agent name (prompted interactively if omitted)
        #[arg(long)]
        name: Option<String>,
        /// Use the Docker image's baked-in code instead of vestad-managed core code
        #[arg(long)]
        no_manage_core_code: bool,
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
    /// Manage the remote vestad gateway daemon
    Gateway {
        #[command(subcommand)]
        action: GatewayAction,
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
    /// View or update agent settings
    Settings {
        /// Agent name
        name: String,
        /// Enable vestad-managed core code (mount from host)
        #[arg(long)]
        manage_core_code: bool,
        /// Disable vestad-managed core code (use image's baked-in code)
        #[arg(long, conflicts_with = "manage_core_code")]
        no_manage_core_code: bool,
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
    /// Print version information
    Version,
}

#[derive(Subcommand)]
enum GatewayAction {
    /// Restart the remote vestad daemon
    Restart,
    /// Stream vestad logs from the remote gateway
    Logs {
        /// Number of lines to show initially
        #[arg(long, default_value = "500")]
        tail: u64,
        /// Follow the log (tail -f)
        #[arg(long, short)]
        follow: bool,
    },
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
    /// List all backups across all agents (including orphaned)
    ListAll,
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
    /// Show or set per-agent backup settings
    Settings {
        /// Agent name
        name: String,
        /// Enable or disable backups for this agent
        #[arg(long)]
        enabled: Option<Toggle>,
        /// Daily backups to keep (per-agent override)
        #[arg(long)]
        daily: Option<usize>,
        /// Weekly backups to keep (per-agent override)
        #[arg(long)]
        weekly: Option<usize>,
        /// Monthly backups to keep (per-agent override)
        #[arg(long)]
        monthly: Option<usize>,
        /// Remove per-agent override, revert to global settings
        #[arg(long)]
        reset: bool,
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

fn print_agent_backup_settings(result: &serde_json::Value) {
    let enabled = result["enabled"].as_bool().unwrap_or(true);
    let has_override = result["has_override"].as_bool().unwrap_or(false);
    eprintln!("  enabled: {} {}", if enabled { "yes" } else { "no" },
        if has_override { "(override)" } else { "(global)" });
    eprintln!("  retention: daily={}, weekly={}, monthly={}",
        result["retention"]["daily"].as_u64().unwrap_or(0),
        result["retention"]["weekly"].as_u64().unwrap_or(0),
        result["retention"]["monthly"].as_u64().unwrap_or(0),
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

fn detect_timezone() -> Option<String> {
    if let Ok(tz) = std::env::var("TZ") {
        if !tz.is_empty() {
            return Some(tz);
        }
    }
    if let Ok(content) = std::fs::read_to_string("/etc/timezone") {
        let tz = content.trim().to_string();
        if !tz.is_empty() {
            return Some(tz);
        }
    }
    if let Ok(link) = std::fs::read_link("/etc/localtime") {
        let path = link.to_string_lossy();
        if let Some(tz) = path.strip_prefix("/usr/share/zoneinfo/") {
            return Some(tz.to_string());
        }
    }
    None
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
        Command::Setup { yes, name, no_manage_core_code } => {
            let c = get_client(host_ref, token_ref);

            let name = name
                .map(|name| name.trim().to_string())
                .unwrap_or_else(prompt_name);

            let timezone = detect_timezone();
            match c.create_agent(&name, !no_manage_core_code, timezone.as_deref()) {
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
            eprintln!("finalizing first-time setup (this can take several minutes the first time)...");
            c.wait_until_alive(&name, std::time::Duration::from_secs(START_READY_TIMEOUT_SECS))
                .unwrap_or_else(|e| platform::die(&e));
            eprintln!("agent '{}' is ready.", name);

        }

        Command::Create { name, no_manage_core_code } => {
            let c = get_client(host_ref, token_ref);
            let name = name
                .map(|name| name.trim().to_string())
                .unwrap_or_else(prompt_name);
            let timezone = detect_timezone();
            let name = c.create_agent(&name, !no_manage_core_code, timezone.as_deref()).unwrap_or_else(|e| platform::die(&e));
            eprintln!("created (run 'vesta auth {}' to authenticate)", name);
        }

        Command::Settings { name, manage_core_code, no_manage_core_code } => {
            let c = get_client(host_ref, token_ref);
            if manage_core_code || no_manage_core_code {
                let body = serde_json::json!({"manage_agent_code": !no_manage_core_code});
                let result = c.patch_agent_settings(&name, &body).unwrap_or_else(|e| platform::die(&e));
                let val = result["manage_agent_code"].as_bool().unwrap_or(true);
                eprintln!("{}: manage_agent_code = {}", name, val);
            } else {
                let result = c.get_agent_settings(&name).unwrap_or_else(|e| platform::die(&e));
                let val = result["manage_agent_code"].as_bool().unwrap_or(true);
                eprintln!("manage_agent_code = {}", val);
            }
        }

        Command::Start { name } => {
            let c = get_client(host_ref, token_ref);
            match name {
                Some(name) => {
                    c.start_agent(&name).unwrap_or_else(|e| platform::die(&e));
                    c.wait_until_alive(&name, std::time::Duration::from_secs(START_READY_TIMEOUT_SECS))
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("{}: ready", name);
                }
                None => {
                    let results = c.start_all().unwrap_or_else(|e| platform::die(&e));
                    if results.is_empty() {
                        eprintln!("no agents found. create one with: vesta setup");
                    } else {
                        for r in &results {
                            if !r.ok {
                                eprintln!(
                                    "{}: {}",
                                    r.name,
                                    r.error.as_deref().unwrap_or("failed")
                                );
                                continue;
                            }
                            match c.wait_until_alive(&r.name, std::time::Duration::from_secs(START_READY_TIMEOUT_SECS)) {
                                Ok(()) => eprintln!("{}: ready", r.name),
                                Err(e) => eprintln!("{}: {}", r.name, e),
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

        Command::Gateway { action } => match action {
            GatewayAction::Restart => {
                let c = get_client(host_ref, token_ref);
                c.restart_gateway().unwrap_or_else(|e| platform::die(&e));
                eprintln!("vestad: restart initiated");
            }
            GatewayAction::Logs { tail, follow } => {
                let c = get_client(host_ref, token_ref);
                c.stream_gateway_logs(tail, follow).unwrap_or_else(|e| platform::die(&e));
            }
        },

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
                            "ws_port": 0
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
                println!("port:   {}", status.ws_port);
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
                    println!(
                        "  {} — {}  (port {})",
                        e.name, e.status, e.ws_port
                    );
                }
            }
        }

        Command::Backup { action } => {
            let c = get_client(host_ref, token_ref);
            match action {
                BackupAction::Create { name } => {
                    eprintln!("creating backup for '{}'...", name);
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
                BackupAction::ListAll => {
                    let backups = c.list_all_backups().unwrap_or_else(|e| platform::die(&e));
                    if backups.is_empty() {
                        eprintln!("no backups found");
                    } else {
                        eprintln!("  {:<16} {:<22} {:<13} {:>8}   ID", "AGENT", "DATE", "TYPE", "SIZE");
                        for b in &backups {
                            println!(
                                "  {:<16} {:<22} {:<13} {:>8}   {}",
                                b.agent_name, b.created_at, b.backup_type, format_size(b.size), b.id
                            );
                        }
                    }
                }
                BackupAction::Restore { name, backup_id } => {
                    eprintln!("restoring '{}' from backup...", name);
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
                BackupAction::Settings { name, enabled, daily, weekly, monthly, reset } => {
                    if reset {
                        let result = c.delete_agent_backup_settings(&name)
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("{}: backup settings reset to global defaults", name);
                        print_agent_backup_settings(&result);
                    } else if enabled.is_none() && daily.is_none() && weekly.is_none() && monthly.is_none() {
                        let result = c.get_agent_backup_settings(&name)
                            .unwrap_or_else(|e| platform::die(&e));
                        print_agent_backup_settings(&result);
                    } else {
                        let mut body = serde_json::Map::new();
                        if let Some(toggle) = enabled {
                            body.insert("enabled".into(), matches!(toggle, Toggle::On).into());
                        }
                        if daily.is_some() || weekly.is_some() || monthly.is_some() {
                            let mut ret = serde_json::Map::new();
                            if let Some(d) = daily { ret.insert("daily".into(), d.into()); }
                            if let Some(w) = weekly { ret.insert("weekly".into(), w.into()); }
                            if let Some(m) = monthly { ret.insert("monthly".into(), m.into()); }
                            body.insert("retention".into(), serde_json::Value::Object(ret));
                        }
                        let result = c.set_agent_backup_settings(&name, &serde_json::Value::Object(body))
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("{}: backup settings updated", name);
                        print_agent_backup_settings(&result);
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
            c.wait_until_alive(&name, std::time::Duration::from_secs(timeout))
                .unwrap_or_else(|e| platform::die(&e));
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
            io::stderr().flush().ok();
            let mut answer = String::new();
            if io::stdin().read_line(&mut answer).is_err() {
                eprintln!("failed to read input");
                process::exit(1);
            }
            if !answer.trim().eq_ignore_ascii_case("y") {
                eprintln!("Aborted.");
                process::exit(0);
            }

            match std::fs::remove_dir_all(common::config_dir()) {
                Ok(()) => eprintln!("  removed {}", common::config_dir().display()),
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
                Err(err) => eprintln!("warning: failed to remove config: {}", err),
            }

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
        Command::Version => {
            println!("v{}", env!("CARGO_PKG_VERSION"));
            return;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_size_cases() {
        for (input, expected) in [
            (0u64, "0B"),
            (1, "1B"),
            (999, "999B"),
            (1_000, "1kB"),
            (1_500, "2kB"),
            (1_000_000, "1.0MB"),
            (1_500_000, "1.5MB"),
            (1_000_000_000, "1.0GB"),
            (2_500_000_000, "2.5GB"),
        ] {
            assert_eq!(format_size(input), expected, "format_size({input})");
        }
    }
}
