mod commands;
mod error;
mod runtime;
mod state;

use state::AppState;

pub fn run() {
    let app_state = AppState::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            commands::agents::agent_exists,
            commands::agents::agent_status,
            commands::agents::create_agent,
            commands::agents::start_agent,
            commands::agents::stop_agent,
            commands::agents::delete_agent,
            commands::chat::attach_chat,
            commands::chat::send_message,
            commands::chat::detach_chat,
            commands::logs::stream_logs,
            commands::logs::stop_logs,
            commands::auth::start_auth,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
