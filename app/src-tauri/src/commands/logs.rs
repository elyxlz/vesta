use tauri::{ipc::Channel, State};
use tokio_util::sync::CancellationToken;

use crate::error::VestaError;
use crate::runtime::cli::{stream_agent_logs, LogEvent};
use crate::state::{AppState, LogStream};

#[tauri::command]
pub async fn stream_logs(
    name: String,
    state: State<'_, AppState>,
    on_event: Channel<LogEvent>,
) -> Result<(), VestaError> {
    let cancel = CancellationToken::new();

    {
        let mut streams = state.log_streams.write().await;
        if let Some(old) = streams.remove(&name) {
            old.cancel.cancel();
        }
        streams.insert(name.clone(), LogStream {
            cancel: cancel.clone(),
        });
    }

    let log_streams = state.log_streams.clone();
    let cleanup_cancel = cancel.clone();
    let cleanup_name = name.clone();
    tokio::spawn(async move {
        cleanup_cancel.cancelled().await;
        let mut streams = log_streams.write().await;
        if let Some(ref s) = streams.get(&cleanup_name) {
            if s.cancel.is_cancelled() {
                streams.remove(&cleanup_name);
            }
        }
    });

    stream_agent_logs(&name, on_event, cancel).await
}

#[tauri::command]
pub async fn stop_logs(name: String, state: State<'_, AppState>) -> Result<(), VestaError> {
    let mut streams = state.log_streams.write().await;
    if let Some(s) = streams.remove(&name) {
        s.cancel.cancel();
    }
    Ok(())
}
