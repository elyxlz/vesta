#[cfg(target_os = "macos")]
mod fps_unlock;

#[tauri::command]
fn focus_window(app: tauri::AppHandle) {
    use tauri::Manager;
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn set_theme(window: tauri::Window, theme: String) {
    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    {
        let tauri_theme = match theme.as_str() {
            "dark" => Some(tauri::Theme::Dark),
            "light" => Some(tauri::Theme::Light),
            _ => None,
        };
        let _ = window.set_theme(tauri_theme);
    }
    #[cfg(any(target_os = "ios", target_os = "android"))]
    let _ = (window, theme);
}

#[cfg(target_os = "linux")]
#[tauri::command]
async fn install_update(version: String) -> Result<(), String> {
    use std::process::Command;

    let arch = std::env::consts::ARCH;

    // Try dpkg (Debian/Ubuntu) first, then rpm (Fedora/RHEL)
    let (url, install_cmd) = if Command::new("dpkg").arg("--version").output().is_ok() {
        let pkg_arch = match arch {
            "x86_64" => "amd64",
            "aarch64" => "arm64",
            _ => return Err(format!("Unsupported architecture: {arch}")),
        };
        let filename = format!("Vesta_{version}_{pkg_arch}.deb");
        let url =
            format!("https://github.com/elyxlz/vesta/releases/download/v{version}/{filename}");
        (url, vec!["dpkg", "-i"])
    } else if Command::new("rpm").arg("--version").output().is_ok() {
        let pkg_arch = match arch {
            "x86_64" => "x86_64",
            "aarch64" => "aarch64",
            _ => return Err(format!("Unsupported architecture: {arch}")),
        };
        let filename = format!("Vesta-{version}-1.{pkg_arch}.rpm");
        let url =
            format!("https://github.com/elyxlz/vesta/releases/download/v{version}/{filename}");
        (url, vec!["rpm", "-U", "--force"])
    } else {
        return Err("No supported package manager (dpkg/rpm) found".into());
    };

    let tmp_dir = std::env::temp_dir().join("vesta-update");
    std::fs::create_dir_all(&tmp_dir).map_err(|e| e.to_string())?;
    let pkg_path = tmp_dir.join("vesta-update-pkg");

    // Download the package
    let output = Command::new("curl")
        .args(["-fsSL", "-o"])
        .arg(&pkg_path)
        .arg(&url)
        .output()
        .map_err(|e| format!("Failed to download update: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "Download failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    // Install with pkexec for GUI privilege escalation
    let mut args = vec![install_cmd[0]];
    for flag in &install_cmd[1..] {
        args.push(flag);
    }
    let pkg_path_str = pkg_path.to_string_lossy().to_string();
    args.push(&pkg_path_str);

    let output = Command::new("pkexec")
        .args(&args)
        .output()
        .map_err(|e| format!("Failed to run pkexec: {e}"))?;

    // Clean up
    let _ = std::fs::remove_dir_all(&tmp_dir);

    if !output.status.success() {
        return Err(format!(
            "Install failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    Ok(())
}

#[cfg(mobile)]
#[tauri::mobile_entry_point]
pub fn mobile_entry_point() {
    run();
}

pub fn run() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .setup(|_app| {
            #[cfg(not(target_os = "android"))]
            use tauri::Manager;

            #[cfg(any(target_os = "macos", target_os = "windows"))]
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

                    window.with_webview(|webview| unsafe {
                        fps_unlock::unlock(webview.inner().cast());
                    }).ok();
                }
                #[cfg(target_os = "windows")]
                {
                    use window_vibrancy::apply_mica;
                    if apply_mica(&window, None).is_err() {
                        let _ = window_vibrancy::apply_acrylic(&window, Some((0, 0, 0, 20)));
                    }
                }
            }

            #[cfg(target_os = "ios")]
            if let Some(window) = _app.get_webview_window("main") {
                window.with_webview(|webview| {
                    unsafe {
                        let wv: *mut std::ffi::c_void = webview.inner();
                        let wv_ref = &*(wv as *const objc2::runtime::AnyObject);

                        // Enable native swipe back/forward navigation
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
                    }
                }).ok();
            }

            // On Linux, disable decorations so Wayland transparency works
            #[cfg(any(
                target_os = "linux",
                target_os = "dragonfly",
                target_os = "freebsd",
                target_os = "netbsd",
                target_os = "openbsd"
            ))]
            if let Some(window) = _app.get_webview_window("main") {
                let _ = window.set_decorations(false);
                let _ = window.set_shadow(false);

                window.with_webview(|webview| {
                    use webkit2gtk::{WebViewExt, PermissionRequestExt};
                    let wv = webview.inner();

                    wv.connect_permission_request(|_wv, request: &webkit2gtk::PermissionRequest| {
                        request.allow();
                        true
                    });
                }).ok();
            }

            Ok(())
        })
        .invoke_handler({
            #[cfg(target_os = "linux")]
            {
                tauri::generate_handler![set_theme, focus_window, install_update]
            }
            #[cfg(not(target_os = "linux"))]
            {
                tauri::generate_handler![set_theme, focus_window]
            }
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
