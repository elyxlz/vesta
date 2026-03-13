use clap::{Parser, Subcommand};
use std::io::{BufRead, Write};
use std::path::PathBuf;
use std::process;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    process::exit(1);
}

fn try_open_browser(url: &str) {
    #[cfg(target_os = "linux")]
    let r = process::Command::new("xdg-open").arg(url)
        .stdout(process::Stdio::null()).stderr(process::Stdio::null()).spawn();
    #[cfg(target_os = "macos")]
    let r = process::Command::new("open").arg(url)
        .stdout(process::Stdio::null()).stderr(process::Stdio::null()).spawn();
    #[cfg(target_os = "windows")]
    let r = process::Command::new("cmd").args(["/c", "start", "", url])
        .stdout(process::Stdio::null()).stderr(process::Stdio::null()).spawn();
    let _ = r;
}

#[allow(dead_code)]
fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            match chars.peek() {
                Some('[') => { chars.next(); for c in chars.by_ref() { if c.is_ascii_alphabetic() { break; } } }
                Some(']') => { chars.next(); while let Some(c) = chars.next() { if c == '\x07' { break; } else if c == '\x1b' && chars.peek() == Some(&'\\') { chars.next(); break; } } }
                _ => { chars.next(); }
            }
        } else {
            out.push(c);
        }
    }
    out
}

/// Run a child process with piped stdout/stderr, passing lines through.
/// Scans output for an auth URL and opens it in the browser.
#[allow(dead_code)]
fn run_passthrough(mut child: process::Child) -> process::ExitStatus {
    let opened = Arc::new(AtomicBool::new(false));

    let spawn_reader = |reader: Box<dyn std::io::Read + Send>,
                        mut writer: Box<dyn std::io::Write + Send>,
                        opened: Arc<AtomicBool>| {
        std::thread::spawn(move || {
            for line in std::io::BufReader::new(reader).lines() {
                let Ok(line) = line else { break };
                let _ = writeln!(writer, "{}", line);
                if !opened.load(Ordering::Relaxed) {
                    let clean = strip_ansi(&line);
                    if let Some(url) = clean.split_whitespace().find(|w| w.starts_with("https://")) {
                        opened.store(true, Ordering::Relaxed);
                        try_open_browser(url);
                    }
                }
            }
        })
    };

    let stdout_thread = spawn_reader(
        Box::new(child.stdout.take().unwrap()),
        Box::new(std::io::stdout()),
        opened.clone(),
    );
    let stderr_thread = spawn_reader(
        Box::new(child.stderr.take().unwrap()),
        Box::new(std::io::stderr()),
        opened,
    );

    let status = child.wait().unwrap_or_else(|_| die("command failed"));
    let _ = stdout_thread.join();
    let _ = stderr_thread.join();
    status
}

#[derive(Parser)]
#[command(name = "vesta", version, about = "manage your vesta agents")]
struct Cli {
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
    /// Attach to an agent's main process
    Attach {
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
    /// Tail agent logs
    Logs {
        /// Agent name
        name: String,
    },
    /// Open a shell inside an agent
    Shell {
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
        /// Skip confirmation prompt
        #[arg(long, short)]
        yes: bool,
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
    /// Check platform readiness (WSL on Windows, VM on macOS)
    PlatformCheck,
    /// Install platform prerequisites (WSL on Windows)
    PlatformSetup,
    /// Update vesta to the latest version
    Update,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strip_ansi_plain() {
        assert_eq!(strip_ansi("hello world"), "hello world");
    }

    #[test]
    fn strip_ansi_csi() {
        assert_eq!(strip_ansi("\x1b[31mred\x1b[0m"), "red");
    }

    #[test]
    fn strip_ansi_cursor_movement() {
        assert_eq!(strip_ansi("\x1b[1CPaste\x1b[1Ccode"), "Pastecode");
    }

    #[test]
    fn strip_ansi_osc() {
        assert_eq!(strip_ansi("\x1b]0;title\x07text"), "text");
    }

    #[test]
    fn strip_ansi_url_preserved() {
        let input = "\x1b[37mhttps://claude.ai/oauth?code=true\x1b[39m";
        assert_eq!(strip_ansi(input), "https://claude.ai/oauth?code=true");
    }

    #[test]
    fn strip_ansi_complex_ink_output() {
        let input = "\x1b[1C\x1b[97m·\x1b[1C\x1b[39mOpening\x1b[1Cbrowser";
        assert_eq!(strip_ansi(input), "·Openingbrowser");
    }

    #[test]
    fn url_extraction_from_ansi() {
        let raw = "\x1b[37mhttps://claude.ai/oauth/authorize?code=true&client_id=abc\x1b[39m";
        let clean = strip_ansi(raw);
        let url = clean.split_whitespace().find(|w| w.starts_with("https://"));
        assert_eq!(url, Some("https://claude.ai/oauth/authorize?code=true&client_id=abc"));
    }
}

/// Check GitHub for the latest CLI version. Returns Some(version) if update available, None if up to date.
#[allow(dead_code)]
fn check_latest_version() -> Option<String> {
    let current = env!("CARGO_PKG_VERSION");
    eprintln!("current version: v{}", current);

    let output = process::Command::new("curl")
        .args(["-fsSL", "https://api.github.com/repos/elyxlz/vesta/releases/latest"])
        .output()
        .unwrap_or_else(|_| die("curl not found — install curl"));
    if !output.status.success() {
        die("failed to check for updates");
    }

    let body = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value = serde_json::from_str(&body)
        .unwrap_or_else(|_| die("failed to parse release info"));
    let latest = data["tag_name"].as_str().unwrap_or("").trim_start_matches('v');
    if latest.is_empty() {
        die("could not determine latest version");
    }

    if latest == current {
        eprintln!("already up to date");
        return None;
    }
    eprintln!("updating to v{}...", latest);
    Some(latest.to_string())
}

/// Download, extract, and self-replace the CLI binary.
/// Returns Some(tmp_dir) on success for caller to do post-processing and cleanup.
/// Returns None if already up to date.
#[allow(dead_code)]
fn cli_self_update(rust_target: &str, is_zip: bool, binary_subpath: &str) -> Option<PathBuf> {
    let latest = check_latest_version()?;

    let ext = if is_zip { "zip" } else { "tar.gz" };
    let archive_name = format!("vesta-{}.{}", rust_target, ext);
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/download/v{}/{}",
        latest, archive_name
    );

    let current_exe = std::env::current_exe()
        .unwrap_or_else(|e| die(&format!("cannot determine binary path: {}", e)));
    let exe_dir = current_exe.parent()
        .unwrap_or_else(|| die("cannot determine binary directory"));

    // Prefer same-filesystem temp for atomic rename; fall back to system temp if not writable
    let tmp_dir = {
        let primary = exe_dir.join(".vesta-update-tmp");
        let _ = std::fs::remove_dir_all(&primary);
        if std::fs::create_dir_all(&primary).is_ok() {
            primary
        } else {
            let fallback = std::env::temp_dir().join("vesta-update");
            let _ = std::fs::remove_dir_all(&fallback);
            std::fs::create_dir_all(&fallback)
                .unwrap_or_else(|e| die(&format!("failed to create temp dir: {}", e)));
            fallback
        }
    };

    let archive = tmp_dir.join(&archive_name);
    let dl = process::Command::new("curl")
        .args(["-fsSL", "-o"])
        .arg(&archive)
        .arg(&url)
        .status()
        .unwrap_or_else(|_| die("curl not found"));
    if !dl.success() {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        die("failed to download update");
    }

    let tar_flag = if is_zip { "-xf" } else { "-xzf" };
    let extract = process::Command::new("tar")
        .arg(tar_flag)
        .arg(&archive)
        .arg("-C")
        .arg(&tmp_dir)
        .status()
        .unwrap_or_else(|_| die("tar not found"));
    if !extract.success() {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        die("failed to extract update");
    }

    let new_binary = tmp_dir.join(binary_subpath);
    self_replace::self_replace(&new_binary)
        .unwrap_or_else(|e| {
            let _ = std::fs::remove_dir_all(&tmp_dir);
            die(&format!("failed to replace binary: {}", e));
        });

    eprintln!("updated to v{}", latest);
    Some(tmp_dir)
}

/// Spawn a background thread that checks for a newer CLI version and prints a warning.
/// Caches the result for 24 hours to avoid hitting the API on every invocation.
#[allow(dead_code)]
fn spawn_update_check() -> std::thread::JoinHandle<Option<String>> {
    std::thread::spawn(|| {
        let cache_dir = dirs::cache_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
        let cache_file = cache_dir.join("vesta-version-check");

        // Check cache: skip if checked within the last 24 hours
        if let Ok(meta) = std::fs::metadata(&cache_file) {
            if let Ok(modified) = meta.modified() {
                if modified.elapsed().unwrap_or_default() < std::time::Duration::from_secs(86400) {
                    let cached = std::fs::read_to_string(&cache_file).unwrap_or_default();
                    let latest = cached.trim();
                    if latest.is_empty() || latest == env!("CARGO_PKG_VERSION") {
                        return None;
                    }
                    return Some(latest.to_string());
                }
            }
        }

        let output = process::Command::new("curl")
            .args(["-fsSL", "--connect-timeout", "3", "--max-time", "5",
                   "https://api.github.com/repos/elyxlz/vesta/releases/latest"])
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

        // Cache the result
        let _ = std::fs::create_dir_all(&cache_dir);
        let _ = std::fs::write(&cache_file, latest);

        if latest != env!("CARGO_PKG_VERSION") {
            Some(latest.to_string())
        } else {
            None
        }
    })
}

#[cfg(target_os = "linux")]
mod linux;

#[cfg(target_os = "macos")]
mod macos;

#[cfg(target_os = "windows")]
mod windows;

fn print_welcome() {
    println!("vesta — your personal AI assistant");
    println!();
    println!("Quick start:");
    println!("  vesta setup        Create an agent, authenticate, and start");
    println!("  vesta list         List all agents");
    println!();
    println!("Run 'vesta --help' for all commands.");
}

fn run_with_update_check(run: impl FnOnce(Command), cmd: Command) {
    let is_update = matches!(cmd, Command::Update);
    let handle = if is_update { None } else { Some(spawn_update_check()) };
    run(cmd);
    if let Some(handle) = handle {
        // Wait briefly for the check to finish (should already be done by now)
        if let Ok(Some(latest)) = handle.join() {
            eprintln!(
                "\nUpdate available: v{} → v{} (run 'vesta update')",
                env!("CARGO_PKG_VERSION"),
                latest
            );
        }
    }
}

#[cfg(target_os = "linux")]
fn main() {
    let cli = Cli::parse();
    match cli.command {
        Some(cmd) => run_with_update_check(linux::run, cmd),
        None => print_welcome(),
    }
}

#[cfg(target_os = "macos")]
fn main() {
    let cli = Cli::parse();
    match cli.command {
        Some(cmd) => run_with_update_check(macos::run, cmd),
        None => print_welcome(),
    }
}

#[cfg(target_os = "windows")]
fn main() {
    let cli = Cli::parse();
    match cli.command {
        Some(cmd) => run_with_update_check(windows::run, cmd),
        None => print_welcome(),
    }
}
