use crate::error::VestaError;
use crate::runtime::cli;

#[tauri::command]
pub async fn authenticate(name: String) -> Result<(), VestaError> {
    cli::obtain_and_inject_credentials(&name).await
}
