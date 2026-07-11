//! The vendored-binary mechanism restic and cloudflared share: the build-time
//! embed lookup (build.rs vendors the binaries into `vendored/` and emits the
//! `*_vendored` cfgs) and the safe on-disk extract (serialized, atomic-rename,
//! fingerprint-marked so a version change re-extracts exactly once).

use std::path::{Path, PathBuf};
use std::sync::Mutex;

#[derive(Debug)]
pub(crate) struct VendoredBinError(String);

impl std::fmt::Display for VendoredBinError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for VendoredBinError {}

/// Serializes extraction so concurrent first-use callers don't write a binary
/// while another thread is exec'ing it (ETXTBSY).
static EXTRACT_LOCK: Mutex<()> = Mutex::new(());

#[cfg(any(restic_vendored, cloudflared_vendored))]
fn fingerprinted(bytes: Vec<u8>) -> (Vec<u8>, String) {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::Hasher;

    let mut hasher = DefaultHasher::new();
    hasher.write(env!("CARGO_PKG_VERSION").as_bytes());
    hasher.write(&bytes);
    let fingerprint = format!("{:016x}", hasher.finish());
    (bytes, fingerprint)
}

#[cfg(restic_vendored)]
pub(crate) fn vendored_restic() -> Option<(&'static [u8], &'static str)> {
    #[derive(rust_embed::RustEmbed)]
    #[folder = "vendored/"]
    #[include = "restic"]
    struct ResticAsset;

    static CACHE: std::sync::OnceLock<Option<(Vec<u8>, String)>> = std::sync::OnceLock::new();
    CACHE
        .get_or_init(|| ResticAsset::get("restic").map(|file| fingerprinted(file.data.into_owned())))
        .as_ref()
        .map(|(bytes, fingerprint)| (bytes.as_slice(), fingerprint.as_str()))
}

#[cfg(not(restic_vendored))]
pub(crate) fn vendored_restic() -> Option<(&'static [u8], &'static str)> {
    None
}

#[cfg(cloudflared_vendored)]
pub(crate) fn vendored_cloudflared() -> Option<(&'static [u8], &'static str)> {
    #[derive(rust_embed::RustEmbed)]
    #[folder = "vendored/"]
    #[include = "cloudflared"]
    struct CloudflaredAsset;

    static CACHE: std::sync::OnceLock<Option<(Vec<u8>, String)>> = std::sync::OnceLock::new();
    CACHE
        .get_or_init(|| CloudflaredAsset::get("cloudflared").map(|file| fingerprinted(file.data.into_owned())))
        .as_ref()
        .map(|(bytes, fingerprint)| (bytes.as_slice(), fingerprint.as_str()))
}

#[cfg(not(cloudflared_vendored))]
pub(crate) fn vendored_cloudflared() -> Option<(&'static [u8], &'static str)> {
    None
}

/// Resolve `name` on PATH, if present.
pub(crate) fn which(name: &str) -> Option<PathBuf> {
    let output = std::process::Command::new("which").arg(name).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if path.is_empty() { None } else { Some(PathBuf::from(path)) }
}

pub(crate) fn set_executable(path: &Path) -> Result<(), VendoredBinError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
        .map_err(|e| VendoredBinError(format!("chmod failed: {e}")))
}

/// Write the embedded binary to `<config_dir>/<bin_name>`, re-extracting only if
/// the fingerprint changed. Returns the installed path.
pub(crate) fn extract_embedded(
    config_dir: &Path,
    bin_name: &str,
    bytes: &[u8],
    fingerprint: &str,
) -> Result<PathBuf, VendoredBinError> {
    let local_bin = config_dir.join(bin_name);
    let marker = config_dir.join(format!(".{bin_name}-fingerprint"));
    let _guard = EXTRACT_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    if local_bin.exists()
        && std::fs::read_to_string(&marker).ok().as_deref() == Some(fingerprint)
    {
        return Ok(local_bin);
    }

    std::fs::create_dir_all(config_dir)
        .map_err(|e| VendoredBinError(format!("failed to create config dir: {e}")))?;
    // Write to a temp file and atomically rename, so we never truncate a binary
    // another thread is currently executing (which would fail with ETXTBSY).
    let tmp = config_dir.join(format!("{bin_name}.tmp"));
    std::fs::write(&tmp, bytes)
        .map_err(|e| VendoredBinError(format!("failed to write embedded {bin_name}: {e}")))?;
    set_executable(&tmp)?;
    std::fs::rename(&tmp, &local_bin)
        .map_err(|e| VendoredBinError(format!("failed to install {bin_name} binary: {e}")))?;
    std::fs::write(&marker, fingerprint)
        .map_err(|e| VendoredBinError(format!("failed to write {bin_name} fingerprint: {e}")))?;

    tracing::info!(path = %local_bin.display(), "{bin_name} extracted from embed");
    Ok(local_bin)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_installs_executable_and_reuses_matching_fingerprint() {
        let dir = tempfile::tempdir().expect("tempdir");
        let installed = extract_embedded(dir.path(), "fakebin", b"#!/bin/sh\n", "fp-1").expect("extract");
        assert_eq!(installed, dir.path().join("fakebin"));
        assert_eq!(std::fs::read(&installed).expect("read"), b"#!/bin/sh\n");
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&installed).expect("metadata").permissions().mode();
            assert_eq!(mode & 0o111, 0o111, "installed binary must be executable");
        }

        // Same fingerprint: contents are left alone even if the bytes differ.
        std::fs::write(&installed, b"mutated").expect("mutate");
        let again = extract_embedded(dir.path(), "fakebin", b"#!/bin/sh\n", "fp-1").expect("reuse");
        assert_eq!(std::fs::read(&again).expect("read"), b"mutated");

        // New fingerprint: re-extracts the new bytes.
        let updated = extract_embedded(dir.path(), "fakebin", b"v2", "fp-2").expect("re-extract");
        assert_eq!(std::fs::read(&updated).expect("read"), b"v2");
    }
}
