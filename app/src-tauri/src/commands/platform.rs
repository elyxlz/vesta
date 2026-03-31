use tauri::Manager;

use crate::error::{ErrorCode, VestaError};
use crate::runtime::cli;

#[tauri::command]
pub async fn auto_setup(app: tauri::AppHandle) -> Result<bool, VestaError> {
    let bundled = app
        .path()
        .resource_dir()
        .ok()
        .map(|d| d.join("resources").join("vestad"))
        .filter(|p| p.exists());
    cli::auto_setup_with(bundled.as_deref()).await
}

#[tauri::command]
pub async fn platform_check() -> Result<cli::PlatformStatus, VestaError> {
    cli::platform_check().await
}

#[tauri::command]
pub async fn platform_setup() -> Result<cli::PlatformStatus, VestaError> {
    cli::platform_setup().await
}

#[tauri::command]
pub async fn connect_to_server(url: String, api_key: String) -> Result<cli::ServerConfig, VestaError> {
    cli::connect_to_server(url, api_key).await
}

#[tauri::command]
pub async fn run_install_script(version: String) -> Result<(), VestaError> {
    let arch = std::env::consts::ARCH;

    let has_dpkg = tokio::process::Command::new("which")
        .arg("dpkg")
        .status()
        .await
        .map(|s| s.success())
        .unwrap_or(false);

    let (filename, pkg_manager, pkg_args) = if has_dpkg {
        let pkg_arch = if arch == "aarch64" { "arm64" } else { "amd64" };
        let name = format!("Vesta_{version}_{pkg_arch}.deb");
        let tmp = format!("/tmp/{name}");
        (name, "dpkg", vec!["-i".to_string(), tmp])
    } else {
        let has_rpm = tokio::process::Command::new("which")
            .arg("rpm")
            .status()
            .await
            .map(|s| s.success())
            .unwrap_or(false);
        if !has_rpm {
            return Err(VestaError::new(
                ErrorCode::ExecFailed,
                "no supported package manager (dpkg or rpm)",
            ));
        }
        let pkg_arch = if arch == "aarch64" {
            "aarch64"
        } else {
            "x86_64"
        };
        let name = format!("Vesta-{version}-1.{pkg_arch}.rpm");
        let tmp = format!("/tmp/{name}");
        (
            name,
            "rpm",
            vec!["-U".to_string(), "--force".to_string(), tmp],
        )
    };

    let tmp_path = format!("/tmp/{filename}");
    let url =
        format!("https://github.com/elyxlz/vesta/releases/download/v{version}/{filename}");

    let download = tokio::process::Command::new("curl")
        .args(["-fsSL", "-o", &tmp_path, &url])
        .status()
        .await
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, e.to_string()))?;
    if !download.success() {
        let _ = tokio::fs::remove_file(&tmp_path).await;
        return Err(VestaError::new(
            ErrorCode::ExecFailed,
            "failed to download package",
        ));
    }

    let status = tokio::process::Command::new("pkexec")
        .arg(pkg_manager)
        .args(&pkg_args)
        .status()
        .await
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, e.to_string()))?;

    let _ = tokio::fs::remove_file(&tmp_path).await;

    if !status.success() {
        return Err(VestaError::new(
            ErrorCode::ExecFailed,
            "package install failed or was cancelled",
        ));
    }
    Ok(())
}
