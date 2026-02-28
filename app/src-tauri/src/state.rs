use std::sync::Arc;
use tokio::sync::{mpsc, RwLock};
use tokio_util::sync::CancellationToken;

pub struct ChatSession {
    pub stdin_tx: mpsc::Sender<String>,
    pub cancel: CancellationToken,
}

pub struct LogStream {
    pub cancel: CancellationToken,
}

pub struct AppState {
    pub chat_session: Arc<RwLock<Option<ChatSession>>>,
    pub log_stream: Arc<RwLock<Option<LogStream>>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            chat_session: Arc::new(RwLock::new(None)),
            log_stream: Arc::new(RwLock::new(None)),
        }
    }
}
