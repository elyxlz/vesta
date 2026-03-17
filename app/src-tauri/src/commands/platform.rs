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
pub async fn run_install_script() -> Result<(), VestaError> {
    let status = tokio::process::Command::new("bash")
        .arg("-c")
        .arg("curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash")
        .status()
        .await
        .map_err(|e| VestaError::new(ErrorCode::ExecFailed, e.to_string()))?;

    if !status.success() {
        return Err(VestaError::new(ErrorCode::ExecFailed, "install script failed"));
    }
    Ok(())
}
