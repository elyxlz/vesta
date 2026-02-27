use clap::{Parser, Subcommand};
use std::process;

fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    process::exit(1);
}

#[derive(Parser)]
#[command(name = "vesta", about = "manage your vesta agent")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Create agent, start it, and authenticate Claude
    Setup {
        /// Build the image locally instead of pulling
        #[arg(long)]
        build: bool,
    },
    /// Create the agent container (without starting or authenticating)
    Create {
        /// Build the image locally instead of pulling
        #[arg(long)]
        build: bool,
    },
    /// Start the agent
    Start,
    /// Stop the agent
    Stop,
    /// Restart the agent
    Restart,
    /// Attach to the agent's main process
    Attach,
    /// Authenticate Claude interactively
    Auth,
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
    /// Snapshot, destroy, recreate, restore auth
    Rebuild,
}

#[cfg(target_os = "linux")]
mod linux;

#[cfg(target_os = "macos")]
mod macos;

#[cfg(target_os = "windows")]
mod windows;

#[cfg(target_os = "linux")]
fn main() {
    let cli = Cli::parse();
    linux::run(cli.command);
}

#[cfg(target_os = "macos")]
#[tokio::main]
async fn main() {
    let cli = Cli::parse();
    macos::run(cli.command).await;
}

#[cfg(target_os = "windows")]
fn main() {
    let cli = Cli::parse();
    windows::run(cli.command);
}
