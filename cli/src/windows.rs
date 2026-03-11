use super::*;
use std::io::{self, Write};
use std::path::PathBuf;

fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            match chars.peek() {
                Some('[') => {
                    chars.next();
                    for c in chars.by_ref() {
                        if c.is_ascii_alphabetic() { break; }
                    }
                }
                Some(']') => {
                    chars.next();
                    while let Some(c) = chars.next() {
                        if c == '\x07' {
                            break;
                        } else if c == '\x1b' && chars.peek() == Some(&'\\') {
                            chars.next();
                            break;
                        }
                    }
                }
                Some('(') => { chars.next(); chars.next(); }
                Some(_) => { chars.next(); }
                None => {}
            }
        } else {
            out.push(c);
        }
    }
    out
}

const WSL_DISTRO: &str = "vesta-wsl";
const VESTA_LINUX_BIN: &str = "/usr/local/bin/vesta";
const REGISTRY_RUN_KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";

fn wsl_status_output() -> (bool, String) {
    let output = process::Command::new("wsl.exe")
        .arg("--status")
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::piped())
        .output();

    match output {
        Ok(o) => {
            let stdout = String::from_utf8_lossy(&o.stdout).to_string();
            let stderr = String::from_utf8_lossy(&o.stderr).to_string();
            let combined = format!("{}\n{}", stdout, stderr);
            (o.status.success(), combined)
        }
        Err(_) => (false, String::new()),
    }
}

fn virtualization_enabled() -> Option<bool> {
    let output = process::Command::new("powershell.exe")
        .args([
            "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled",
        ])
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_lowercase();
    match stdout.as_str() {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    }
}

fn wsl_binary_exists() -> bool {
    process::Command::new("where.exe")
        .arg("wsl.exe")
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn platform_check_json() -> serde_json::Value {
    let wsl_exists = wsl_binary_exists();
    let (wsl_ok, wsl_output) = wsl_status_output();
    let wsl_lower = wsl_output.to_lowercase();

    let needs_reboot = wsl_exists && !wsl_ok
        && (wsl_lower.contains("reboot") || wsl_lower.contains("restart"));

    let virt = if wsl_ok {
        Some(true)
    } else if wsl_exists && (wsl_lower.contains("virtual") || wsl_lower.contains("bios")) {
        Some(false)
    } else {
        virtualization_enabled()
    };

    let registered = wsl_ok && distro_registered();
    let healthy = registered && distro_healthy();
    let services = healthy && docker_ready();

    let ready = wsl_ok && healthy && services;

    let message = if !wsl_exists && !wsl_ok {
        "WSL2 is not installed"
    } else if needs_reboot {
        "restart your computer to finish WSL2 setup"
    } else if virt == Some(false) {
        "hardware virtualization is disabled in BIOS/UEFI"
    } else if !wsl_ok {
        "WSL2 is installed but not working"
    } else if !registered {
        "vesta environment needs to be set up"
    } else if !healthy {
        "vesta environment is unhealthy"
    } else if !services {
        "services are starting..."
    } else {
        ""
    };

    serde_json::json!({
        "ready": ready,
        "platform": "windows",
        "wsl_installed": wsl_ok,
        "virtualization_enabled": virt,
        "distro_registered": registered,
        "distro_healthy": healthy,
        "services_ready": services,
        "needs_reboot": needs_reboot,
        "message": message
    })
}

fn try_install_wsl() -> bool {
    eprintln!("installing WSL2...");
    let status = process::Command::new("powershell.exe")
        .args([
            "-Command",
            "Start-Process wsl -ArgumentList '--install','--no-distribution' -Verb RunAs -Wait -WindowStyle Hidden",
        ])
        .status();

    status.map(|s| s.success()).unwrap_or(false)
}

fn platform_setup() {
    let (wsl_ok, _) = wsl_status_output();
    if !wsl_ok {
        if !try_install_wsl() {
            die("WSL2 installation failed or was cancelled");
        }

        let (wsl_ok_after, _) = wsl_status_output();
        if !wsl_ok_after {
            println!("{}", serde_json::json!({
                "ready": false,
                "platform": "windows",
                "wsl_installed": false,
                "virtualization_enabled": null,
                "distro_registered": false,
                "distro_healthy": false,
                "services_ready": false,
                "needs_reboot": true,
                "message": "restart your computer to finish WSL2 setup"
            }));
            eprintln!("WSL2 installed. restart your computer to finish setup.");
            return;
        }
        eprintln!("WSL2 installed.");
    }

    if !distro_registered() {
        eprintln!("setting up vesta environment...");
        bootstrap_distro();
    } else if !distro_healthy() {
        eprintln!("repairing vesta environment...");
        let _ = process::Command::new("wsl.exe")
            .args(["--terminate", WSL_DISTRO])
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();

        if !distro_healthy() {
            unregister_distro();
            bootstrap_distro();
        }
    }

    let healthy = distro_healthy();
    if healthy {
        ensure_services();
    }

    let services = healthy && docker_ready();
    let ready = healthy && services;
    let message = if !healthy {
        "vesta environment is unhealthy"
    } else if !services {
        "services failed to start"
    } else {
        ""
    };

    println!("{}", serde_json::json!({
        "ready": ready,
        "platform": "windows",
        "wsl_installed": true,
        "virtualization_enabled": true,
        "distro_registered": healthy,
        "distro_healthy": healthy,
        "services_ready": services,
        "needs_reboot": false,
        "message": message
    }));

    if ready {
        eprintln!("platform is ready.");
    }
}

fn distro_registered() -> bool {
    let output = match process::Command::new("wsl.exe")
        .args(["--list", "--quiet"])
        .output()
    {
        Ok(o) => o,
        Err(_) => return false,
    };

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
    eprintln!("removing broken vesta-wsl distro...");
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

    eprintln!("downloading WSL rootfs...");

    let output = process::Command::new("curl.exe")
        .args([
            "-fSL",
            "-o",
            tmp_path.to_str().unwrap(),
            &format!(
                "https://github.com/{}/releases/latest/download/{}",
                repo, asset
            ),
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::piped())
        .output()
        .unwrap_or_else(|_| die("failed to download rootfs. is curl available?"));

    if !output.status.success() {
        std::fs::remove_file(&tmp_path).ok();
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stderr = stderr.trim();
        if stderr.is_empty() {
            die("failed to download rootfs. check your internet connection.");
        } else {
            die(&format!("failed to download rootfs: {}", stderr));
        }
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

    eprintln!("importing vesta-wsl distro...");
    let output = process::Command::new("wsl.exe")
        .args([
            "--import",
            WSL_DISTRO,
            install_dir.to_str().unwrap(),
            rootfs.to_str().unwrap(),
            "--version",
            "2",
        ])
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::piped())
        .output()
        .unwrap_or_else(|_| die("failed to run wsl --import"));

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stderr = stderr.trim();
        if stderr.is_empty() {
            die("failed to set up WSL2 environment. ensure WSL2 is enabled and virtualization is turned on in BIOS.");
        } else {
            die(&format!(
                "failed to set up WSL2 environment: {}\nensure WSL2 is enabled and virtualization is turned on in BIOS.",
                stderr
            ));
        }
    }

    eprintln!("vesta-wsl distro ready.");
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

    eprint!("waiting for services...");
    io::stderr().flush().ok();
    for _ in 0..30 {
        if docker_ready() {
            eprintln!(" ready");
            return;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        eprint!(".");
        io::stderr().flush().ok();
    }
    eprintln!();
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

fn wslpath(win_path: &std::path::Path) -> String {
    let output = process::Command::new("wsl.exe")
        .args(["-d", WSL_DISTRO, "--exec", "wslpath", "-a", win_path.to_str().unwrap()])
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .unwrap_or_else(|_| die("failed to convert path with wslpath"));
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

fn command_args(command: &Command) -> Vec<String> {
    match command {
        Command::Setup { build, yes, ref name } => {
            let mut args = vec!["setup".into()];
            if *yes { args.push("-y".into()); }
            if *build { args.push("--build".into()); }
            if let Some(n) = name { args.push("--name".into()); args.push(n.clone()); }
            args
        }
        Command::Create { build, ref name } => {
            let mut args = vec!["create".into()];
            if *build { args.push("--build".into()); }
            if let Some(n) = name { args.push("--name".into()); args.push(n.clone()); }
            args
        }
        Command::Start { ref name } => {
            let mut args = vec!["start".into()];
            if let Some(n) = name { args.push(n.clone()); }
            args
        }
        Command::Stop { ref name } => vec!["stop".into(), name.clone()],
        Command::Restart { ref name } => vec!["restart".into(), name.clone()],
        Command::Attach { ref name } => vec!["attach".into(), name.clone()],
        Command::Auth { ref name, ref token } => {
            let mut args = vec!["auth".into(), name.clone()];
            if let Some(t) = token { args.push("--token".into()); args.push(t.clone()); }
            args
        }
        Command::Logs { ref name } => vec!["logs".into(), name.clone()],
        Command::Shell { ref name } => vec!["shell".into(), name.clone()],
        Command::Status { ref name, json } => {
            let mut args = vec!["status".into(), name.clone()];
            if *json { args.push("--json".into()); }
            args
        }
        Command::List { json } => {
            let mut args = vec!["list".into()];
            if *json { args.push("--json".into()); }
            args
        }
        Command::Backup { ref name, ref output } => {
            vec!["backup".into(), name.clone(), wslpath(output)]
        }
        Command::Restore { ref input, ref name, replace } => {
            let mut args = vec!["restore".into(), wslpath(input)];
            if let Some(n) = name { args.push("--name".into()); args.push(n.clone()); }
            if *replace { args.push("--replace".into()); }
            args
        }
        Command::Destroy { ref name, yes } => {
            let mut args = vec!["destroy".into(), name.clone()];
            if *yes { args.push("--yes".into()); }
            args
        }
        Command::Rebuild { ref name } => vec!["rebuild".into(), name.clone()],
        Command::WaitReady { ref name, timeout } => {
            vec!["wait-ready".into(), name.clone(), "--timeout".into(), timeout.to_string()]
        }
        Command::PlatformCheck | Command::PlatformSetup => unreachable!(),
    }
}

pub fn run(command: Command) -> ! {
    match command {
        Command::PlatformCheck => {
            println!("{}", platform_check_json());
            process::exit(0);
        }
        Command::PlatformSetup => {
            platform_setup();
            process::exit(0);
        }
        _ => {}
    }

    if !wsl_status_output().0 {
        eprintln!("WSL2 is required but not installed. attempting to install...");
        if !try_install_wsl() || !wsl_status_output().0 {
            die("WSL2 installation failed or was cancelled. reboot if you just installed it, or install manually:\n    \
                 wsl --install --no-distribution");
        }
        eprintln!("WSL2 installed.");
    }

    if !distro_registered() {
        eprintln!("first run: setting up vesta WSL2 environment...");
        bootstrap_distro();
    }

    let is_setup = matches!(command, Command::Setup { .. });
    let is_destroy = matches!(command, Command::Destroy { .. });

    if is_destroy {
        remove_autostart();
    }

    ensure_services();

    let cmd_args = command_args(&command);
    let cmd_args_refs: Vec<&str> = cmd_args.iter().map(|s| s.as_str()).collect();
    let mut args: Vec<&str> = vec!["-d", WSL_DISTRO, "--exec", VESTA_LINUX_BIN];
    args.extend(&cmd_args_refs);

    if matches!(command, Command::Auth { token: None, .. }) {
        let child = process::Command::new("wsl.exe")
            .args(&args)
            .stdin(process::Stdio::inherit())
            .stdout(process::Stdio::piped())
            .stderr(process::Stdio::piped())
            .spawn()
            .unwrap_or_else(|_| die("failed to execute wsl.exe"));
        let status = run_passthrough(child);
        process::exit(status.code().unwrap_or(1));
    }

    let interactive = matches!(
        command,
        Command::Setup { .. }
            | Command::Destroy { yes: false, .. }
            | Command::Attach { .. }
            | Command::Shell { .. }
    );

    if interactive {
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

    let wsl_exec = || -> (process::ExitStatus, String) {
        let output = process::Command::new("wsl.exe")
            .args(&args)
            .stdout(process::Stdio::piped())
            .stderr(process::Stdio::piped())
            .output()
            .unwrap_or_else(|_| die("failed to execute wsl.exe"));
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let stdout = String::from_utf8_lossy(&output.stdout);
        if !stdout.is_empty() {
            print!("{}", stdout);
        }
        for line in stderr.lines() {
            let clean = strip_ansi(line);
            if !clean.trim().is_empty() {
                eprintln!("{}", clean);
            }
        }
        (output.status, stderr)
    };

    let (status, _stderr) = wsl_exec();

    if !status.success() && !distro_healthy() {
        eprintln!("distro is unhealthy. attempting recovery...");
        let _ = process::Command::new("wsl.exe")
            .args(["--terminate", WSL_DISTRO])
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
        ensure_services();

        let (retry, _) = wsl_exec();
        if retry.success() {
            if is_setup {
                install_autostart();
            }
            process::exit(0);
        }

        unregister_distro();
        eprintln!("reinstalling vesta WSL2 environment...");
        bootstrap_distro();
        ensure_services();

        let (status, _) = wsl_exec();
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
