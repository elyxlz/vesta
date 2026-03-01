use tauri::{ipc::Channel, State};
use tokio_util::sync::CancellationToken;

use crate::error::VestaError;
use crate::runtime::cli::{stream_agent_logs, LogEvent};
use crate::state::{AppState, LogStream};

#[tauri::command]
pub async fn stream_logs(
    state: State<'_, AppState>,
    on_event: Channel<LogEvent>,
) -> Result<(), VestaError> {
    let cancel = CancellationToken::new();

    {
        let mut stream = state.log_stream.write().await;
        if let Some(old) = stream.take() {
            old.cancel.cancel();
        }
        *stream = Some(LogStream {
            cancel: cancel.clone(),
        });
    }

    let log_stream = state.log_stream.clone();
    let cleanup_cancel = cancel.clone();
    tokio::spawn(async move {
        cleanup_cancel.cancelled().await;
        let mut stream = log_stream.write().await;
        if let Some(ref s) = *stream {
            if s.cancel.is_cancelled() {
                *stream = None;
            }
        }
    });

    stream_agent_logs(on_event, cancel).await
}

#[tauri::command]
pub async fn stop_logs(state: State<'_, AppState>) -> Result<(), VestaError> {
    let mut stream = state.log_stream.write().await;
    if let Some(s) = stream.take() {
        s.cancel.cancel();
    }
    Ok(())
}
