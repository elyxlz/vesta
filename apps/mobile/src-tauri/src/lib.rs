// Frontend invokes `focus_window` and `set_theme` on all platforms — expose
// them as no-ops on mobile so the calls don't error out.
#[tauri::command]
fn focus_window(_app: tauri::AppHandle) {}

#[tauri::command]
fn set_theme(_window: tauri::Window, _theme: String) {}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .setup(|_app| {
            #[cfg(target_os = "ios")]
            {
                use tauri::Manager;
                if let Some(window) = _app.get_webview_window("main") {
                    window
                        .with_webview(|webview| unsafe {
                            let wv: *mut std::ffi::c_void = webview.inner();
                            let wv_ref = &*(wv as *const objc2::runtime::AnyObject);

                            let _: () = objc2::msg_send![
                                wv_ref,
                                setAllowsBackForwardNavigationGestures: objc2::runtime::Bool::YES
                            ];

                            let scroll_view: *mut std::ffi::c_void =
                                objc2::msg_send![wv_ref, scrollView];
                            if !scroll_view.is_null() {
                                let sv_ref = &*(scroll_view as *const objc2::runtime::AnyObject);
                                let _: () = objc2::msg_send![
                                    sv_ref,
                                    setContentInsetAdjustmentBehavior: 2i64
                                ];
                            }
                        })
                        .ok();
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![set_theme, focus_window])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    builder.run(|_app_handle, _event| {});
}
