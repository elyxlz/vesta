use crate::ServerConfig;
use std::process;

const VESTAD_SERVICE: &str = "vestad";
const BOOT_CRASH_CHECK_DELAY_MS: u64 = 500;
const MAX_BOOT_LOG_LINES: usize = 20;

pub fn boot_log_path() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    std::path::PathBuf::from(home)
        .join(".config/vesta/vestad-boot.log")
}

/// Read the first few lines of the boot log for error reporting.
pub fn boot_log_summary() -> String {
    std::fs::read_to_string(boot_log_path())
        .unwrap_or_default()
        .lines()
        .take(MAX_BOOT_LOG_LINES)
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn boot() -> Result<(), String> {
    // If already running, nothing to do
    let status = process::Command::new("systemctl")
        .args(["--user", "is-active", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();

    if status.map(|s| s.success()).unwrap_or(false) {
        return Ok(());
    }

    // Try systemctl first (works if vestad already installed its service)
    let status = process::Command::new("systemctl")
        .args(["--user", "start", VESTAD_SERVICE])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();

    if status.map(|s| s.success()).unwrap_or(false) {
        return Ok(());
    }

    // Fallback: start vestad directly (first run — vestad will install the service itself)
    let home = std::env::var("HOME").map_err(|_| "HOME not set".to_string())?;
    let vestad_bin = format!("{}/.local/bin/vestad", home);
    if !std::path::Path::new(&vestad_bin).exists() {
        return Err("vestad not found. run: vesta setup".into());
    }

    // Log stderr so we can surface errors if vestad fails to start
    let log_path = boot_log_path();
    let log_file = std::fs::File::create(&log_path).ok();
    let stderr_cfg = match log_file {
        Some(f) => process::Stdio::from(f),
        None => process::Stdio::null(),
    };

    let mut child = process::Command::new(&vestad_bin)
        .args(["serve"])
        .stdout(process::Stdio::null())
        .stderr(stderr_cfg)
        .spawn()
        .map_err(|e| format!("failed to start {}: {}", vestad_bin, e))?;

    // Give vestad a moment to crash-check (e.g. docker permission denied)
    std::thread::sleep(std::time::Duration::from_millis(BOOT_CRASH_CHECK_DELAY_MS));
    if let Ok(Some(status)) = child.try_wait() {
        if !status.success() {
            let detail = boot_log_summary();
            return Err(if detail.is_empty() {
                format!("vestad exited with code {}", status.code().unwrap_or(-1))
            } else {
                format!("vestad failed to start:\n{}", detail)
            });
        }
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

    // Skip copy if source and dest are the same file
    let same_file = std::fs::canonicalize(&source)
        .and_then(|s| std::fs::canonicalize(&dest).map(|d| s == d))
        .unwrap_or(false);
    if same_file {
        return Ok(dest);
    }

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
