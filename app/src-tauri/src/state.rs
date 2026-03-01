use std::sync::Arc;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

pub struct LogStream {
    pub cancel: CancellationToken,
}

pub struct AppState {
    pub log_stream: Arc<RwLock<Option<LogStream>>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            log_stream: Arc::new(RwLock::new(None)),
        }
    }
}
