#[cfg(restic_vendored)]
use rust_embed::RustEmbed;
#[cfg(restic_vendored)]
use std::sync::OnceLock;

#[cfg(restic_vendored)]
#[derive(RustEmbed)]
#[folder = "vendored/"]
#[include = "restic"]
struct ResticAsset;

#[cfg(restic_vendored)]
fn cached() -> Option<&'static (Vec<u8>, String)> {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::Hasher;

    static CACHE: OnceLock<Option<(Vec<u8>, String)>> = OnceLock::new();
    CACHE
        .get_or_init(|| {
            let bytes = ResticAsset::get("restic")?.data.into_owned();
            let mut hasher = DefaultHasher::new();
            hasher.write(env!("CARGO_PKG_VERSION").as_bytes());
            hasher.write(&bytes);
            Some((bytes, format!("{:016x}", hasher.finish())))
        })
        .as_ref()
}

#[cfg(restic_vendored)]
pub(crate) fn vendored_restic() -> Option<(&'static [u8], &'static str)> {
    cached().map(|(bytes, fingerprint)| (bytes.as_slice(), fingerprint.as_str()))
}

#[cfg(not(restic_vendored))]
pub(crate) fn vendored_restic() -> Option<(&'static [u8], &'static str)> {
    None
}
