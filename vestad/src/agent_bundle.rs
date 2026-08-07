//! Portable agent export/import bundle format: a gzipped tar carrying a JSON
//! manifest, the agent's constitution, and a `docker save` image tar, in that
//! fixed entry order. `write_bundle` produces one, `sniff_bundle` tells a
//! bundle apart from a legacy plain-image export without fully parsing it,
//! `open_bundle` reads the small head (manifest + constitution), and
//! `read_bundle_image` streams the trailing image entry into a caller sink.

use crate::docker::DockerError;
use bollard::Docker;
use std::io::Read;
use std::path::{Path, PathBuf};

pub(crate) const BUNDLE_FORMAT_VERSION: u32 = 1;
pub(crate) const MANIFEST_ENTRY: &str = "vesta-manifest.json";
pub(crate) const CONSTITUTION_ENTRY: &str = "constitution.md";
pub(crate) const IMAGE_ENTRY: &str = "image.tar";

const IMAGE_CHUNK_BYTES: usize = 64 * 1024;

const CORRUPT_BUNDLE_MESSAGE: &str = "bundle is corrupt or was modified";
const NOT_A_BUNDLE_MESSAGE: &str = "not a vesta export file";

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub(crate) struct BundleManifest {
    pub format_version: u32,
    pub agent_name: String,
    pub vestad_version: String,
    pub created_at: String,
    pub user_desired: crate::settings::UserDesired,
    pub mounts: Vec<crate::mounts::HostMount>,
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub(crate) enum BundleKind {
    Bundle,
    Legacy,
}

fn docker_failed(context: &str, err: impl std::fmt::Display) -> DockerError {
    DockerError::Failed(format!("{context}: {err}"))
}

/// A GNU tar header for an entry of `size` bytes, world-readable and checksummed.
fn gnu_header(size: u64) -> tar::Header {
    let mut header = tar::Header::new_gnu();
    header.set_size(size);
    header.set_mode(0o644);
    header.set_cksum();
    header
}

/// Appends one entry (a GNU tar header plus its bytes) to the bundle being built.
fn append_entry<W: std::io::Write>(builder: &mut tar::Builder<W>, name: &str, data: &[u8]) -> Result<(), DockerError> {
    let mut header = gnu_header(data.len() as u64);
    builder
        .append_data(&mut header, name, data)
        .map_err(|err| DockerError::Failed(format!("appending {name} entry: {err}")))
}

fn write_bundle_inner(output: &Path, manifest: &BundleManifest, constitution: &str, image_tar: &Path) -> Result<(), DockerError> {
    let file = std::fs::File::create(output).map_err(|err| docker_failed("creating bundle file", err))?;
    let encoder = flate2::write::GzEncoder::new(file, flate2::Compression::default());
    let mut builder = tar::Builder::new(encoder);

    let manifest_bytes = serde_json::to_vec(manifest).map_err(|err| docker_failed("encoding bundle manifest", err))?;
    append_entry(&mut builder, MANIFEST_ENTRY, &manifest_bytes)?;
    append_entry(&mut builder, CONSTITUTION_ENTRY, constitution.as_bytes())?;

    let image_size = std::fs::metadata(image_tar)
        .map_err(|err| docker_failed("reading image tar metadata", err))?
        .len();
    let mut image_file = std::fs::File::open(image_tar).map_err(|err| docker_failed("opening image tar", err))?;
    let mut header = gnu_header(image_size);
    builder
        .append_data(&mut header, IMAGE_ENTRY, &mut image_file)
        .map_err(|err| docker_failed("appending image tar entry", err))?;

    let encoder = builder.into_inner().map_err(|err| docker_failed("finishing bundle tar", err))?;
    encoder.finish().map_err(|err| docker_failed("finishing bundle gzip", err))?;
    Ok(())
}

pub(crate) fn write_bundle(output: &Path, manifest: &BundleManifest, constitution: &str, image_tar: &Path) -> Result<(), DockerError> {
    match write_bundle_inner(output, manifest, constitution, image_tar) {
        Ok(()) => Ok(()),
        Err(err) => {
            std::fs::remove_file(output).ok();
            Err(err)
        }
    }
}

pub(crate) fn sniff_bundle(path: &Path) -> Result<BundleKind, DockerError> {
    let file = std::fs::File::open(path).map_err(|err| docker_failed(NOT_A_BUNDLE_MESSAGE, err))?;
    let decoder = flate2::read::GzDecoder::new(file);
    let mut archive = tar::Archive::new(decoder);
    let mut entries = archive.entries().map_err(|err| docker_failed(NOT_A_BUNDLE_MESSAGE, err))?;
    let first = entries
        .next()
        .ok_or_else(|| DockerError::Failed(NOT_A_BUNDLE_MESSAGE.to_string()))?
        .map_err(|err| docker_failed(NOT_A_BUNDLE_MESSAGE, err))?;
    let entry_path = first.path().map_err(|err| docker_failed(NOT_A_BUNDLE_MESSAGE, err))?;
    if entry_path.as_ref() == Path::new(MANIFEST_ENTRY) {
        Ok(BundleKind::Bundle)
    } else {
        Ok(BundleKind::Legacy)
    }
}

/// Reads the next tar entry, checks its name matches `expected_name`, and returns its bytes.
fn read_named_entry<R: std::io::Read>(entries: &mut tar::Entries<'_, R>, expected_name: &str) -> Result<Vec<u8>, DockerError> {
    let mut entry = entries
        .next()
        .ok_or_else(|| DockerError::Failed(CORRUPT_BUNDLE_MESSAGE.to_string()))?
        .map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    let entry_path = entry.path().map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    if entry_path.as_ref() != Path::new(expected_name) {
        return Err(DockerError::Failed(CORRUPT_BUNDLE_MESSAGE.to_string()));
    }
    let mut data = Vec::new();
    entry.read_to_end(&mut data).map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    Ok(data)
}

pub(crate) fn open_bundle(path: &Path) -> Result<(BundleManifest, String), DockerError> {
    let file = std::fs::File::open(path).map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    let decoder = flate2::read::GzDecoder::new(file);
    let mut archive = tar::Archive::new(decoder);
    let mut entries = archive.entries().map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;

    let manifest_bytes = read_named_entry(&mut entries, MANIFEST_ENTRY)?;
    let manifest: BundleManifest =
        serde_json::from_slice(&manifest_bytes).map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    if manifest.format_version > BUNDLE_FORMAT_VERSION {
        return Err(DockerError::Failed(format!(
            "bundle format v{} is newer than this vestad supports; update vestad",
            manifest.format_version
        )));
    }

    let constitution_bytes = read_named_entry(&mut entries, CONSTITUTION_ENTRY)?;
    let constitution = String::from_utf8(constitution_bytes).map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;

    Ok((manifest, constitution))
}

pub(crate) fn read_bundle_image<F: FnMut(&[u8]) -> Result<(), DockerError>>(path: &Path, mut sink: F) -> Result<(), DockerError> {
    let file = std::fs::File::open(path).map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    let decoder = flate2::read::GzDecoder::new(file);
    let mut archive = tar::Archive::new(decoder);
    let mut entries = archive.entries().map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;

    read_named_entry(&mut entries, MANIFEST_ENTRY)?;
    read_named_entry(&mut entries, CONSTITUTION_ENTRY)?;

    let mut entry = entries
        .next()
        .ok_or_else(|| DockerError::Failed(CORRUPT_BUNDLE_MESSAGE.to_string()))?
        .map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    let entry_path = entry.path().map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
    if entry_path.as_ref() != Path::new(IMAGE_ENTRY) {
        return Err(DockerError::Failed(CORRUPT_BUNDLE_MESSAGE.to_string()));
    }
    drop(entry_path);

    let mut buffer = vec![0u8; IMAGE_CHUNK_BYTES];
    loop {
        let bytes_read = entry.read(&mut buffer).map_err(|err| docker_failed(CORRUPT_BUNDLE_MESSAGE, err))?;
        if bytes_read == 0 {
            break;
        }
        sink(&buffer[..bytes_read])?;
    }
    Ok(())
}

pub const SCRUB_TIMEOUT_SECS: u64 = 300;

/// The one pinned invocation of core's credential wipe. cwd /root/agent puts the core package
/// (bind-mounted at /root/agent/core) on sys.path; the venv is baked into the image.
pub fn scrub_cmd() -> Vec<String> {
    vec![
        "sh".into(),
        "-c".into(),
        "cd /root/agent && .venv/bin/python -c 'from core.provider import clear_provider; clear_provider()'".into(),
    ]
}

/// Scrub credentials from `source_image` by running core's `clear_provider` (via `scrub_cmd`) in a
/// throwaway container, then committing the result to `vesta-export-{agent_name}:scrubbed`.
/// `core_dir` is bind-mounted read-only at `docker::CORE_MOUNT_DEST` so the invocation reaches the
/// same core package the agent runs. Any leftover same-named container/image from a crashed prior
/// run is removed first (mirrors `backup.rs::remove_temp_artifacts`).
pub async fn scrub_image(
    docker: &Docker,
    agent_name: &str,
    source_image: &str,
    core_dir: &Path,
) -> Result<String, DockerError> {
    let cname = format!("vesta-export-scrub-{agent_name}");
    let image_repo = format!("vesta-export-{agent_name}");
    let output_image = format!("{image_repo}:scrubbed");

    crate::docker::remove_container_force(docker, &cname).await.ok();
    crate::docker::remove_image(docker, &output_image).await.ok();

    let core_bind = format!("{}:{}:ro", core_dir.display(), crate::docker::CORE_MOUNT_DEST);
    let exit_code = crate::docker::run_oneshot_container(
        docker,
        crate::docker::OneshotSpec {
            image: source_image,
            cname: &cname,
            cmd: scrub_cmd(),
            ro_binds: vec![core_bind],
        },
        SCRUB_TIMEOUT_SECS,
    )
    .await?;

    if exit_code != 0 {
        // Leave the container in place: the error advises `docker logs {cname}`, and the next
        // scrub_image call's leftover sweep above reclaims it.
        return Err(DockerError::Failed(format!(
            "credential scrub failed (exit {exit_code}); see docker logs {cname}"
        )));
    }

    let commit_result = crate::docker::commit_container_to_image(docker, &cname, &image_repo, "scrubbed").await;
    crate::docker::remove_container_force(docker, &cname).await.ok();
    commit_result?;

    Ok(output_image)
}

/// Everything `export_agent` needs to build one bundle. `core_dir` is the host directory
/// bind-mounted read-only into the scrub container at `docker::CORE_MOUNT_DEST`; `constitution`
/// and `mounts` are read by the caller from the agent's own settings and constitution file.
pub struct ExportRequest<'a> {
    pub name: &'a str,
    pub output: &'a Path,
    pub core_dir: &'a Path,
    pub constitution: String,
    pub user_desired: crate::settings::UserDesired,
    pub mounts: Vec<crate::mounts::HostMount>,
}

const IMAGE_SPOOL_SUFFIX: &str = ".image-partial";

/// The uncompressed image tar spooled next to `output` while a bundle is assembled, so the
/// final rename-free write via `write_bundle` reads from the same filesystem it writes to.
fn spool_path_for(output: &Path) -> PathBuf {
    let mut spool = output.as_os_str().to_os_string();
    spool.push(IMAGE_SPOOL_SUFFIX);
    PathBuf::from(spool)
}

fn build_manifest(
    name: &str,
    user_desired: crate::settings::UserDesired,
    mounts: Vec<crate::mounts::HostMount>,
    now_rfc3339: String,
) -> BundleManifest {
    BundleManifest {
        format_version: BUNDLE_FORMAT_VERSION,
        agent_name: name.to_string(),
        vestad_version: env!("CARGO_PKG_VERSION").to_string(),
        created_at: now_rfc3339,
        user_desired,
        mounts,
    }
}

/// Steps 5-9 of the export flow: scrub the snapshot, build the manifest, spool the scrubbed
/// image, and package the bundle. Runs after the source container (if it was running) is
/// already back up, so every failure here cleans up its own litter (spool file, scrubbed
/// image) and leaves the source untouched; `write_bundle` removes a partial `output` itself.
async fn export_from_snapshot(docker: &Docker, request: ExportRequest<'_>, snapshot_tag: &str) -> Result<(), DockerError> {
    eprintln!("scrubbing credentials...");
    let scrub_result = scrub_image(docker, request.name, snapshot_tag, request.core_dir).await;
    crate::docker::remove_image(docker, snapshot_tag).await.ok();
    let scrubbed_tag = scrub_result?;

    let now_rfc3339 = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|err| docker_failed("formatting export timestamp", err))?;
    let manifest = build_manifest(request.name, request.user_desired, request.mounts, now_rfc3339);

    let spool_path = spool_path_for(request.output);
    eprintln!("saving image...");
    let save_result = crate::docker::save_image_to_file(docker, &scrubbed_tag, &spool_path).await;
    let bundle_result = match save_result {
        Ok(()) => {
            eprintln!("packaging bundle...");
            write_bundle(request.output, &manifest, &request.constitution, &spool_path)
        }
        Err(err) => Err(err),
    };

    std::fs::remove_file(&spool_path).ok();
    crate::docker::remove_image(docker, &scrubbed_tag).await.ok();
    bundle_result
}

/// Export `request.name` to a portable bundle at `request.output`: stop the agent if running,
/// snapshot its filesystem, restart it, then scrub and package the copy. Progress lines go to
/// stderr, matching the prior `vestad backup export` UX. The source agent is back up (or was
/// never stopped) before any of the copy-only work in `export_from_snapshot` runs.
pub async fn export_agent(docker: &Docker, request: ExportRequest<'_>) -> Result<(), DockerError> {
    crate::docker::validate_name(request.name)?;
    let cname = crate::docker::container_name(request.name);
    let status = crate::docker::container_status(docker, &cname).await;
    if status == crate::docker::ContainerStatus::NotFound {
        return Err(DockerError::Failed(format!("agent '{}' not found", request.name)));
    }

    let was_running = status == crate::docker::ContainerStatus::Running;
    if was_running {
        eprintln!("stopping agent...");
        crate::docker::handoff_shutdown_reason(docker, request.name, &cname, &crate::lifecycle::BACKUP_EXPORT).await;
        crate::docker::stop_container_with_timeout(docker, &cname, crate::backup::BACKUP_STOP_TIMEOUT_SECS).await?;
    }

    eprintln!("snapshotting container...");
    let snapshot_tag = format!("vesta-export-{}:snapshot", request.name);
    if let Err(err) = crate::docker::snapshot_container(docker, &cname, &snapshot_tag, &[]).await {
        if was_running {
            crate::docker::handoff_boot_reason(docker, request.name, &cname, &crate::lifecycle::BACKUP_EXPORT).await;
            crate::docker::start_container(docker, &cname).await;
        }
        return Err(err);
    }

    if was_running {
        crate::docker::handoff_boot_reason(docker, request.name, &cname, &crate::lifecycle::BACKUP_EXPORT).await;
        crate::docker::start_container(docker, &cname).await;
    }

    export_from_snapshot(docker, request, &snapshot_tag).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_manifest_stamps_current_version_and_format() {
        let manifest = build_manifest("apollo", crate::settings::UserDesired::Running, vec![], "2026-08-07T00:00:00Z".into());
        assert_eq!(manifest.format_version, BUNDLE_FORMAT_VERSION);
        assert_eq!(manifest.vestad_version, env!("CARGO_PKG_VERSION"));
        assert_eq!(manifest.agent_name, "apollo");
    }

    #[test]
    fn bundle_round_trips_manifest_constitution_and_image() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let image_src = dir.path().join("image-src.tar");
        std::fs::write(&image_src, b"fake image tar bytes").expect("write image");
        let manifest = BundleManifest {
            format_version: BUNDLE_FORMAT_VERSION,
            agent_name: "apollo".into(),
            vestad_version: "0.1.187".into(),
            created_at: "2026-08-07T00:00:00Z".into(),
            user_desired: crate::settings::UserDesired::Stopped,
            mounts: vec![crate::mounts::HostMount {
                host_path: "/home/u/docs".into(),
                container_path: "/mnt/docs".into(),
                writable: true,
            }],
        };
        let bundle = dir.path().join("apollo.tar.gz");
        write_bundle(&bundle, &manifest, "be kind", &image_src).expect("write bundle");

        assert_eq!(sniff_bundle(&bundle).expect("sniff"), BundleKind::Bundle);
        let (read_manifest, constitution) = open_bundle(&bundle).expect("open");
        assert_eq!(read_manifest.agent_name, "apollo");
        assert_eq!(read_manifest.user_desired, crate::settings::UserDesired::Stopped);
        assert_eq!(read_manifest.mounts.len(), 1);
        assert_eq!(constitution, "be kind");
        let mut image_bytes = Vec::new();
        read_bundle_image(&bundle, |chunk| {
            image_bytes.extend_from_slice(chunk);
            Ok(())
        })
        .expect("image");
        assert_eq!(image_bytes, b"fake image tar bytes");
    }

    #[test]
    fn sniff_reports_legacy_for_plain_gzipped_tar() {
        // A legacy export is a gzipped docker-save tar; its first entry is never vesta-manifest.json.
        let dir = tempfile::TempDir::new().expect("tempdir");
        let legacy = dir.path().join("legacy.tar.gz");
        let file = std::fs::File::create(&legacy).expect("create");
        let encoder = flate2::write::GzEncoder::new(file, flate2::Compression::default());
        let mut builder = tar::Builder::new(encoder);
        let mut header = tar::Header::new_gnu();
        header.set_size(2);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append_data(&mut header, "manifest.json", &b"[]"[..]).expect("append");
        builder.into_inner().expect("tar").finish().expect("gzip");
        assert_eq!(sniff_bundle(&legacy).expect("sniff"), BundleKind::Legacy);
    }

    #[test]
    fn sniff_rejects_garbage() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let junk = dir.path().join("junk.tar.gz");
        std::fs::write(&junk, b"not gzip at all").expect("write");
        assert!(sniff_bundle(&junk).is_err());
    }

    #[test]
    fn open_bundle_refuses_future_format_version() {
        // Build a bundle whose manifest claims version BUNDLE_FORMAT_VERSION + 1.
        let dir = tempfile::TempDir::new().expect("tempdir");
        let image_src = dir.path().join("image-src.tar");
        std::fs::write(&image_src, b"x").expect("write image");
        let manifest = BundleManifest {
            format_version: BUNDLE_FORMAT_VERSION + 1,
            agent_name: "apollo".into(),
            vestad_version: "9.9.9".into(),
            created_at: "2026-08-07T00:00:00Z".into(),
            user_desired: crate::settings::UserDesired::Running,
            mounts: vec![],
        };
        let bundle = dir.path().join("future.tar.gz");
        write_bundle(&bundle, &manifest, "", &image_src).expect("write");
        let err = open_bundle(&bundle).expect_err("must refuse");
        assert!(err.to_string().contains("newer"), "got: {err}");
    }

    #[test]
    fn read_bundle_image_fails_on_truncated_file() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let image_src = dir.path().join("image-src.tar");
        std::fs::write(&image_src, vec![7u8; 64 * 1024]).expect("write image");
        let manifest = BundleManifest {
            format_version: BUNDLE_FORMAT_VERSION,
            agent_name: "apollo".into(),
            vestad_version: "0.1.187".into(),
            created_at: "2026-08-07T00:00:00Z".into(),
            user_desired: crate::settings::UserDesired::Running,
            mounts: vec![],
        };
        let bundle = dir.path().join("whole.tar.gz");
        write_bundle(&bundle, &manifest, "", &image_src).expect("write");
        let whole = std::fs::read(&bundle).expect("read");
        let truncated_path = dir.path().join("truncated.tar.gz");
        std::fs::write(&truncated_path, &whole[..whole.len() / 2]).expect("write truncated");
        let result = read_bundle_image(&truncated_path, |_| Ok(()));
        assert!(result.is_err(), "truncated bundle must fail");
    }

    fn test_docker() -> bollard::Docker {
        crate::docker::connect().expect("docker")
    }

    fn test_agent_image() -> String {
        std::env::var(crate::docker::AGENT_IMAGE_ENV).unwrap_or_else(|_| crate::docker::vesta_image())
    }

    #[tokio::test]
    #[ignore]
    async fn scrub_image_removes_credentials_and_clears_provider() {
        let docker = test_docker();
        let image = test_agent_image();
        let name = format!("scrubtest-{}", std::process::id());
        let fixture_cname = format!("vesta-scrub-fixture-{name}");
        let fixture_image = format!("vesta-scrub-fixture:{name}");

        // Build a fixture image with credentials planted: create (never start) a container from the
        // agent image, docker cp the files in, commit.
        let dir = tempfile::TempDir::new().expect("tempdir");
        let creds = dir.path().join(".credentials.json");
        std::fs::write(&creds, r#"{"claudeAiOauth":{"accessToken":"secret"}}"#).expect("write creds");
        let config_json = dir.path().join("config.json");
        std::fs::write(
            &config_json,
            r#"{"provider":{"kind":"openrouter","key":"sk-secret","model":"m"},"timezone":"Europe/London"}"#,
        )
        .expect("write config");

        crate::docker::create_plain_container(&docker, &image, &fixture_cname).await.expect("create fixture");
        let cp = |src: &std::path::Path, dst: &str| {
            let status = std::process::Command::new("docker")
                .args(["cp", &src.display().to_string(), &format!("{fixture_cname}:{dst}")])
                .status()
                .expect("docker cp runs");
            assert!(status.success(), "docker cp {dst} failed");
        };
        // ~/.claude exists in the image (created by the Dockerfile), so the file cp lands directly.
        cp(&creds, "/root/.claude/.credentials.json");
        // /root/agent/data may be absent in a never-booted image; docker cp cannot mkdir -p, so
        // stage the whole data dir and cp the directory.
        let data_dir = dir.path().join("data");
        std::fs::create_dir_all(&data_dir).expect("mkdir data");
        std::fs::copy(&config_json, data_dir.join("config.json")).expect("stage config");
        cp(&data_dir, "/root/agent/data");
        let status = std::process::Command::new("docker")
            .args(["commit", &fixture_cname, &fixture_image])
            .status()
            .expect("docker commit runs");
        assert!(status.success());

        // Scrub. core_dir: extract the embedded agent code into a temp config dir, as the CLI does.
        let config_dir = tempfile::TempDir::new().expect("tempdir");
        let code_dir = crate::agent_code::ensure_agent_code(config_dir.path()).expect("agent code");
        let scrubbed = scrub_image(&docker, &name, &fixture_image, &code_dir.join("core"))
            .await
            .expect("scrub succeeds");

        // Verify inside the scrubbed image: both credential files gone, provider cleared, timezone kept.
        let verify_cname = format!("vesta-scrub-verify-{name}");
        let exit = crate::docker::run_oneshot_container(
            &docker,
            crate::docker::OneshotSpec {
                image: &scrubbed,
                cname: &verify_cname,
                cmd: vec!["sh".into(), "-c".into(),
                    "test ! -f /root/.claude/.credentials.json && \
                     test ! -f /root/agent/data/claude-code-proxy/codex/auth.json && \
                     grep -q Europe/London /root/agent/data/config.json && \
                     ! grep -q sk-secret /root/agent/data/config.json".into()],
                ro_binds: vec![],
            },
            60,
        )
        .await
        .expect("verify runs");
        assert_eq!(exit, 0, "scrubbed image must have no credentials and keep prefs");

        // Cleanup.
        for cname in [&fixture_cname, &verify_cname] {
            crate::docker::remove_container_force(&docker, cname).await.ok();
        }
        for img in [&fixture_image, &scrubbed] {
            crate::docker::remove_image(&docker, img).await.ok();
        }
    }
}
