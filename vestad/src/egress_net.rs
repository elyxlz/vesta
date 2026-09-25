//! The egress feature's outbound network IO: fetch the pinned sing-box release as a one-file
//! image tar, and check a proxy before vestad routes an agent through it. No Docker here:
//! `docker::ensure_egress_image` imports the tar.

use std::io::Read;

const SING_BOX_VERSION: &str = "1.14.2";
const SING_BOX_AMD64_SHA256: &str =
    "8f6cb4bcf94d2b33c65d52e0d5b142db29a938336f1ff7267f397ac3758fc297";
const SING_BOX_ARM64_SHA256: &str =
    "675297394f9430cebb72b3c48ba8bce0d6f7c750a9d68a8f7f88c515c8255cd1";
const RELEASE_BASE: &str = "https://github.com/SagerNet/sing-box/releases/download";
const IMAGE_REPO: &str = "vesta-egress";
const BINARY_FILE: &str = "sing-box";
const BINARY_MODE: u32 = 0o755;
pub const BINARY_IN_IMAGE: &str = "/sing-box";
const DOWNLOAD_TIMEOUT_SECS: u64 = 300;
const PREFLIGHT_TIMEOUT_SECS: u64 = 15;
/// The host an agent needs most. Any HTTP answer through the proxy proves the whole path.
const PREFLIGHT_URL: &str = "https://api.anthropic.com/";

#[derive(Debug)]
pub struct EgressNetError(String);

impl std::fmt::Display for EgressNetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for EgressNetError {}

pub fn image_tag() -> String {
    format!("{IMAGE_REPO}:{SING_BOX_VERSION}")
}

struct ReleaseAsset {
    dir_name: String,
    sha256: &'static str,
}

fn release_asset(target_arch: &str) -> Option<ReleaseAsset> {
    let (arch, sha256) = match target_arch {
        "x86_64" => ("amd64", SING_BOX_AMD64_SHA256),
        "aarch64" => ("arm64", SING_BOX_ARM64_SHA256),
        _ => return None,
    };
    Some(ReleaseAsset {
        dir_name: format!("sing-box-{SING_BOX_VERSION}-linux-{arch}-musl"),
        sha256,
    })
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(ring::digest::digest(&ring::digest::SHA256, bytes))
}

fn verify_sha256(bytes: &[u8], expected: &str) -> Result<(), EgressNetError> {
    let actual = sha256_hex(bytes);
    if actual == expected {
        Ok(())
    } else {
        Err(EgressNetError(format!(
            "sing-box download checksum mismatch: expected {expected}, got {actual}"
        )))
    }
}

/// Pull `<dir_name>/sing-box` out of the release tarball and pack it alone at the root of a
/// flat tar, the input `docker import` turns into the sidecar image.
fn image_tar_from_release(tarball: &[u8], dir_name: &str) -> Result<Vec<u8>, EgressNetError> {
    let fail = |e: std::io::Error| EgressNetError(format!("failed to unpack sing-box: {e}"));
    let wanted = format!("{dir_name}/{BINARY_FILE}");
    let mut archive = tar::Archive::new(flate2::read::GzDecoder::new(tarball));
    let mut binary = None;
    for entry in archive.entries().map_err(fail)? {
        let mut entry = entry.map_err(fail)?;
        if entry.path().map_err(fail)?.to_str() == Some(wanted.as_str()) {
            let mut data = Vec::new();
            entry.read_to_end(&mut data).map_err(fail)?;
            binary = Some(data);
            break;
        }
    }
    let binary =
        binary.ok_or_else(|| EgressNetError(format!("{wanted} not found in the release")))?;

    let mut builder = tar::Builder::new(Vec::new());
    let mut header = tar::Header::new_gnu();
    header.set_size(u64::try_from(binary.len()).map_err(|e| EgressNetError(e.to_string()))?);
    header.set_mode(BINARY_MODE);
    header.set_cksum();
    builder
        .append_data(&mut header, BINARY_FILE, binary.as_slice())
        .map_err(fail)?;
    builder.into_inner().map_err(fail)
}

pub async fn fetch_image_tar(http: &reqwest::Client) -> Result<Vec<u8>, EgressNetError> {
    let asset = release_asset(std::env::consts::ARCH).ok_or_else(|| {
        EgressNetError(format!(
            "no pinned sing-box build for {}",
            std::env::consts::ARCH
        ))
    })?;
    let url = format!(
        "{RELEASE_BASE}/v{SING_BOX_VERSION}/{}.tar.gz",
        asset.dir_name
    );
    let fail = |e: reqwest::Error| EgressNetError(format!("failed to download {url}: {e}"));
    let tarball = http
        .get(&url)
        .timeout(std::time::Duration::from_secs(DOWNLOAD_TIMEOUT_SECS))
        .send()
        .await
        .map_err(fail)?
        .error_for_status()
        .map_err(fail)?
        .bytes()
        .await
        .map_err(fail)?;
    verify_sha256(&tarball, asset.sha256)?;
    tokio::task::spawn_blocking(move || image_tar_from_release(&tarball, &asset.dir_name))
        .await
        .map_err(|e| EgressNetError(format!("sing-box unpack task failed: {e}")))?
}

/// One HTTPS request through the proxy. The error names only the failure class, because
/// reqwest's own text can carry the proxy URL and its password.
pub async fn preflight(proxy: &crate::egress::ProxyUrl) -> Result<(), EgressNetError> {
    let build_fail = |_: reqwest::Error| EgressNetError("the proxy url is not usable".to_string());
    let client = reqwest::Client::builder()
        .proxy(reqwest::Proxy::all(proxy.raw()).map_err(build_fail)?)
        .timeout(std::time::Duration::from_secs(PREFLIGHT_TIMEOUT_SECS))
        .build()
        .map_err(build_fail)?;
    match client.head(PREFLIGHT_URL).send().await {
        Ok(_) => Ok(()),
        Err(e) => {
            let class = if e.is_timeout() {
                "timed out"
            } else if e.is_connect() {
                "could not connect or authenticate"
            } else {
                "failed"
            };
            Err(EgressNetError(format!(
                "proxy check {class}: {PREFLIGHT_URL} was not reachable through {}",
                proxy.masked()
            )))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_tarball(dir_name: &str, binary: &[u8]) -> Vec<u8> {
        let encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
        let mut builder = tar::Builder::new(encoder);
        for (path, data) in [
            (format!("{dir_name}/LICENSE"), b"license".as_slice()),
            (format!("{dir_name}/sing-box"), binary),
        ] {
            let mut header = tar::Header::new_gnu();
            header.set_size(data.len() as u64);
            header.set_mode(0o755);
            header.set_cksum();
            builder
                .append_data(&mut header, path, data)
                .expect("append");
        }
        builder
            .into_inner()
            .expect("finish tar")
            .finish()
            .expect("finish gzip")
    }

    #[test]
    fn release_asset_maps_supported_arches() {
        assert_eq!(
            release_asset("x86_64").map(|asset| asset.dir_name),
            Some("sing-box-1.14.2-linux-amd64-musl".to_string())
        );
        assert_eq!(
            release_asset("aarch64").map(|asset| asset.sha256),
            Some(SING_BOX_ARM64_SHA256)
        );
        assert!(release_asset("riscv64").is_none());
    }

    #[test]
    fn image_tag_names_the_pinned_version() {
        assert_eq!(image_tag(), "vesta-egress:1.14.2");
    }

    #[test]
    fn verify_rejects_a_wrong_checksum() {
        assert!(verify_sha256(b"payload", &sha256_hex(b"payload")).is_ok());
        assert!(verify_sha256(b"payload", &sha256_hex(b"other")).is_err());
    }

    #[test]
    fn image_tar_holds_only_the_executable_binary() {
        let tarball = fixture_tarball("sing-box-1.14.2-linux-amd64-musl", b"ELF-binary");
        let image =
            image_tar_from_release(&tarball, "sing-box-1.14.2-linux-amd64-musl").expect("pack");
        let mut archive = tar::Archive::new(image.as_slice());
        let entries: Vec<(String, u32, Vec<u8>)> = archive
            .entries()
            .expect("entries")
            .map(|entry| {
                let mut entry = entry.expect("entry");
                let path = entry.path().expect("path").display().to_string();
                let mode = entry.header().mode().expect("mode");
                let mut data = Vec::new();
                std::io::Read::read_to_end(&mut entry, &mut data).expect("read");
                (path, mode, data)
            })
            .collect();
        assert_eq!(
            entries,
            vec![("sing-box".to_string(), 0o755, b"ELF-binary".to_vec())]
        );
    }

    #[test]
    fn image_tar_fails_when_the_binary_is_missing() {
        let tarball = fixture_tarball("some-other-dir", b"ELF-binary");
        assert!(image_tar_from_release(&tarball, "sing-box-1.14.2-linux-amd64-musl").is_err());
    }

    #[tokio::test]
    async fn preflight_fails_fast_for_a_dead_proxy() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        drop(listener);
        let proxy = crate::egress::ProxyUrl::parse(&format!("socks5://u:secret@127.0.0.1:{port}"))
            .expect("parse");
        let error = preflight(&proxy).await.expect_err("dead proxy must fail");
        assert!(
            !error.to_string().contains("secret"),
            "error must not leak the password: {error}"
        );
    }
}
