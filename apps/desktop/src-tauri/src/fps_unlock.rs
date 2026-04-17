//! Disable WebKit's 60fps cap on macOS, enabling the display's native refresh rate.
//! Uses private WebKit APIs — not App Store compatible.

use objc2::runtime::{AnyClass, AnyObject, Bool, Sel};
use objc2::{msg_send, sel};

const TARGET_KEY: &str = "PreferPageRenderingUpdatesNear60FPSEnabled";

/// Toggle the 60fps cap off on a WKWebView.
///
/// # Safety
///
/// `wk_webview_ptr` must be a valid pointer to a `WKWebView` instance.
/// Must be called from the main thread.
pub unsafe fn unlock(wk_webview_ptr: *mut std::ffi::c_void) -> bool {
    let wk_webview = wk_webview_ptr as *mut AnyObject;
    if wk_webview.is_null() {
        return false;
    }

    let config: *mut AnyObject = unsafe { msg_send![wk_webview, configuration] };
    if config.is_null() {
        return false;
    }
    let preferences: *mut AnyObject = unsafe { msg_send![config, preferences] };
    if preferences.is_null() {
        return false;
    }

    let Some(wk_prefs_class) = AnyClass::get(c"WKPreferences") else {
        return false;
    };

    let sel_features: Sel = sel!(_features);
    let responds: Bool = unsafe { msg_send![wk_prefs_class, respondsToSelector: sel_features] };
    if !responds.as_bool() {
        return false;
    }

    let features: *mut AnyObject = unsafe { msg_send![wk_prefs_class, _features] };
    if features.is_null() {
        return false;
    }

    let count: usize = unsafe { msg_send![features, count] };
    for i in 0..count {
        let feature: *mut AnyObject = unsafe { msg_send![features, objectAtIndex: i] };
        if feature.is_null() {
            continue;
        }
        let key: *mut AnyObject = unsafe { msg_send![feature, key] };
        if key.is_null() {
            continue;
        }

        let key_nsstring = unsafe { &*(key as *const objc2_foundation::NSString) };
        if key_nsstring.to_string() == TARGET_KEY {
            let sel_set: Sel = sel!(_setEnabled:forFeature:);
            let can_set: Bool = unsafe { msg_send![preferences, respondsToSelector: sel_set] };
            if !can_set.as_bool() {
                return false;
            }

            let objc_bool = Bool::new(false);
            let _: () =
                unsafe { msg_send![preferences, _setEnabled: objc_bool, forFeature: feature] };
            return true;
        }
    }

    false
}
