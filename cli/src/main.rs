use clap::{Parser, Subcommand};
use std::io::{BufRead, IsTerminal, Write};
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

/// Run a child process with piped stdout/stderr, passing lines through.
/// When running in a terminal (not piped by Tauri), scans for an auth URL
/// and opens it in the browser.
fn run_passthrough(mut child: process::Child) -> process::ExitStatus {
    let opened = Arc::new(AtomicBool::new(false));
    let is_tty = std::io::stdout().is_terminal();

    let spawn_reader = |reader: Box<dyn std::io::Read + Send>,
                        mut writer: Box<dyn std::io::Write + Send>,
                        opened: Arc<AtomicBool>| {
        std::thread::spawn(move || {
            for line in std::io::BufReader::new(reader).lines() {
                let Ok(line) = line else { break };
                let _ = writeln!(writer, "{}", line);
                if is_tty && !opened.load(Ordering::Relaxed) {
                    if let Some(url) = line.split_whitespace().find(|w| w.starts_with("https://")) {
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
#[command(name = "vesta", version, about = "manage your vesta agent")]
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
        /// Set the agent's display name
        #[arg(long)]
        name: Option<String>,
    },
    /// Create the agent container (without starting or authenticating)
    Create {
        /// Build the image locally instead of pulling
        #[arg(long)]
        build: bool,
        /// Set the agent's display name
        #[arg(long)]
        name: Option<String>,
    },
    /// Start the agent
    Start,
    /// Stop the agent
    Stop,
    /// Restart the agent
    Restart,
    /// Attach to the agent's main process
    Attach,
    /// Authenticate Claude
    Auth {
        /// Provide a token directly (skip interactive flow)
        #[arg(long)]
        token: Option<String>,
    },
    /// Tail agent logs
    Logs,
    /// Open a shell inside the agent
    Shell,
    /// Show agent status
    Status {
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Create a snapshot backup
    Backup,
    /// Destroy the agent (irreversible)
    Destroy {
        /// Skip confirmation prompt
        #[arg(long, short)]
        yes: bool,
    },
    /// Set the agent's display name
    Name {
        /// The name to set
        name: String,
    },
    /// Snapshot, destroy, recreate, restore auth
    Rebuild,
    /// Check platform readiness (WSL on Windows, VM on macOS)
    PlatformCheck,
    /// Install platform prerequisites (WSL on Windows)
    PlatformSetup,
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
    println!("  vesta setup        Create agent, authenticate, and start");
    println!("  vesta start        Start your agent");
    println!("  vesta status       Check agent status");
    println!();
    println!("Run 'vesta --help' for all commands.");
}

#[cfg(target_os = "linux")]
fn main() {
    let cli = Cli::parse();
    match cli.command {
        Some(cmd) => linux::run(cmd),
        None => print_welcome(),
    }
}

#[cfg(target_os = "macos")]
fn main() {
    let cli = Cli::parse();
    match cli.command {
        Some(cmd) => macos::run(cmd),
        None => print_welcome(),
    }
}

#[cfg(target_os = "windows")]
fn main() {
    let cli = Cli::parse();
    match cli.command {
        Some(cmd) => windows::run(cmd),
        None => print_welcome(),
    }
}
