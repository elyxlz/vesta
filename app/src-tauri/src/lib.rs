#[cfg(mobile)]
#[tauri::mobile_entry_point]
pub fn mobile_entry_point() {
    run();
}

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
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
            #[cfg(target_os = "ios")]
            {
                use tauri::Manager;
                if let Some(window) = _app.get_webview_window("main") {
                    window.with_webview(|webview| {
                        unsafe {
                            let wv: *mut std::ffi::c_void = webview.inner();
                            let wv_ref = &*(wv as *const objc2::runtime::AnyObject);
                            let scroll_view: *mut std::ffi::c_void =
                                objc2::msg_send![wv_ref, scrollView];
                            if !scroll_view.is_null() {
                                let sv_ref = &*(scroll_view as *const objc2::runtime::AnyObject);
                                let _: () = objc2::msg_send![
                                    sv_ref,
                                    setContentInsetAdjustmentBehavior: 2i64
                                ];
                            }
                        }
                    }).ok();
                }
            }
            Ok(())
        })
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
