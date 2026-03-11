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

/// Run a child process with piped stdout/stderr, passing lines through.
/// Scans output for an auth URL and opens it in the browser.
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
