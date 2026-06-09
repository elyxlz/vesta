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
    let tauri_theme = match theme.as_str() {
        "dark" => Some(tauri::Theme::Dark),
        "light" => Some(tauri::Theme::Light),
        _ => None,
    };
    let _ = window.set_theme(tauri_theme);
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

// Update to a specific version by pointing the updater at that release's manifest,
// rather than the static `releases/latest` endpoint in tauri.conf.json. The app
// always matches the gateway's exact version, and the gateway may be on a beta
// (prerelease) that `releases/latest` never points at. Targeting the version's own
// manifest works identically for stable and beta, so the channel stays a
// vestad-owned concept and the app just follows.
#[cfg(not(target_os = "linux"))]
#[tauri::command]
async fn run_update(app: tauri::AppHandle, version: String) -> Result<(), String> {
    use tauri_plugin_updater::UpdaterExt;

    let url = format!("https://github.com/elyxlz/vesta/releases/download/v{version}/latest.json");
    let endpoint = tauri::Url::parse(&url).map_err(|e| format!("invalid updater url: {e}"))?;
    let updater = app
        .updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())?;

    if let Some(update) = updater.check().await.map_err(|e| e.to_string())? {
        update
            .download_and_install(|_, _| {}, || {})
            .await
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn run() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_oauth::init())
        .setup(|_app| {
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
                tauri::generate_handler![set_theme, focus_window, run_update]
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
