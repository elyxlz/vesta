use crate::error::VestaError;
use crate::runtime::cli::{self, AgentInfo};

#[tauri::command]
pub async fn agent_status() -> Result<AgentInfo, VestaError> {
    cli::agent_status().await
}

#[tauri::command]
pub async fn create_agent(name: Option<String>) -> Result<(), VestaError> {
    cli::create_agent(name).await
}

#[tauri::command]
pub async fn start_agent() -> Result<(), VestaError> {
    cli::start_agent().await
}

#[tauri::command]
pub async fn stop_agent() -> Result<(), VestaError> {
    cli::stop_agent().await
}

#[tauri::command]
pub async fn restart_agent() -> Result<(), VestaError> {
    cli::restart_agent().await
}

#[tauri::command]
pub async fn delete_agent() -> Result<(), VestaError> {
    cli::delete_agent().await
}

#[tauri::command]
pub async fn set_agent_name(name: String) -> Result<(), VestaError> {
    cli::set_agent_name(&name).await
}

#[tauri::command]
pub async fn agent_host() -> String {
    cli::agent_host().await
}
