use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

pub struct LogStream {
    pub cancel: CancellationToken,
}

pub struct AppState {
    pub log_streams: Arc<RwLock<HashMap<String, LogStream>>>,
    pub auth_code_tx: Arc<RwLock<Option<tokio::sync::oneshot::Sender<String>>>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            log_streams: Arc::new(RwLock::new(HashMap::new())),
            auth_code_tx: Arc::new(RwLock::new(None)),
        }
    }
}
