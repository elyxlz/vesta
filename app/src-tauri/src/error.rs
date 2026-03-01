use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub enum ErrorCode {
    ExecFailed,
    Internal,
}

#[derive(Debug, Clone, Serialize)]
pub struct VestaError {
    pub code: ErrorCode,
    pub message: String,
}

impl VestaError {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for VestaError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for VestaError {}
