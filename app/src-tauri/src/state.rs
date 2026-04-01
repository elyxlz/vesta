use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex, RwLock};
use tokio_util::sync::CancellationToken;

pub struct LogStream {
    pub cancel: CancellationToken,
}

pub struct WsConnection {
    pub cancel: CancellationToken,
    pub tx: mpsc::Sender<String>,
}

pub struct AppState {
    pub log_streams: Arc<RwLock<HashMap<String, LogStream>>>,
    pub ws_connections: Arc<RwLock<HashMap<String, WsConnection>>>,
    pub auth_code_tx: Arc<Mutex<Option<tokio::sync::oneshot::Sender<String>>>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            log_streams: Arc::new(RwLock::new(HashMap::new())),
            ws_connections: Arc::new(RwLock::new(HashMap::new())),
            auth_code_tx: Arc::new(Mutex::new(None)),
        }
    }
}
