use super::*;
use std::io::{self, Write};
use std::path::PathBuf;

const WSL_DISTRO: &str = "vesta-wsl";
const VESTA_LINUX_BIN: &str = "/usr/local/bin/vesta";
const REGISTRY_RUN_KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";

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

fn distro_healthy() -> bool {
    process::Command::new("wsl.exe")
        .args(["-d", WSL_DISTRO, "--exec", "/bin/true"])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn unregister_distro() {
    println!("removing broken vesta-wsl distro...");
    let _ = process::Command::new("wsl.exe")
        .args(["--unregister", WSL_DISTRO])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
}

fn install_dir() -> PathBuf {
    let local_app_data =
        std::env::var("LOCALAPPDATA").unwrap_or_else(|_| die("LOCALAPPDATA not set"));
    PathBuf::from(&local_app_data).join(WSL_DISTRO)
}

fn clean_install_dir() {
    if let Ok(v) = std::env::var("LOCALAPPDATA") {
        std::fs::remove_dir_all(PathBuf::from(&v).join(WSL_DISTRO)).ok();
    }
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
        // Tauri NSIS installs place resources/ as subdirectory of install dir
        exe_dir.join("resources").join("vesta-wsl-rootfs.tar.gz"),
        exe_dir.join("..").join("resources").join("vesta-wsl-rootfs.tar.gz"),
    ];

    for c in &candidates {
        if c.exists() {
            return c.clone();
        }
    }

    die("rootfs tarball not found. expected vesta-wsl-rootfs.tar.gz next to vesta.exe");
}

fn bootstrap_distro() {
    clean_install_dir();
    let install_dir = install_dir();
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
        die("failed to set up WSL2 environment. ensure WSL2 is enabled and virtualization is turned on in BIOS.");
    }

    println!("vesta-wsl distro ready.");
}

fn docker_ready() -> bool {
    process::Command::new("wsl.exe")
        .args(["-d", WSL_DISTRO, "--exec", "test", "-S", "/var/run/docker.sock"])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn ensure_services() {
    if docker_ready() {
        return;
    }

    // On Windows 10, [boot] command in wsl.conf is not supported,
    // so the entrypoint never runs. Start it manually (only if not already running).
    // The sleep 1 prevents the background process from dying when the
    // wsl.exe shell exits before nohup fully detaches.
    let _ = process::Command::new("wsl.exe")
        .args(["-d", WSL_DISTRO, "--", "sh", "-c",
               "pgrep -f entrypoint.sh >/dev/null 2>&1 || nohup /entrypoint.sh >/dev/null 2>&1 & sleep 1"])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();

    print!("waiting for services...");
    io::stdout().flush().ok();
    for _ in 0..30 {
        if docker_ready() {
            println!(" ready");
            return;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        print!(".");
        io::stdout().flush().ok();
    }
    println!();
    die("services did not start within 30s. try restarting and running again.");
}

fn install_autostart() {
    let exe = match std::env::current_exe() {
        Ok(p) => p,
        Err(_) => return,
    };

    let value = format!("\"{}\" start", exe.display());
    let status = process::Command::new("reg")
        .args([
            "add",
            REGISTRY_RUN_KEY,
            "/v", "Vesta",
            "/t", "REG_SZ",
            "/d", &value,
            "/f",
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();

    if !status.map(|s| s.success()).unwrap_or(false) {
        eprintln!("warning: failed to enable autostart on login");
    }
}

fn remove_autostart() {
    let _ = process::Command::new("reg")
        .args([
            "delete",
            REGISTRY_RUN_KEY,
            "/v", "Vesta",
            "/f",
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
}

fn command_args(command: &Command) -> Vec<&str> {
    match command {
        Command::Setup { build, .. } => {
            let mut args = vec!["setup", "-y"];
            if *build {
                args.push("--build");
            }
            args
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
        Command::Auth { ref token } => {
            if let Some(t) = token {
                vec!["auth", "--token", t]
            } else {
                vec!["auth"]
            }
        }
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
        println!("WSL2 is required but not installed. attempting to install...");
        let status = process::Command::new("powershell.exe")
            .args([
                "-Command",
                "Start-Process wsl -ArgumentList '--install','--no-distribution' -Verb RunAs -Wait -WindowStyle Hidden",
            ])
            .status();

        if status.map(|s| s.success()).unwrap_or(false) && wsl_available() {
            println!("WSL2 installed.");
        } else {
            die("WSL2 installation failed or was cancelled. reboot if you just installed it, or install manually:\n    \
                 wsl --install --no-distribution");
        }
    }

    if !distro_registered() {
        println!("first run: setting up vesta WSL2 environment...");
        bootstrap_distro();
    }

    let is_setup = matches!(command, Command::Setup { .. });
    let is_destroy = matches!(command, Command::Destroy { .. });

    if is_destroy {
        remove_autostart();
    }

    ensure_services();

    let mut args = vec!["-d", WSL_DISTRO, "--exec", VESTA_LINUX_BIN];
    args.extend(command_args(&command));

    let status = process::Command::new("wsl.exe")
        .args(&args)
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|_| die("failed to execute wsl.exe"));

    if !status.success() && !distro_healthy() {
        unregister_distro();
        println!("reinstalling vesta WSL2 environment...");
        bootstrap_distro();
        ensure_services();

        let status = process::Command::new("wsl.exe")
            .args(&args)
            .stdin(process::Stdio::inherit())
            .stdout(process::Stdio::inherit())
            .stderr(process::Stdio::inherit())
            .status()
            .unwrap_or_else(|_| die("failed to execute wsl.exe"));

        if is_setup && status.success() {
            install_autostart();
        }

        process::exit(status.code().unwrap_or(1));
    }

    if is_setup && status.success() {
        install_autostart();
    }

    process::exit(status.code().unwrap_or(1));
}
