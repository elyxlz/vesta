use crate::ServerConfig;
use std::process;

const VESTAD_SERVICE: &str = "vestad";

pub fn boot() -> Result<(), String> {
    let status = process::Command::new("systemctl")
        .args(["--user", "is-active", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();

    if status.map(|s| s.success()).unwrap_or(false) {
        return Ok(());
    }

    let status = process::Command::new("systemctl")
        .args(["--user", "start", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::inherit())
        .status();

    if !status.map(|s| s.success()).unwrap_or(false) {
        return Err("failed to start vestad. run: vesta setup".into());
    }
    Ok(())
}

pub fn shutdown() {
    let _ = process::Command::new("systemctl")
        .args(["--user", "stop", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
}

pub fn install_autostart(vestad_path: &str) -> Result<(), String> {
    let home = std::env::var("HOME").map_err(|_| "HOME not set".to_string())?;
    let unit_dir = format!("{}/.config/systemd/user", home);
    std::fs::create_dir_all(&unit_dir).ok();

    let unit_content = format!(
        r#"[Unit]
Description=Vesta API Server
After=docker.service

[Service]
ExecStart={vestad_path} serve
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"#
    );

    let unit_path = format!("{}/{}.service", unit_dir, VESTAD_SERVICE);
    std::fs::write(&unit_path, unit_content)
        .map_err(|e| format!("failed to write service file: {}", e))?;

    let _ = process::Command::new("systemctl")
        .args(["--user", "daemon-reload"])
        .status();
    let _ = process::Command::new("systemctl")
        .args(["--user", "enable", VESTAD_SERVICE])
        .status();
    Ok(())
}

pub fn server_url() -> String {
    crate::default_server_url()
}

pub fn extract_credentials() -> Option<ServerConfig> {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/root".to_string());
    let api_key = std::fs::read_to_string(format!("{}/.config/vesta/api-key", home))
        .ok()?
        .trim()
        .to_string();
    let fingerprint =
        std::fs::read_to_string(format!("{}/.config/vesta/tls/fingerprint", home))
            .ok()
            .map(|s| s.trim().to_string());
    let cert_pem =
        std::fs::read_to_string(format!("{}/.config/vesta/tls/cert.pem", home)).ok();

    if api_key.is_empty() {
        return None;
    }

    Some(ServerConfig {
        url: server_url(),
        api_key,
        cert_fingerprint: fingerprint,
        cert_pem,
    })
}

pub fn download_vestad() -> Result<String, String> {
    let target = match std::env::consts::ARCH {
        "x86_64" => "x86_64-unknown-linux-gnu",
        "aarch64" => "aarch64-unknown-linux-gnu",
        other => return Err(format!("unsupported architecture: {}", other)),
    };

    let home = std::env::var("HOME").map_err(|_| "HOME not set".to_string())?;
    let dest = format!("{}/.local/bin/vestad", home);
    std::fs::create_dir_all(format!("{}/.local/bin", home)).ok();

    let archive = format!("vestad-{}.tar.gz", target);
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/latest/download/{}",
        archive
    );
    let tmp = format!("/tmp/vestad-download-{}", std::process::id());
    std::fs::create_dir_all(&tmp).ok();

    eprintln!("downloading vestad...");
    let status = process::Command::new("curl")
        .args(["-fsSL", "-o", &format!("{}/{}", tmp, archive), &url])
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        return Err("failed to download vestad".into());
    }

    let status = process::Command::new("tar")
        .args(["-xzf", &format!("{}/{}", tmp, archive), "-C", &tmp])
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        return Err("failed to extract vestad".into());
    }

    std::fs::copy(format!("{}/vestad", tmp), &dest)
        .map_err(|e| format!("failed to install vestad: {}", e))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&dest, std::fs::Permissions::from_mode(0o755)).ok();
    }

    std::fs::remove_dir_all(&tmp).ok();
    eprintln!("installed vestad to {}", dest);
    Ok(dest)
}
