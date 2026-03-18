use crate::error::{ErrorCode, VestaError};
use crate::runtime::cli;

#[tauri::command]
pub async fn platform_check() -> Result<cli::PlatformStatus, VestaError> {
    cli::platform_check().await
}

#[tauri::command]
pub async fn platform_setup() -> Result<cli::PlatformStatus, VestaError> {
    cli::platform_setup().await
}

#[tauri::command]
pub fn get_os() -> &'static str {
    #[cfg(target_os = "linux")]
    return "linux";
    #[cfg(target_os = "macos")]
    return "macos";
    #[cfg(target_os = "windows")]
    return "windows";
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
    return "unknown";
}

#[tauri::command]
pub async fn run_install_script(version: String) -> Result<(), VestaError> {
    // Detect architecture
    let arch_out = tokio::process::Command::new("uname")
        .arg("-m")
        .output()
        .await
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, e.to_string()))?;
    let arch = std::str::from_utf8(&arch_out.stdout).unwrap_or("").trim().to_string();

    // Detect package manager
    let has_dpkg = tokio::process::Command::new("which")
        .arg("dpkg")
        .status()
        .await
        .map(|s| s.success())
        .unwrap_or(false);
    let has_rpm = tokio::process::Command::new("which")
        .arg("rpm")
        .status()
        .await
        .map(|s| s.success())
        .unwrap_or(false);

    let (filename, install_cmd) = if has_dpkg {
        let pkg_arch = if arch == "aarch64" { "arm64" } else { "amd64" };
        let name = format!("Vesta_{version}_{pkg_arch}.deb");
        let cmd = format!("dpkg -i /tmp/{name}");
        (name, cmd)
    } else if has_rpm {
        let pkg_arch = if arch == "aarch64" { "aarch64" } else { "x86_64" };
        let name = format!("Vesta-{version}-1.{pkg_arch}.rpm");
        let cmd = format!("rpm -U --force /tmp/{name}");
        (name, cmd)
    } else {
        return Err(VestaError::new(ErrorCode::ExecFailed, "no supported package manager (dpkg or rpm)"));
    };

    let tmp_path = format!("/tmp/{filename}");
    let url = format!("https://github.com/elyxlz/vesta/releases/download/v{version}/{filename}");

    // Download package as current user (no root needed)
    let download = tokio::process::Command::new("curl")
        .args(["-fsSL", "-o", &tmp_path, &url])
        .status()
        .await
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, e.to_string()))?;
    if !download.success() {
        return Err(VestaError::new(ErrorCode::ExecFailed, "failed to download package"));
    }

    // Install with pkexec — shows a graphical polkit auth dialog
    let status = tokio::process::Command::new("pkexec")
        .args(["bash", "-c", &install_cmd])
        .status()
        .await
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, e.to_string()))?;

    let _ = std::fs::remove_file(&tmp_path);

    if !status.success() {
        return Err(VestaError::new(ErrorCode::ExecFailed, "package install failed or was cancelled"));
    }
    Ok(())
}
