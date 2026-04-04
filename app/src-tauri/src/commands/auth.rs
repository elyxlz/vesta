use crate::error::VestaError;
use crate::runtime::cli;
use crate::state::AppState;
use tauri::{AppHandle, Emitter, Manager};

#[tauri::command]
pub async fn authenticate(app: AppHandle, name: String) -> Result<(), VestaError> {
    let (tx, rx) = tokio::sync::oneshot::channel::<String>();

    let state = app.state::<AppState>();
    *state.auth_code_tx.lock().await = Some(tx);

    let app2 = app.clone();
    cli::obtain_and_inject_credentials(
        &name,
        move |event, payload| {
            let _ = app2.emit(event, payload.unwrap_or("").to_string());
        },
        rx,
    )
    .await
}

#[tauri::command]
pub async fn submit_auth_code(app: AppHandle, code: String) -> Result<(), VestaError> {
    let state = app.state::<AppState>();
    let tx = state.auth_code_tx.lock().await.take();
    if let Some(tx) = tx {
        let _ = tx.send(code);
    }
    Ok(())
}
