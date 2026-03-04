mod commands;
mod error;
mod runtime;
mod state;

use state::AppState;

pub fn run() {
    let app_state = AppState::new();

    tauri::Builder::default()
        .manage(app_state)
        .setup(|_app| {
            #[cfg(any(target_os = "macos", target_os = "windows"))]
            {
                use tauri::Manager;
                if let Some(window) = _app.get_webview_window("main") {
                    #[cfg(target_os = "macos")]
                    {
                        use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};
                        let _ = apply_vibrancy(
                            &window,
                            NSVisualEffectMaterial::HudWindow,
                            None,
                            None,
                        );
                    }
                    #[cfg(target_os = "windows")]
                    {
                        use window_vibrancy::apply_mica;
                        if apply_mica(&window, None).is_err() {
                            let _ = window_vibrancy::apply_acrylic(&window, Some((0, 0, 0, 20)));
                        }
                    }
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::agents::agent_status,
            commands::agents::create_agent,
            commands::agents::start_agent,
            commands::agents::stop_agent,
            commands::agents::restart_agent,
            commands::agents::delete_agent,
            commands::agents::set_agent_name,
            commands::agents::agent_host,
            commands::logs::stream_logs,
            commands::logs::stop_logs,
            commands::auth::authenticate,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
