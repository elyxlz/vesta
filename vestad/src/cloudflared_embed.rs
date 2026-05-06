#[cfg(cloudflared_vendored)]
use rust_embed::RustEmbed;
#[cfg(cloudflared_vendored)]
use std::sync::OnceLock;

#[cfg(cloudflared_vendored)]
#[derive(RustEmbed)]
#[folder = "vendored/"]
#[include = "cloudflared"]
struct CloudflaredAsset;

#[cfg(cloudflared_vendored)]
fn cached() -> Option<&'static (Vec<u8>, String)> {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::Hasher;

    static CACHE: OnceLock<Option<(Vec<u8>, String)>> = OnceLock::new();
    CACHE
        .get_or_init(|| {
            let bytes = CloudflaredAsset::get("cloudflared")?.data.into_owned();
            let mut hasher = DefaultHasher::new();
            hasher.write(env!("CARGO_PKG_VERSION").as_bytes());
            hasher.write(&bytes);
            Some((bytes, format!("{:016x}", hasher.finish())))
        })
        .as_ref()
}

#[cfg(cloudflared_vendored)]
pub(crate) fn vendored_cloudflared() -> Option<(&'static [u8], &'static str)> {
    cached().map(|(bytes, fingerprint)| (bytes.as_slice(), fingerprint.as_str()))
}

#[cfg(not(cloudflared_vendored))]
pub(crate) fn vendored_cloudflared() -> Option<(&'static [u8], &'static str)> {
    None
}
