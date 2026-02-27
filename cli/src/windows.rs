use super::*;
use std::path::PathBuf;

const WSL_DISTRO: &str = "vesta-wsl";
const VESTA_LINUX_BIN: &str = "/usr/local/bin/vesta";

fn wsl_available() -> bool {
    process::Command::new("wsl.exe")
        .arg("--status")
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn distro_registered() -> bool {
    let output = match process::Command::new("wsl.exe")
        .args(["--list", "--quiet"])
        .output()
    {
        Ok(o) => o,
        Err(_) => return false,
    };

    // wsl --list --quiet outputs UTF-16LE with BOM on Windows
    let u16s: Vec<u16> = output
        .stdout
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]]))
        .collect();
    let text = String::from_utf16_lossy(&u16s);
    let text = text.trim_start_matches('\u{FEFF}');
    text.lines().any(|line| line.trim() == WSL_DISTRO)
}

fn find_rootfs() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .unwrap_or_else(|_| die("cannot determine executable path"))
        .parent()
        .unwrap()
        .to_path_buf();

    let candidates = [
        exe_dir.join("vesta-wsl-rootfs.tar.gz"),
        exe_dir.join("rootfs").join("vesta-wsl-rootfs.tar.gz"),
    ];

    for c in &candidates {
        if c.exists() {
            return c.clone();
        }
    }

    die("rootfs tarball not found. expected vesta-wsl-rootfs.tar.gz next to vesta.exe");
}

fn bootstrap_distro() {
    let local_app_data =
        std::env::var("LOCALAPPDATA").unwrap_or_else(|_| die("LOCALAPPDATA not set"));
    let install_dir = PathBuf::from(&local_app_data).join(WSL_DISTRO);
    std::fs::create_dir_all(&install_dir)
        .unwrap_or_else(|_| die("failed to create install directory"));

    let rootfs = find_rootfs();

    println!("importing vesta-wsl distro...");
    let status = process::Command::new("wsl.exe")
        .args([
            "--import",
            WSL_DISTRO,
            install_dir.to_str().unwrap(),
            rootfs.to_str().unwrap(),
            "--version",
            "2",
        ])
        .status()
        .unwrap_or_else(|_| die("failed to run wsl --import"));

    if !status.success() {
        die("wsl --import failed. check that WSL2 is enabled and virtualization is on in BIOS.");
    }

    println!("vesta-wsl distro ready.");
}

fn command_args(command: &Command) -> Vec<&str> {
    match command {
        Command::Setup { build } => {
            if *build {
                vec!["setup", "--build"]
            } else {
                vec!["setup"]
            }
        }
        Command::Create { build } => {
            if *build {
                vec!["create", "--build"]
            } else {
                vec!["create"]
            }
        }
        Command::Start => vec!["start"],
        Command::Stop => vec!["stop"],
        Command::Restart => vec!["restart"],
        Command::Attach => vec!["attach"],
        Command::Auth => vec!["auth"],
        Command::Logs => vec!["logs"],
        Command::Shell => vec!["shell"],
        Command::Status { json } => {
            if *json {
                vec!["status", "--json"]
            } else {
                vec!["status"]
            }
        }
        Command::Backup => vec!["backup"],
        Command::Destroy { yes } => {
            if *yes {
                vec!["destroy", "--yes"]
            } else {
                vec!["destroy"]
            }
        }
        Command::Rebuild => vec!["rebuild"],
    }
}

pub fn run(command: Command) -> ! {
    if !wsl_available() {
        die(
            "WSL2 is not installed.\n\
             run in an Administrator PowerShell:\n    \
             wsl --install --no-distribution\n\
             then reboot and run vesta again.",
        );
    }

    if !distro_registered() {
        println!("first run: setting up vesta WSL2 environment...");
        bootstrap_distro();
    }

    let mut args = vec!["-d", WSL_DISTRO, "--exec", VESTA_LINUX_BIN];
    args.extend(command_args(&command));

    let status = process::Command::new("wsl.exe")
        .args(&args)
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|_| die("failed to execute wsl.exe"));

    process::exit(status.code().unwrap_or(1));
}
