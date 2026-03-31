use tauri::{ipc::Channel, State};
use tokio_util::sync::CancellationToken;

use crate::error::VestaError;
use crate::runtime::cli::{connect_agent_ws, WsEvent};
use crate::state::{AppState, WsConnection};

#[tauri::command]
pub async fn connect_ws(
    name: String,
    state: State<'_, AppState>,
    on_event: Channel<WsEvent>,
) -> Result<(), VestaError> {
    // Cancel any existing connection for this agent
    {
        let mut conns = state.ws_connections.write().await;
        if let Some(old) = conns.remove(&name) {
            old.cancel.cancel();
        }
    }

    let cancel = CancellationToken::new();
    let tx = connect_agent_ws(&name, on_event, cancel.clone()).await?;

    let mut conns = state.ws_connections.write().await;
    conns.insert(name, WsConnection { cancel, tx });

    Ok(())
}

#[tauri::command]
pub async fn send_ws(
    name: String,
    text: String,
    state: State<'_, AppState>,
) -> Result<(), VestaError> {
    let conns = state.ws_connections.read().await;
    if let Some(conn) = conns.get(&name) {
        conn.tx
            .send(text)
            .await
            .map_err(|_| VestaError::new(crate::error::ErrorCode::Internal, "ws connection closed"))?;
    }
    Ok(())
}

#[tauri::command]
pub async fn disconnect_ws(
    name: String,
    state: State<'_, AppState>,
) -> Result<(), VestaError> {
    let mut conns = state.ws_connections.write().await;
    if let Some(conn) = conns.remove(&name) {
        conn.cancel.cancel();
    }
    Ok(())
}
