mod commands;
mod error;
mod runtime;
mod state;

use state::AppState;

pub fn run() {
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install rustls crypto provider");

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
            commands::platform::auto_setup,
            commands::platform::platform_check,
            commands::platform::platform_setup,
            commands::platform::connect_to_server,
            commands::platform::run_install_script,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    #[cfg(target_os = "macos")]
    {
        use tauri::Manager;
        if let Some(main_window) = builder.get_webview_window("main") {
            let win = main_window.clone();
            main_window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = win.hide();
                }
            });
        }
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
