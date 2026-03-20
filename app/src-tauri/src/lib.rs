mod commands;
mod error;
mod runtime;
mod state;

use state::AppState;

pub fn run() {
    let app_state = AppState::new();

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
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
                        let _ = window.set_decorations(true);
                        let _ = window
                            .set_title_bar_style(tauri::TitleBarStyle::Overlay);
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
            commands::agents::list_agents,
            commands::agents::agent_status,
            commands::agents::create_agent,
            commands::agents::start_agent,
            commands::agents::stop_agent,
            commands::agents::restart_agent,
            commands::agents::delete_agent,
            commands::agents::rebuild_agent,
            commands::agents::backup_agent,
            commands::agents::restore_agent,
            commands::agents::wait_for_ready,
            commands::agents::agent_host,
            commands::agents::get_server_config,
            commands::logs::stream_logs,
            commands::logs::stop_logs,
            commands::auth::authenticate,
            commands::auth::submit_auth_code,
            commands::platform::platform_check,
            commands::platform::platform_setup,
            commands::platform::run_install_script,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    #[cfg(target_os = "macos")]
    {
        use tauri::Manager;
        let main_window = builder.get_webview_window("main").unwrap();
        let win = main_window.clone();
        main_window.on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = win.hide();
            }
        });
    }

    builder.run(|app_handle, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = event {
            use tauri::Manager;
            if let Some(window) = app_handle.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        let _ = (app_handle, event);
    });
}
