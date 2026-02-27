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
        let session = state.chat_session.read().await;
        if session.is_some() {
            return Err(VestaError::new(
                ErrorCode::AttachFailed,
                "already attached",
            ));
        }
    }

    let handle = attach_to_agent(on_event).await?;

    let mut session = state.chat_session.write().await;
    *session = Some(ChatSession {
        stdin_tx: handle.stdin_tx,
        cancel: handle.cancel,
    });

    Ok(())
}

#[tauri::command]
pub async fn send_message(
    state: State<'_, AppState>,
    message: String,
) -> Result<(), VestaError> {
    let session = state.chat_session.read().await;
    let s = session.as_ref().ok_or_else(|| {
        VestaError::new(ErrorCode::AttachFailed, "not attached")
    })?;

    s.stdin_tx
        .send(format!("{}\n", message))
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
