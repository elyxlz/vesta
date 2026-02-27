use tauri::ipc::Channel;
use tokio_util::sync::CancellationToken;

use crate::error::VestaError;
use crate::runtime::cli::{run_claude_auth, AuthEvent};

#[tauri::command]
pub async fn start_auth(
    on_event: Channel<AuthEvent>,
) -> Result<(), VestaError> {
    let cancel = CancellationToken::new();
    run_claude_auth(on_event, cancel).await
}
