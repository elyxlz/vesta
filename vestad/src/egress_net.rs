//! The egress feature's outbound network IO: fetch the pinned sing-box release and the pinned
//! static busybox, assemble them plus the init script (`egress::init_script`) into a one-tar
//! sidecar image, and check a proxy before vestad routes an agent through it. No Docker here:
//! `docker::ensure_egress_image` imports the tar.

use std::io::Read;

const SING_BOX_VERSION: &str = "1.14.2";
const SING_BOX_AMD64_SHA256: &str =
    "8f6cb4bcf94d2b33c65d52e0d5b142db29a938336f1ff7267f397ac3758fc297";
const SING_BOX_ARM64_SHA256: &str =
    "675297394f9430cebb72b3c48ba8bce0d6f7c750a9d68a8f7f88c515c8255cd1";
const RELEASE_BASE: &str = "https://github.com/SagerNet/sing-box/releases/download";
/// Hex digits of the image content digest kept in the tag (see `image_tag`).
const IMAGE_DIGEST_LEN: usize = 12;
const IMAGE_REPO: &str = "vesta-egress";
const SING_BOX_FILE: &str = "sing-box";
const SING_BOX_MODE: u32 = 0o755;
const BUSYBOX_MODE: u32 = 0o755;
/// Not executed directly (`/busybox sh /egress-init.sh`), just read.
const EGRESS_INIT_MODE: u32 = 0o644;
const DOWNLOAD_TIMEOUT_SECS: u64 = 300;
const PREFLIGHT_TIMEOUT_SECS: u64 = 15;
/// The host an agent needs most. Any HTTP answer through the proxy proves the whole path.
const PREFLIGHT_URL: &str = "https://api.anthropic.com/";

/// Debian snapshot.debian.org pins a static `busybox` build with `ip`: busybox.net ships no
/// 64-bit ARM static build carrying it. Permanent, content-addressed URLs.
const BUSYBOX_VERSION: &str = "1.37.0-10";
const BUSYBOX_SNAPSHOT: &str = "20260202T142326Z";
const BUSYBOX_BASE: &str = "https://snapshot.debian.org/archive/debian";
const BUSYBOX_AMD64_SHA256: &str =
    "9eac28cbd7732a7c978593cbf2087c301cd4e436b16db57534124b043962578d";
const BUSYBOX_ARM64_SHA256: &str =
    "af29d55c405337447f4434ddff9ceb0bb2419df957d273a84dcae1e781348c81";
/// The busybox binary's path inside the .deb's `data.tar.xz`.
const BUSYBOX_TAR_ENTRY: &str = "./usr/bin/busybox";

#[derive(Debug)]
pub struct EgressNetError(String);

impl std::fmt::Display for EgressNetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for EgressNetError {}

/// The sing-box pin plus a digest of the rest of the image's content (the busybox pin and the
/// generated init script), so any content change is a new tag and `current_sidecar_id` treats
/// a sidecar on the old one as drift.
pub fn image_tag() -> String {
    let content = format!(
        "{BUSYBOX_VERSION}\n{BUSYBOX_SNAPSHOT}\n{}",
        crate::egress::init_script()
    );
    let digest = sha256_hex(content.as_bytes());
    format!(
        "{IMAGE_REPO}:{SING_BOX_VERSION}-{}",
        &digest[..IMAGE_DIGEST_LEN]
    )
}

/// `x86_64` -> Docker/Debian's `amd64`, `aarch64` -> `arm64`. Shared by the sing-box and busybox
/// pins, which both publish under those arch names.
fn docker_arch(target_arch: &str) -> Option<&'static str> {
    match target_arch {
        "x86_64" => Some("amd64"),
        "aarch64" => Some("arm64"),
        _ => None,
    }
}

struct ReleaseAsset {
    dir_name: String,
    sha256: &'static str,
}

fn release_asset(target_arch: &str) -> Option<ReleaseAsset> {
    let arch = docker_arch(target_arch)?;
    let sha256 = match arch {
        "amd64" => SING_BOX_AMD64_SHA256,
        _ => SING_BOX_ARM64_SHA256,
    };
    Some(ReleaseAsset {
        dir_name: format!("sing-box-{SING_BOX_VERSION}-linux-{arch}-musl"),
        sha256,
    })
}

fn busybox_asset(target_arch: &str) -> Option<(String, &'static str)> {
    let arch = docker_arch(target_arch)?;
    let sha256 = match arch {
        "amd64" => BUSYBOX_AMD64_SHA256,
        _ => BUSYBOX_ARM64_SHA256,
    };
    let url = format!(
        "{BUSYBOX_BASE}/{BUSYBOX_SNAPSHOT}/pool/main/b/busybox/busybox-static_{BUSYBOX_VERSION}_{arch}.deb"
    );
    Some((url, sha256))
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
            "download checksum mismatch: expected {expected}, got {actual}"
        )))
    }
}

/// Pull `<dir_name>/sing-box` out of the release tarball.
fn sing_box_binary_from_release(tarball: &[u8], dir_name: &str) -> Result<Vec<u8>, EgressNetError> {
    let fail = |e: std::io::Error| EgressNetError(format!("failed to unpack sing-box: {e}"));
    let wanted = format!("{dir_name}/{SING_BOX_FILE}");
    let mut archive = tar::Archive::new(flate2::read::GzDecoder::new(tarball));
    for entry in archive.entries().map_err(fail)? {
        let mut entry = entry.map_err(fail)?;
        if entry.path().map_err(fail)?.to_str() == Some(wanted.as_str()) {
            let mut data = Vec::new();
            entry.read_to_end(&mut data).map_err(fail)?;
            return Ok(data);
        }
    }
    Err(EgressNetError(format!("{wanted} not found in the release")))
}

/// A member of a `.deb`'s `ar` archive: the global `!<arch>\n` magic, then a run of 60-byte
/// headers (`name[16] mtime[12] uid[6] gid[6] mode[8] size[10] magic[2]`) each followed by its
/// data, padded to even length.
struct ArMember<'a> {
    name: String,
    data: &'a [u8],
}

const AR_MAGIC: &[u8; 8] = b"!<arch>\n";
const AR_HEADER_LEN: usize = 60;
const AR_MEMBER_MAGIC: &[u8; 2] = b"`\n";

fn parse_ar(bytes: &[u8]) -> Result<Vec<ArMember<'_>>, EgressNetError> {
    let fail = |msg: &str| EgressNetError(format!("invalid ar archive: {msg}"));
    let mut body = bytes
        .strip_prefix(AR_MAGIC)
        .ok_or_else(|| fail("bad magic"))?;
    let mut members = Vec::new();
    while !body.is_empty() {
        if body.len() < AR_HEADER_LEN {
            return Err(fail("truncated member header"));
        }
        let (header, rest) = body.split_at(AR_HEADER_LEN);
        if &header[58..60] != AR_MEMBER_MAGIC {
            return Err(fail("bad member magic"));
        }
        let name = std::str::from_utf8(&header[0..16])
            .map_err(|_| fail("non-utf8 name"))?
            .trim_end()
            .trim_end_matches('/')
            .to_string();
        let size: usize = std::str::from_utf8(&header[48..58])
            .map_err(|_| fail("non-utf8 size"))?
            .trim_end()
            .parse()
            .map_err(|_| fail("non-numeric size"))?;
        if rest.len() < size {
            return Err(fail("truncated member data"));
        }
        let (data, rest) = rest.split_at(size);
        members.push(ArMember { name, data });
        // Members are padded to an even length; an odd-sized one has one pad byte to skip.
        body = if size % 2 == 1 && !rest.is_empty() {
            &rest[1..]
        } else {
            rest
        };
    }
    Ok(members)
}

/// The busybox binary out of a `busybox-static_*.deb`: its `ar` member `data.tar.xz` holds the
/// filesystem, and the binary lives at `BUSYBOX_TAR_ENTRY` inside that xz-compressed tar.
fn extract_busybox_from_deb(deb: &[u8]) -> Result<Vec<u8>, EgressNetError> {
    let fail = |e: std::io::Error| EgressNetError(format!("failed to unpack busybox: {e}"));
    let members = parse_ar(deb)?;
    let data_tar_xz = members
        .iter()
        .find(|member| member.name == "data.tar.xz")
        .ok_or_else(|| EgressNetError("data.tar.xz not found in the busybox .deb".to_string()))?
        .data;
    let mut tar_bytes = Vec::new();
    lzma_rs::xz_decompress(&mut std::io::BufReader::new(data_tar_xz), &mut tar_bytes)
        .map_err(|e| EgressNetError(format!("failed to decompress busybox data.tar.xz: {e}")))?;
    let mut archive = tar::Archive::new(tar_bytes.as_slice());
    for entry in archive.entries().map_err(fail)? {
        let mut entry = entry.map_err(fail)?;
        if entry.path().map_err(fail)?.to_str() == Some(BUSYBOX_TAR_ENTRY) {
            let mut data = Vec::new();
            entry.read_to_end(&mut data).map_err(fail)?;
            return Ok(data);
        }
    }
    Err(EgressNetError(format!(
        "{BUSYBOX_TAR_ENTRY} not found in the busybox .deb"
    )))
}

/// Download a pinned asset and check it against its pinned checksum.
async fn download_verified(
    http: &reqwest::Client,
    url: &str,
    sha256: &str,
) -> Result<bytes::Bytes, EgressNetError> {
    let fail = |e: reqwest::Error| EgressNetError(format!("failed to download {url}: {e}"));
    let body = http
        .get(url)
        .timeout(std::time::Duration::from_secs(DOWNLOAD_TIMEOUT_SECS))
        .send()
        .await
        .map_err(fail)?
        .error_for_status()
        .map_err(fail)?
        .bytes()
        .await
        .map_err(fail)?;
    verify_sha256(&body, sha256)?;
    Ok(body)
}

async fn fetch_sing_box(http: &reqwest::Client) -> Result<Vec<u8>, EgressNetError> {
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
    let tarball = download_verified(http, &url, asset.sha256).await?;
    tokio::task::spawn_blocking(move || sing_box_binary_from_release(&tarball, &asset.dir_name))
        .await
        .map_err(|e| EgressNetError(format!("sing-box unpack task failed: {e}")))?
}

async fn fetch_busybox(http: &reqwest::Client) -> Result<Vec<u8>, EgressNetError> {
    let (url, sha256) = busybox_asset(std::env::consts::ARCH).ok_or_else(|| {
        EgressNetError(format!(
            "no pinned busybox build for {}",
            std::env::consts::ARCH
        ))
    })?;
    let deb = download_verified(http, &url, sha256).await?;
    tokio::task::spawn_blocking(move || extract_busybox_from_deb(&deb))
        .await
        .map_err(|e| EgressNetError(format!("busybox unpack task failed: {e}")))?
}

/// The image-internal path (`crate::egress::*_IN_IMAGE`) as the flat tar entry name
/// `docker import` places at the image root.
fn image_entry_name(absolute_path: &str) -> &str {
    absolute_path.trim_start_matches('/')
}

fn append_tar_entry(
    builder: &mut tar::Builder<Vec<u8>>,
    name: &str,
    mode: u32,
    data: &[u8],
) -> Result<(), EgressNetError> {
    let fail = |e: std::io::Error| EgressNetError(format!("failed to pack {name}: {e}"));
    let mut header = tar::Header::new_gnu();
    header.set_size(u64::try_from(data.len()).map_err(|e| EgressNetError(e.to_string()))?);
    header.set_mode(mode);
    header.set_cksum();
    builder.append_data(&mut header, name, data).map_err(fail)
}

/// Pack the sidecar's three assets into the flat tar `docker import` turns into its image:
/// `sing-box`, `busybox`, and the generated init script, each at the path its own const names.
fn assemble_image_tar(
    sing_box: &[u8],
    busybox: &[u8],
    init_script: &str,
) -> Result<Vec<u8>, EgressNetError> {
    let mut builder = tar::Builder::new(Vec::new());
    append_tar_entry(
        &mut builder,
        image_entry_name(crate::egress::SING_BOX_IN_IMAGE),
        SING_BOX_MODE,
        sing_box,
    )?;
    append_tar_entry(
        &mut builder,
        image_entry_name(crate::egress::BUSYBOX_IN_IMAGE),
        BUSYBOX_MODE,
        busybox,
    )?;
    append_tar_entry(
        &mut builder,
        image_entry_name(crate::egress::EGRESS_INIT_IN_IMAGE),
        EGRESS_INIT_MODE,
        init_script.as_bytes(),
    )?;
    builder
        .into_inner()
        .map_err(|e| EgressNetError(format!("failed to build image tar: {e}")))
}

pub async fn fetch_image_tar(http: &reqwest::Client) -> Result<Vec<u8>, EgressNetError> {
    let (sing_box, busybox) = tokio::try_join!(fetch_sing_box(http), fetch_busybox(http))?;
    let init_script = crate::egress::init_script();
    tokio::task::spawn_blocking(move || assemble_image_tar(&sing_box, &busybox, &init_script))
        .await
        .map_err(|e| EgressNetError(format!("image assembly task failed: {e}")))?
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
    fn image_tag_names_the_pinned_version_and_a_content_digest() {
        let tag = image_tag();
        let digest = tag
            .strip_prefix("vesta-egress:1.14.2-")
            .expect("repo and sing-box pin");
        assert_eq!(digest.len(), IMAGE_DIGEST_LEN, "{tag}");
        assert!(digest.chars().all(|c| c.is_ascii_hexdigit()), "{tag}");
        assert_eq!(image_tag(), tag, "the tag is stable across calls");
    }

    #[test]
    fn busybox_asset_maps_supported_arches() {
        let (url, sha256) = busybox_asset("x86_64").expect("amd64");
        assert!(url.ends_with("busybox-static_1.37.0-10_amd64.deb"), "{url}");
        assert_eq!(sha256, BUSYBOX_AMD64_SHA256);
        let (url, sha256) = busybox_asset("aarch64").expect("arm64");
        assert!(url.ends_with("busybox-static_1.37.0-10_arm64.deb"), "{url}");
        assert_eq!(sha256, BUSYBOX_ARM64_SHA256);
        assert!(busybox_asset("riscv64").is_none());
    }

    #[test]
    fn verify_rejects_a_wrong_checksum() {
        assert!(verify_sha256(b"payload", &sha256_hex(b"payload")).is_ok());
        assert!(verify_sha256(b"payload", &sha256_hex(b"other")).is_err());
    }

    #[test]
    fn sing_box_binary_from_release_extracts_only_the_binary() {
        let tarball = fixture_tarball("sing-box-1.14.2-linux-amd64-musl", b"ELF-binary");
        let binary = sing_box_binary_from_release(&tarball, "sing-box-1.14.2-linux-amd64-musl")
            .expect("unpack");
        assert_eq!(binary, b"ELF-binary");
    }

    #[test]
    fn sing_box_binary_from_release_fails_when_the_binary_is_missing() {
        let tarball = fixture_tarball("some-other-dir", b"ELF-binary");
        assert!(
            sing_box_binary_from_release(&tarball, "sing-box-1.14.2-linux-amd64-musl").is_err()
        );
    }

    /// A 60-byte ar member header: only `name` and `size` matter to `parse_ar`, so the rest of
    /// the fixed-width fields are left blank.
    fn ar_header(name: &str, size: usize) -> [u8; AR_HEADER_LEN] {
        let mut header = [b' '; AR_HEADER_LEN];
        header[..name.len()].copy_from_slice(name.as_bytes());
        let size_str = size.to_string();
        header[48..48 + size_str.len()].copy_from_slice(size_str.as_bytes());
        header[58..60].copy_from_slice(AR_MEMBER_MAGIC);
        header
    }

    fn build_fixture_ar(members: &[(&str, &[u8])]) -> Vec<u8> {
        let mut bytes = AR_MAGIC.to_vec();
        for (name, data) in members {
            bytes.extend_from_slice(&ar_header(name, data.len()));
            bytes.extend_from_slice(data);
            if data.len() % 2 == 1 {
                bytes.push(b'\n');
            }
        }
        bytes
    }

    #[test]
    fn parse_ar_reads_two_members_and_skips_odd_size_padding() {
        let archive = build_fixture_ar(&[("debian-binary", b"2.0\n"), ("data.tar.xz", b"odd")]);
        let members = parse_ar(&archive).expect("parse");
        assert_eq!(members.len(), 2);
        assert_eq!(members[0].name, "debian-binary");
        assert_eq!(members[0].data, b"2.0\n");
        assert_eq!(members[1].name, "data.tar.xz");
        assert_eq!(members[1].data, b"odd");
    }

    #[test]
    fn parse_ar_rejects_a_bad_magic() {
        assert!(parse_ar(b"not an ar archive at all").is_err());
    }

    /// `tar::Builder::append_data` strips a leading `./` from the given path (`Header::set_path`
    /// treats `.` components as no-ops), but a real `dpkg-deb` tar stores entries exactly as
    /// `./usr/bin/busybox`. Writing the name bytes directly and using the raw `append` preserves
    /// it, matching what `extract_busybox_from_deb` actually reads off a real `.deb`.
    fn fixture_tar(entries: &[(&str, &[u8])]) -> Vec<u8> {
        let mut builder = tar::Builder::new(Vec::new());
        for (path, data) in entries {
            let mut header = tar::Header::new_gnu();
            header.set_size(data.len() as u64);
            header.set_mode(0o755);
            header.as_old_mut().name[..path.len()].copy_from_slice(path.as_bytes());
            header.set_cksum();
            builder.append(&header, *data).expect("append");
        }
        builder.into_inner().expect("finish tar")
    }

    fn xz_compress(data: &[u8]) -> Vec<u8> {
        let mut out = Vec::new();
        lzma_rs::xz_compress(&mut std::io::Cursor::new(data), &mut out).expect("xz compress");
        out
    }

    #[test]
    fn extract_busybox_from_deb_pulls_the_binary_out_of_data_tar_xz() {
        let tar_bytes = fixture_tar(&[("./usr/bin/busybox", b"BUSYBOX-BIN")]);
        let deb = build_fixture_ar(&[
            ("debian-binary", b"2.0\n"),
            ("control.tar.xz", b"unused"),
            ("data.tar.xz", &xz_compress(&tar_bytes)),
        ]);
        assert_eq!(
            extract_busybox_from_deb(&deb).expect("extract"),
            b"BUSYBOX-BIN"
        );
    }

    #[test]
    fn extract_busybox_from_deb_fails_when_data_tar_xz_is_missing() {
        let deb = build_fixture_ar(&[("debian-binary", b"2.0\n")]);
        assert!(extract_busybox_from_deb(&deb).is_err());
    }

    #[test]
    fn assemble_image_tar_holds_exactly_the_three_assets_at_their_named_paths() {
        let image =
            assemble_image_tar(b"SING-BOX-BIN", b"BUSYBOX-BIN", "set -e\n").expect("assemble");
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
            vec![
                ("sing-box".to_string(), 0o755, b"SING-BOX-BIN".to_vec()),
                ("busybox".to_string(), 0o755, b"BUSYBOX-BIN".to_vec()),
                ("egress-init.sh".to_string(), 0o644, b"set -e\n".to_vec()),
            ]
        );
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
