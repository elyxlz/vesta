use crate::error::VestaError;
use crate::runtime::cli;
use tauri::{AppHandle, Emitter};

#[tauri::command]
pub async fn authenticate(app: AppHandle, name: String) -> Result<(), VestaError> {
    cli::obtain_and_inject_credentials(&name, move |url| {
        let _ = app.emit("auth-url", url);
    })
    .await
}
