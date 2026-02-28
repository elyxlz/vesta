use crate::error::VestaError;
use crate::runtime::cli;

#[tauri::command]
pub async fn authenticate() -> Result<(), VestaError> {
    cli::obtain_and_inject_token().await
}
