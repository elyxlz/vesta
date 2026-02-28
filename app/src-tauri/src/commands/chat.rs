use tauri::{ipc::Channel, State};

use crate::error::{ErrorCode, VestaError};
use crate::runtime::cli::{attach_to_agent, ChatEvent};
use crate::state::{AppState, ChatSession};

#[tauri::command]
pub async fn attach_chat(
    state: State<'_, AppState>,
    on_event: Channel<ChatEvent>,
) -> Result<(), VestaError> {
    {
        let mut session = state.chat_session.write().await;
        if let Some(old) = session.take() {
            old.cancel.cancel();
        }
    }

    let handle = attach_to_agent(on_event).await?;
    let cancel = handle.cancel.clone();

    {
        let mut session = state.chat_session.write().await;
        *session = Some(ChatSession {
            stdin_tx: handle.stdin_tx,
            cancel: handle.cancel,
        });
    }

    let chat_session = state.chat_session.clone();
    tokio::spawn(async move {
        cancel.cancelled().await;
        let mut session = chat_session.write().await;
        *session = None;
    });

    Ok(())
}

#[tauri::command]
pub async fn send_message(
    state: State<'_, AppState>,
    message: String,
) -> Result<(), VestaError> {
    let tx = {
        let session = state.chat_session.read().await;
        session.as_ref()
            .ok_or_else(|| VestaError::new(ErrorCode::AttachFailed, "not attached"))?
            .stdin_tx
            .clone()
    };

    tx.send(format!("{}\n", message))
        .await
        .map_err(|e| VestaError::new(ErrorCode::AttachFailed, e.to_string()))
}

#[tauri::command]
pub async fn detach_chat(state: State<'_, AppState>) -> Result<(), VestaError> {
    let mut session = state.chat_session.write().await;
    if let Some(s) = session.take() {
        s.cancel.cancel();
    }
    Ok(())
}
