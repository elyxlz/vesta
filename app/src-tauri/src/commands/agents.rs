use crate::error::VestaError;
use crate::runtime::cli::{self, AgentInfo, ListEntry, ServerConfig};

#[tauri::command]
pub async fn list_agents() -> Result<Vec<ListEntry>, VestaError> {
    cli::list_agents().await
}

#[tauri::command]
pub async fn agent_status(name: String) -> Result<AgentInfo, VestaError> {
    cli::agent_status(&name).await
}

#[tauri::command]
pub async fn create_agent(name: String) -> Result<(), VestaError> {
    cli::create_agent(Some(name)).await
}

#[tauri::command]
pub async fn start_agent(name: String) -> Result<(), VestaError> {
    cli::start_agent(&name).await
}

#[tauri::command]
pub async fn stop_agent(name: String) -> Result<(), VestaError> {
    cli::stop_agent(&name).await
}

#[tauri::command]
pub async fn restart_agent(name: String) -> Result<(), VestaError> {
    cli::restart_agent(&name).await
}

#[tauri::command]
pub async fn delete_agent(name: String) -> Result<(), VestaError> {
    cli::delete_agent(&name).await
}

#[tauri::command]
pub async fn rebuild_agent(name: String) -> Result<(), VestaError> {
    cli::rebuild_agent(&name).await
}

#[tauri::command]
pub async fn create_backup(name: String) -> Result<vesta_common::BackupInfo, VestaError> {
    cli::create_backup(&name).await
}

#[tauri::command]
pub async fn list_backups(name: String) -> Result<Vec<vesta_common::BackupInfo>, VestaError> {
    cli::list_backups(&name).await
}

#[tauri::command]
pub async fn restore_backup(name: String, backup_id: String) -> Result<(), VestaError> {
    cli::restore_backup(&name, &backup_id).await
}

#[tauri::command]
pub async fn delete_backup(name: String, backup_id: String) -> Result<(), VestaError> {
    cli::delete_backup(&name, &backup_id).await
}

#[tauri::command]
pub async fn wait_for_ready(name: String, timeout: u64) -> Result<(), VestaError> {
    cli::wait_for_ready(&name, timeout).await
}

#[tauri::command]
pub async fn agent_host() -> String {
    cli::agent_host().await
}

#[tauri::command]
pub async fn get_server_config() -> Result<ServerConfig, VestaError> {
    cli::get_server_config()
}
