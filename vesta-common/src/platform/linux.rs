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

pub fn install_vestad_from(bundled: Option<&std::path::Path>) -> Result<String, String> {
    let home = std::env::var("HOME").map_err(|_| "HOME not set".to_string())?;
    let bin_dir = format!("{}/.local/bin", home);
    let dest = format!("{}/vestad", bin_dir);
    std::fs::create_dir_all(&bin_dir).map_err(|e| format!("failed to create {}: {}", bin_dir, e))?;

    let source = obtain_vestad(bundled)?;

    std::fs::copy(&source, &dest).map_err(|e| format!("failed to install vestad: {}", e))?;
    if let Some(parent) = source.parent().filter(|p| p.starts_with("/tmp/")) {
        let _ = std::fs::remove_dir_all(parent);
    }
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&dest, std::fs::Permissions::from_mode(0o755)).ok();
    eprintln!("installed vestad to {}", dest);
    Ok(dest)
}

#[cfg(debug_assertions)]
fn obtain_vestad(_bundled: Option<&std::path::Path>) -> Result<std::path::PathBuf, String> {
    let workspace_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("cannot determine workspace root")?;

    eprintln!("building vestad from source...");
    let status = process::Command::new("cargo")
        .args(["build", "-p", "vestad"])
        .current_dir(workspace_root)
        .stderr(process::Stdio::inherit())
        .status();
    if !status.map(|s| s.success()).unwrap_or(false) {
        return Err("cargo build -p vestad failed".into());
    }

    Ok(workspace_root.join("target/debug/vestad"))
}

#[cfg(not(debug_assertions))]
fn obtain_vestad(bundled: Option<&std::path::Path>) -> Result<std::path::PathBuf, String> {
    // Check for bundled binary (passed by Tauri app from its resource dir)
    if let Some(path) = bundled {
        if path.exists() {
            return Ok(path.to_path_buf());
        }
    }

    // Check next to current executable (CLI install puts both in ~/.local/bin/)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let adjacent = dir.join("vestad");
            if adjacent.exists() {
                return Ok(adjacent);
            }
        }
    }

    Err("vestad not found. reinstall vesta or place vestad next to the vesta binary".into())
}
