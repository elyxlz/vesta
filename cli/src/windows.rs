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

fn rootfs_path() -> PathBuf {
    install_dir().join("vesta-wsl-rootfs.tar.gz")
}

fn download_rootfs() -> PathBuf {
    let path = rootfs_path();
    if path.exists() {
        return path;
    }

    let dir = path.parent().unwrap();
    std::fs::create_dir_all(dir)
        .unwrap_or_else(|e| die(&format!("failed to create directory: {}", e)));

    let repo = "elyxlz/vesta";
    let asset = "vesta-wsl-rootfs.tar.gz";
    let tmp_path = dir.join(format!("{}.tmp", asset));

    println!("downloading WSL rootfs...");

    let status = process::Command::new("curl.exe")
        .args([
            "-fSL",
            "--progress-bar",
            "-o",
            tmp_path.to_str().unwrap(),
            &format!(
                "https://github.com/{}/releases/latest/download/{}",
                repo, asset
            ),
        ])
        .status()
        .unwrap_or_else(|_| die("failed to download rootfs. is curl available?"));

    if !status.success() {
        std::fs::remove_file(&tmp_path).ok();
        die("failed to download rootfs. check your internet connection.");
    }

    std::fs::rename(&tmp_path, &path)
        .unwrap_or_else(|e| die(&format!("failed to save rootfs: {}", e)));

    path
}

fn bootstrap_distro() {
    clean_install_dir();
    let install_dir = install_dir();
    std::fs::create_dir_all(&install_dir)
        .unwrap_or_else(|_| die("failed to create install directory"));

    let rootfs = download_rootfs();

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
    // so the entrypoint never runs. Start it if not already running.
    // We spawn a dedicated wsl.exe process that stays alive as a background child,
    // preventing WSL from terminating the distro when interactive sessions exit.
    let already_running = process::Command::new("wsl.exe")
        .args(["-d", WSL_DISTRO, "--exec", "pgrep", "-f", "entrypoint.sh"])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    if !already_running {
        let _ = process::Command::new("wsl.exe")
            .args(["-d", WSL_DISTRO, "--exec", "/entrypoint.sh"])
            .stdin(process::Stdio::null())
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .spawn();
    }

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
        Command::Setup { build, yes, ref name } => {
            let mut args = vec!["setup"];
            if *yes { args.push("-y"); }
            if *build { args.push("--build"); }
            if let Some(n) = name { args.push("--name"); args.push(n); }
            args
        }
        Command::Create { build, ref name } => {
            let mut args = if *build {
                vec!["create", "--build"]
            } else {
                vec!["create"]
            };
            if let Some(n) = name {
                args.push("--name");
                args.push(n);
            }
            args
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
        Command::Name { ref name } => vec!["name", name],
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

    let wsl_exec = || -> process::ExitStatus {
        process::Command::new("wsl.exe")
            .args(&args)
            .stdin(process::Stdio::inherit())
            .stdout(process::Stdio::inherit())
            .stderr(process::Stdio::inherit())
            .status()
            .unwrap_or_else(|_| die("failed to execute wsl.exe"))
    };

    let status = wsl_exec();

    if !status.success() && !distro_healthy() {
        // Soft recovery: terminate distro and restart services
        println!("distro is unhealthy. attempting recovery...");
        let _ = process::Command::new("wsl.exe")
            .args(["--terminate", WSL_DISTRO])
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
        ensure_services();

        let retry = wsl_exec();
        if retry.success() {
            if is_setup {
                install_autostart();
            }
            process::exit(0);
        }

        // Soft recovery failed — nuke and reimport as last resort
        unregister_distro();
        println!("reinstalling vesta WSL2 environment...");
        bootstrap_distro();
        ensure_services();

        let status = wsl_exec();
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
