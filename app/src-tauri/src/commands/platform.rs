use crate::error::VestaError;
use crate::runtime::cli;

#[tauri::command]
pub async fn platform_check() -> Result<cli::PlatformStatus, VestaError> {
    cli::platform_check().await
}

#[tauri::command]
pub async fn platform_setup() -> Result<cli::PlatformStatus, VestaError> {
    cli::platform_setup().await
}
