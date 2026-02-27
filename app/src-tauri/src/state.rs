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
    pub chat_session: RwLock<Option<ChatSession>>,
    pub log_stream: RwLock<Option<LogStream>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            chat_session: RwLock::new(None),
            log_stream: RwLock::new(None),
        }
    }
}
