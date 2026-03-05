use clap::{Parser, Subcommand};
use std::process;

fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    process::exit(1);
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
