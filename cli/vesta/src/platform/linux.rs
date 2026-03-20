use super::{die, ServerConfig};
use std::process;

const VESTAD_SERVICE: &str = "vestad";

pub fn boot() {
    // Check if vestad is already running
    let status = process::Command::new("systemctl")
        .args(["--user", "is-active", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();

    if status.map(|s| s.success()).unwrap_or(false) {
        return;
    }

    // Try starting the service
    let status = process::Command::new("systemctl")
        .args(["--user", "start", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::inherit())
        .status();

    if !status.map(|s| s.success()).unwrap_or(false) {
        die("failed to start vestad. run: vesta setup");
    }
}

pub fn shutdown() {
    let _ = process::Command::new("systemctl")
        .args(["--user", "stop", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
}

pub fn install_autostart(vestad_path: &str) {
    let home = std::env::var("HOME").unwrap_or_else(|_| die("HOME not set"));
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
        .unwrap_or_else(|e| die(&format!("failed to write service file: {}", e)));

    let _ = process::Command::new("systemctl")
        .args(["--user", "daemon-reload"])
        .status();
    let _ = process::Command::new("systemctl")
        .args(["--user", "enable", VESTAD_SERVICE])
        .status();
}

pub fn server_url() -> String {
    "https://localhost:7860".to_string()
}

pub fn extract_credentials() -> Option<ServerConfig> {
    let home = std::env::var("HOME").ok()?;
    let api_key = std::fs::read_to_string(format!("{}/.config/vesta/api-key", home))
        .ok()?
        .trim()
        .to_string();
    let fingerprint =
        std::fs::read_to_string(format!("{}/.config/vesta/tls/fingerprint", home))
            .ok()
            .map(|s| s.trim().to_string());

    if api_key.is_empty() {
        return None;
    }

    Some(ServerConfig {
        url: server_url(),
        api_key,
        cert_fingerprint: fingerprint,
    })
}

pub fn download_vestad() -> String {
    let target = match std::env::consts::ARCH {
        "x86_64" => "x86_64-unknown-linux-gnu",
        "aarch64" => "aarch64-unknown-linux-gnu",
        other => die(&format!("unsupported architecture: {}", other)),
    };

    let home = std::env::var("HOME").unwrap_or_else(|_| die("HOME not set"));
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
        die("failed to download vestad");
    }

    let status = process::Command::new("tar")
        .args(["-xzf", &format!("{}/{}", tmp, archive), "-C", &tmp])
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        die("failed to extract vestad");
    }

    std::fs::copy(format!("{}/vestad", tmp), &dest)
        .unwrap_or_else(|e| die(&format!("failed to install vestad: {}", e)));

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&dest, std::fs::Permissions::from_mode(0o755)).ok();
    }

    std::fs::remove_dir_all(&tmp).ok();
    eprintln!("installed vestad to {}", dest);
    dest
}
