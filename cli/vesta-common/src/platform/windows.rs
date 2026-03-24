use crate::ServerConfig;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process;

const WSL_DISTRO: &str = "vesta-wsl";
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

fn docker_ready() -> bool {
    process::Command::new("wsl.exe")
        .args([
            "-d",
            WSL_DISTRO,
            "--exec",
            "test",
            "-S",
            "/var/run/docker.sock",
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
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

fn install_dir() -> Result<PathBuf, String> {
    let local_app_data =
        std::env::var("LOCALAPPDATA").map_err(|_| "LOCALAPPDATA not set".to_string())?;
    Ok(PathBuf::from(&local_app_data).join(WSL_DISTRO))
}

fn clean_install_dir() {
    if let Ok(v) = std::env::var("LOCALAPPDATA") {
        std::fs::remove_dir_all(PathBuf::from(&v).join(WSL_DISTRO)).ok();
    }
}

fn rootfs_path() -> Result<PathBuf, String> {
    Ok(install_dir()?.join("vesta-wsl-rootfs.tar.gz"))
}

fn download_rootfs() -> Result<PathBuf, String> {
    let path = rootfs_path()?;
    if path.exists() {
        return Ok(path);
    }
    let dir = path.parent().unwrap();
    std::fs::create_dir_all(dir)
        .map_err(|e| format!("failed to create directory: {}", e))?;

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
        .map_err(|_| "failed to download rootfs".to_string())?;

    if !output.status.success() {
        std::fs::remove_file(&tmp_path).ok();
        return Err("failed to download rootfs".into());
    }

    std::fs::rename(&tmp_path, &path)
        .map_err(|e| format!("failed to save rootfs: {}", e))?;
    Ok(path)
}

fn bootstrap_distro() -> Result<(), String> {
    clean_install_dir();
    let install_dir = install_dir()?;
    std::fs::create_dir_all(&install_dir)
        .map_err(|_| "failed to create install directory".to_string())?;

    let rootfs = download_rootfs()?;

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
        .map_err(|_| "failed to run wsl --import".to_string())?;

    if !output.status.success() {
        return Err("failed to set up WSL2 environment".into());
    }
    eprintln!("vesta-wsl distro ready.");
    Ok(())
}

fn ensure_services() -> Result<(), String> {
    if docker_ready() {
        return Ok(());
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
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        eprint!(".");
        io::stderr().flush().ok();
    }
    eprintln!();
    Err("services did not start within 30s".into())
}

fn wsl_run_output(args: &[&str]) -> Option<String> {
    let mut cmd_args = vec!["-d", WSL_DISTRO, "--exec"];
    cmd_args.extend(args);
    let output = process::Command::new("wsl.exe")
        .args(&cmd_args)
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

// --- Public API ---

pub fn boot() -> Result<(), String> {
    if !wsl_status_output().0 {
        eprintln!("WSL2 is required but not installed. attempting to install...");
        if !try_install_wsl() || !wsl_status_output().0 {
            return Err("WSL2 installation failed or was cancelled".into());
        }
    }
    if !distro_registered() {
        eprintln!("first run: setting up vesta WSL2 environment...");
        bootstrap_distro()?;
    }
    ensure_services()
}

pub fn shutdown() {
    let _ = process::Command::new("wsl.exe")
        .args(["--terminate", WSL_DISTRO])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
}

pub fn install_autostart() -> Result<(), String> {
    let exe = std::env::current_exe()
        .map_err(|_| "cannot determine executable path".to_string())?;
    let value = format!("\"{}\" boot", exe.display());
    let _ = process::Command::new("reg")
        .args([
            "add",
            REGISTRY_RUN_KEY,
            "/v",
            "Vesta",
            "/t",
            "REG_SZ",
            "/d",
            &value,
            "/f",
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
    Ok(())
}

pub fn remove_autostart() {
    let _ = process::Command::new("reg")
        .args(["delete", REGISTRY_RUN_KEY, "/v", "Vesta", "/f"])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
}

pub fn server_url() -> String {
    if let Some(ip) = wsl_run_output(&["hostname", "-I"]) {
        let ip = ip.split_whitespace().next().unwrap_or("localhost");
        return format!("https://{}:{}", ip, crate::DEFAULT_API_PORT);
    }
    crate::default_server_url()
}

pub fn extract_credentials() -> Option<ServerConfig> {
    boot().ok()?;
    let api_key = wsl_run_output(&["cat", "/root/.config/vesta/api-key"])?;
    let fingerprint = wsl_run_output(&["cat", "/root/.config/vesta/tls/fingerprint"]);
    let cert_pem = wsl_run_output(&["cat", "/root/.config/vesta/tls/cert.pem"]);

    if api_key.trim().is_empty() {
        return None;
    }

    Some(ServerConfig {
        url: server_url(),
        api_key: api_key.trim().to_string(),
        cert_fingerprint: fingerprint.map(|s| s.trim().to_string()),
        cert_pem,
    })
}
