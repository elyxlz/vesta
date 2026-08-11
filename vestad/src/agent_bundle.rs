//! Portable agent export/import bundle format: a gzipped tar carrying a JSON
//! manifest, the agent's constitution, and a flat `docker export` filesystem
//! tar, in that fixed entry order. `write_bundle` produces one, `sniff_bundle`
//! tells a bundle apart from a legacy plain-image export without fully parsing it,
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
/// Cap on the manifest and constitution entries, which are read whole from untrusted files.
const MAX_HEAD_ENTRY_BYTES: u64 = 256 * 1024;
const IMAGE_SPOOL_SUFFIX: &str = ".image-partial";
const EXPORT_IMAGE_REPO_PREFIX: &str = "vesta-export";
/// The one tag every export commits its capture under, reclaimed by the next run's sweep.
const SNAPSHOT_TAG: &str = "snapshot";
pub const SCRUB_TIMEOUT_SECS: u64 = 300;

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
    if entry_path.as_ref() != Path::new(expected_name) || entry.size() > MAX_HEAD_ENTRY_BYTES {
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

/// The one pinned invocation of core's LLM provider sign-out. cwd /root/agent puts the core
/// package (bind-mounted at /root/agent/core) on sys.path; the venv is baked into the image.
pub fn scrub_cmd() -> Vec<String> {
    vec![
        "sh".into(),
        "-c".into(),
        "cd /root/agent && .venv/bin/python -c 'from core.provider import clear_provider; clear_provider()'".into(),
    ]
}

fn scrub_container_name(agent_name: &str) -> String {
    format!("{EXPORT_IMAGE_REPO_PREFIX}-scrub-{agent_name}")
}

/// Strip the LLM provider sign-in from `source_image` by running core's `clear_provider` (via
/// `scrub_cmd`) in a throwaway container, and return that container's name: its filesystem is
/// the scrubbed copy the bundle carries, so the caller exports it directly and removes it.
/// `core_dir` is bind-mounted read-only at `docker::CORE_MOUNT_DEST` so the invocation reaches
/// the same core package the agent runs.
pub async fn run_scrub_container(
    docker: &Docker,
    agent_name: &str,
    source_image: &str,
    core_dir: &Path,
) -> Result<String, DockerError> {
    let cname = scrub_container_name(agent_name);

    crate::docker::remove_container_force(docker, &cname).await.ok();

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
        // export's leftover sweep in `export_agent` reclaims it.
        return Err(DockerError::Failed(format!(
            "LLM provider scrub failed (exit {exit_code}); see docker logs {cname}"
        )));
    }

    Ok(cname)
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

/// The uncompressed filesystem tar spooled next to `output` while a bundle is assembled, so the
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

/// Everything the export does to the captured copy: scrub it, build the manifest, spool the
/// scrub container's filesystem, and package the bundle. The source agent is never touched
/// here, so every failure cleans up its own litter (spool file, scrub container, snapshot
/// image) and leaves the agent running; `write_bundle` removes a partial `output` itself.
async fn export_from_snapshot(docker: &Docker, request: ExportRequest<'_>, snapshot_image: &str) -> Result<(), DockerError> {
    let now_rfc3339 = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|err| docker_failed("formatting export timestamp", err))?;

    eprintln!("scrubbing the LLM provider sign-in...");
    // A failed scrub keeps its container for `docker logs`, and that container pins the snapshot
    // image. Neither is removed on that path, so `export_agent`'s sweep reclaims both on the next
    // run. Past the scrub, the cleanup below always runs.
    let scrub_cname = run_scrub_container(docker, request.name, snapshot_image, request.core_dir).await?;

    let manifest = build_manifest(request.name, request.user_desired, request.mounts, now_rfc3339);

    let spool_path = spool_path_for(request.output);
    eprintln!("exporting filesystem...");
    let export_result = crate::docker::export_container_to_file(&scrub_cname, &spool_path).await;
    let bundle_result = match export_result {
        Ok(()) => {
            eprintln!("packaging bundle...");
            write_bundle(request.output, &manifest, &request.constitution, &spool_path)
        }
        Err(err) => Err(err),
    };

    std::fs::remove_file(&spool_path).ok();
    crate::docker::remove_container_force(docker, &scrub_cname).await.ok();
    crate::docker::remove_image(docker, snapshot_image).await.ok();
    bundle_result
}

/// Export `request.name` to a portable bundle at `request.output`: commit the agent's
/// filesystem, then scrub and package that copy. Progress lines go to stderr. The commit is
/// the whole cost the agent pays, a pause of seconds, so an export never stops the agent and
/// everything past the commit reads the copy alone.
pub async fn export_agent(docker: &Docker, request: ExportRequest<'_>) -> Result<(), DockerError> {
    crate::docker::validate_name(request.name)?;
    let cname = crate::docker::container_name(request.name);
    crate::docker::guard_alive(crate::docker::container_status(docker, &cname).await, request.name)?;

    let image_repo = format!("{EXPORT_IMAGE_REPO_PREFIX}-{}", request.name);
    let snapshot_image = format!("{image_repo}:{SNAPSHOT_TAG}");
    // Reclaim what a prior failed scrub deliberately left behind, container first so the
    // snapshot image it pins becomes removable, before this run's capture takes the tag.
    crate::docker::remove_container_force(docker, &scrub_container_name(request.name)).await.ok();
    crate::docker::remove_image(docker, &snapshot_image).await.ok();

    eprintln!("capturing agent...");
    crate::docker::commit_container_to_image(docker, &cname, &image_repo, SNAPSHOT_TAG).await?;

    export_from_snapshot(docker, request, &snapshot_image).await
}

// --- Import ---

pub struct ImportRequest<'a> {
    pub input: &'a Path,
    pub name_override: Option<&'a str>,
    pub env_config: &'a crate::docker::AgentEnvConfig,
}

pub struct ImportOutcome {
    pub name: String,
    pub port: u16,
    pub manifest: Option<BundleManifest>,
}

/// The name a new agent takes on import: the override always wins, a bundle otherwise falls
/// back to its embedded manifest name, and a legacy plain-image file (no manifest) has no name
/// to fall back to, so the override is mandatory there.
pub fn resolve_import_name(
    kind: BundleKind,
    manifest_name: Option<&str>,
    override_name: Option<&str>,
) -> Result<String, DockerError> {
    if let Some(name) = override_name {
        return Ok(name.to_string());
    }
    match (kind, manifest_name) {
        (BundleKind::Bundle, Some(name)) => Ok(name.to_string()),
        (BundleKind::Bundle, None) => Err(DockerError::Failed("bundle manifest missing agent name".to_string())),
        (BundleKind::Legacy, _) => {
            Err(DockerError::Failed("legacy export file has no embedded name; pass --name".to_string()))
        }
    }
}

/// The name `import_agent` would create, without holding the per-agent file lock the caller
/// takes once it knows that name. Cheap: a bundle's manifest is only its small tar head.
/// Validates before returning: the manifest's `agent_name` is untrusted file content, and the
/// caller locks a `{name}.lock` path keyed on this name before any other validation runs, so an
/// unvalidated name (e.g. `../evil` or an absolute path) could escape the lock directory.
pub fn peek_import_name(input: &Path, name_override: Option<&str>) -> Result<String, DockerError> {
    let kind = sniff_bundle(input)?;
    let manifest_name = match kind {
        BundleKind::Bundle => Some(open_bundle(input)?.0.agent_name),
        BundleKind::Legacy => None,
    };
    let name = resolve_import_name(kind, manifest_name.as_deref(), name_override)?;
    crate::docker::validate_name(&name)?;
    Ok(name)
}

fn agent_exists_error(name: &str) -> DockerError {
    DockerError::Failed(format!("agent '{name}' already exists; destroy it first or pass a different --name"))
}

/// LEGACY(remove-when: 2027-08-01; plain-image files from the removed `vestad backup export`
/// are by then over a year stale): import a legacy plain-image export (a bare `docker save`
/// tar, gzipped or not, with no manifest): load the image directly and create+start the agent,
/// always running.
async fn import_legacy(docker: &Docker, request: ImportRequest<'_>) -> Result<ImportOutcome, DockerError> {
    let name = resolve_import_name(BundleKind::Legacy, None, request.name_override)?;
    crate::docker::validate_name(&name)?;
    let cname = crate::docker::container_name(&name);
    if crate::docker::container_status(docker, &cname).await != crate::docker::ContainerStatus::NotFound {
        return Err(agent_exists_error(&name));
    }

    eprintln!("loading image from {}...", request.input.display());
    let image = crate::docker::load_image_from_file(docker, request.input).await?;

    eprintln!("creating agent '{name}'...");
    let port = crate::docker::allocate_port()?;
    crate::docker::create_container(
        docker,
        request.env_config,
        crate::docker::ContainerSpec {
            cname: &cname,
            image: &image,
            port,
            agent_name: &name,
            user_mounts: &[],
        },
    )
    .await?;

    crate::docker::handoff_boot_reason(docker, &name, &cname, &crate::lifecycle::BACKUP_IMPORT).await;
    if !crate::docker::start_container(docker, &cname).await {
        return Err(DockerError::Failed("failed to start imported agent".to_string()));
    }

    Ok(ImportOutcome { name, port, manifest: None })
}

/// Imports the bundle's flat filesystem tar as `vesta-restore:{agent_name}`, the stable
/// per-agent image name a restic restore also takes, so image cleanup treats restores and
/// imports alike; a previous image under that name is force-removed first. The blocking
/// tar+gzip read feeds `docker import`'s stdin from its own thread, so the multi-GB image tar
/// never needs a spool file beside an input that may sit on read-only media.
async fn load_bundle_image(input: &Path, agent_name: &str) -> Result<String, DockerError> {
    let image_ref = format!("vesta-restore:{agent_name}");
    let input_path = input.to_path_buf();
    let image_for_task = image_ref.clone();

    tokio::task::spawn_blocking(move || -> Result<(), DockerError> {
        std::process::Command::new("docker")
            .args(["rmi", "-f", &image_for_task])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .ok();

        let mut child = crate::docker::import_container_fs_tar_cmd(&image_for_task)
            .spawn()
            .map_err(|err| docker_failed("failed to start docker import", err))?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| DockerError::Failed("docker import stdin not available".to_string()))?;
        let read_result = read_bundle_image(&input_path, |chunk| {
            std::io::Write::write_all(&mut stdin, chunk).map_err(|err| docker_failed("docker import stopped reading", err))
        });
        drop(stdin);
        if read_result.is_err() {
            // Plain EOF would have docker commit an image out of the partial stream it holds.
            child.kill().ok();
        }
        let output = child.wait_with_output().map_err(|err| docker_failed("docker import wait failed", err))?;
        // A killed or broken-pipe import names only the consequence, so the bundle read's own
        // error outranks docker's stderr.
        read_result?;
        crate::docker::finish_import_output(&output)
    })
    .await
    .map_err(|err| docker_failed("bundle import task panicked", err))??;

    Ok(image_ref)
}

/// Steps that follow a loaded image: write the constitution (before `create_container`, whose
/// `ensure_constitution_file` only creates-if-missing), create the container, then start it
/// only when the manifest says the source agent was running.
async fn finish_bundle_import(
    docker: &Docker,
    request: &ImportRequest<'_>,
    name: &str,
    cname: &str,
    manifest: BundleManifest,
    constitution: &str,
    image: &str,
) -> Result<ImportOutcome, DockerError> {
    eprintln!("creating agent '{name}'...");
    crate::docker::write_constitution(&request.env_config.agents_dir, name, constitution)?;

    let port = crate::docker::allocate_port()?;
    crate::docker::create_container(
        docker,
        request.env_config,
        crate::docker::ContainerSpec {
            cname,
            image,
            port,
            agent_name: name,
            user_mounts: &[],
        },
    )
    .await?;

    crate::docker::handoff_boot_reason(docker, name, cname, &crate::lifecycle::BACKUP_IMPORT).await;
    if manifest.user_desired == crate::settings::UserDesired::Running && !crate::docker::start_container(docker, cname).await {
        return Err(DockerError::Failed("failed to start imported agent".to_string()));
    }

    Ok(ImportOutcome { name: name.to_string(), port, manifest: Some(manifest) })
}

/// Import a bundle: warn on a manifest from a newer vestad, resolve and validate the name,
/// import the image, then hand off to `finish_bundle_import`. A failure anywhere past the
/// import removes the freshly imported image so a retry doesn't trip over it.
async fn import_bundle(docker: &Docker, request: ImportRequest<'_>) -> Result<ImportOutcome, DockerError> {
    let (manifest, constitution) = open_bundle(request.input)?;

    if crate::update::version_less_than(env!("CARGO_PKG_VERSION"), &manifest.vestad_version) {
        eprintln!(
            "warning: this bundle was exported by vestad v{}, newer than this vestad v{}; the agent's first boot will converge it, but consider updating vestad first",
            manifest.vestad_version,
            env!("CARGO_PKG_VERSION"),
        );
    }

    let name = resolve_import_name(BundleKind::Bundle, Some(&manifest.agent_name), request.name_override)?;
    crate::docker::validate_name(&name)?;
    let cname = crate::docker::container_name(&name);
    if crate::docker::container_status(docker, &cname).await != crate::docker::ContainerStatus::NotFound {
        return Err(agent_exists_error(&name));
    }

    eprintln!("loading image...");
    let image = load_bundle_image(request.input, &name).await?;

    let outcome = finish_bundle_import(docker, &request, &name, &cname, manifest, &constitution, &image).await;
    if outcome.is_err() {
        crate::docker::remove_image(docker, &image).await.ok();
    }
    outcome
}

pub async fn import_agent(docker: &Docker, request: ImportRequest<'_>) -> Result<ImportOutcome, DockerError> {
    match sniff_bundle(request.input)? {
        BundleKind::Bundle => import_bundle(docker, request).await,
        BundleKind::Legacy => import_legacy(docker, request).await,
    }
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

    #[test]
    fn resolve_import_name_prefers_override_then_manifest() {
        assert_eq!(resolve_import_name(BundleKind::Bundle, Some("apollo"), Some("copy")).expect("ok"), "copy");
        assert_eq!(resolve_import_name(BundleKind::Bundle, Some("apollo"), None).expect("ok"), "apollo");
    }

    #[test]
    fn resolve_import_name_requires_override_for_legacy() {
        assert_eq!(resolve_import_name(BundleKind::Legacy, None, Some("apollo")).expect("ok"), "apollo");
        let err = resolve_import_name(BundleKind::Legacy, None, None).expect_err("must refuse");
        assert!(err.to_string().contains("--name"), "got: {err}");
    }

    /// A bundle whose manifest carries a malicious `agent_name`. Its manifest name alone must
    /// never reach a caller that locks a `{name}.lock` file keyed on it.
    fn bundle_with_manifest_name(dir: &Path, agent_name: &str) -> PathBuf {
        let image_src = dir.join("image-src.tar");
        std::fs::write(&image_src, b"x").expect("write image");
        let manifest = BundleManifest {
            format_version: BUNDLE_FORMAT_VERSION,
            agent_name: agent_name.to_string(),
            vestad_version: env!("CARGO_PKG_VERSION").to_string(),
            created_at: "2026-08-07T00:00:00Z".into(),
            user_desired: crate::settings::UserDesired::Running,
            mounts: vec![],
        };
        let bundle = dir.join("evil.tar.gz");
        write_bundle(&bundle, &manifest, "", &image_src).expect("write bundle");
        bundle
    }

    #[test]
    fn peek_import_name_rejects_path_traversal_in_manifest_name() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let bundle = bundle_with_manifest_name(dir.path(), "../evil");

        let err = peek_import_name(&bundle, None).expect_err("must refuse traversal name");
        assert!(matches!(err, DockerError::InvalidName(_)), "got: {err}");

        // The traversal name must never have reached a caller that could lock/write a path
        // derived from it: no such file exists anywhere reachable from the tempdir or its parent.
        assert!(!dir.path().join("../evil.lock").exists());
    }

    #[test]
    fn peek_import_name_override_wins_and_is_validated() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let bundle = bundle_with_manifest_name(dir.path(), "../evil");

        let name = peek_import_name(&bundle, Some("apollo")).expect("valid override succeeds");
        assert_eq!(name, "apollo");
    }

    fn test_docker() -> bollard::Docker {
        crate::docker::connect().expect("docker")
    }

    fn test_agent_image() -> String {
        std::env::var(crate::docker::AGENT_IMAGE_ENV).unwrap_or_else(|_| crate::docker::vesta_image())
    }

    /// Plants fake OAuth credentials and a scrubbable `config.json` into `cname` via `docker cp`,
    /// staged under `dir`. Shared by the scrub test and the export/import round-trip test.
    fn plant_credentials(cname: &str, dir: &Path) {
        let creds = dir.join(".credentials.json");
        std::fs::write(&creds, r#"{"claudeAiOauth":{"accessToken":"secret"}}"#).expect("write creds");
        let config_json = dir.join("config.json");
        std::fs::write(
            &config_json,
            r#"{"provider":{"kind":"openrouter","key":"sk-secret","model":"m"},"timezone":"Europe/London"}"#,
        )
        .expect("write config");

        let cp = |src: &Path, dst: &str| {
            let status = std::process::Command::new("docker")
                .args(["cp", &src.display().to_string(), &format!("{cname}:{dst}")])
                .status()
                .expect("docker cp runs");
            assert!(status.success(), "docker cp {dst} failed");
        };
        // ~/.claude exists in the image (created by the Dockerfile), so the file cp lands directly.
        cp(&creds, "/root/.claude/.credentials.json");
        // /root/agent/data may be absent in a never-booted container, and docker cp cannot mkdir
        // -p, so stage the whole data dir and cp the directory.
        let data_dir = dir.join("data");
        std::fs::create_dir_all(&data_dir).expect("mkdir data");
        std::fs::copy(&config_json, data_dir.join("config.json")).expect("stage config");
        cp(&data_dir, "/root/agent/data");
    }

    /// Runs the "no credentials, prefs retained" probe from the scrub test against `image`,
    /// removing the throwaway verify container it starts. Shared by the scrub test and the
    /// export/import round-trip test.
    async fn assert_no_credentials(docker: &Docker, image: &str, verify_cname: &str) {
        let exit = crate::docker::run_oneshot_container(
            docker,
            crate::docker::OneshotSpec {
                image,
                cname: verify_cname,
                cmd: vec![
                    "sh".into(),
                    "-c".into(),
                    "test ! -f /root/.claude/.credentials.json && \
                     test ! -f /root/agent/data/claude-code-proxy/codex/auth.json && \
                     grep -q Europe/London /root/agent/data/config.json && \
                     ! grep -q sk-secret /root/agent/data/config.json"
                        .into(),
                ],
                ro_binds: vec![],
            },
            60,
        )
        .await
        .expect("verify runs");
        assert_eq!(exit, 0, "image must have no credentials and keep prefs");
        crate::docker::remove_container_force(docker, verify_cname).await.ok();
    }

    #[tokio::test]
    #[ignore = "requires Docker + the local agent image"]
    async fn scrub_image_removes_credentials_and_clears_provider() {
        let docker = test_docker();
        let image = test_agent_image();
        let name = format!("scrubtest-{}", std::process::id());
        let fixture_cname = format!("vesta-scrub-fixture-{name}");
        let fixture_image = format!("vesta-scrub-fixture:{name}");

        // Build a fixture image with credentials planted: create (never start) a container from the
        // agent image, docker cp the files in, commit.
        let dir = tempfile::TempDir::new().expect("tempdir");
        crate::docker::create_plain_container(&docker, &image, &fixture_cname).await.expect("create fixture");
        plant_credentials(&fixture_cname, dir.path());
        let commit_status = std::process::Command::new("docker")
            .args(["commit", &fixture_cname, &fixture_image])
            .status()
            .expect("docker commit runs");
        assert!(commit_status.success());

        // Scrub. core_dir: extract the embedded agent code into a temp config dir, as the CLI does.
        let config_dir = tempfile::TempDir::new().expect("tempdir");
        let code_dir = crate::agent_code::ensure_agent_code(config_dir.path()).expect("agent code");
        let scrubbed = run_scrub_container(&docker, &name, &fixture_image, &code_dir.join("core"))
            .await
            .expect("scrub succeeds");

        // Verify inside the scrubbed image: both credential files gone, provider cleared, timezone kept.
        let verify_cname = format!("vesta-scrub-verify-{name}");
        assert_no_credentials(&docker, &scrubbed, &verify_cname).await;

        // Cleanup.
        crate::docker::remove_container_force(&docker, &fixture_cname).await.ok();
        for img in [&fixture_image, &scrubbed] {
            crate::docker::remove_image(&docker, img).await.ok();
        }
    }

    /// Removes a test agent network on drop, mirroring `docker.rs`'s own `TestNetwork`
    /// (private to that module's tests, so not reusable here).
    struct TestNetwork {
        name: String,
    }

    impl Drop for TestNetwork {
        fn drop(&mut self) {
            std::process::Command::new("docker").args(["network", "rm", &self.name]).status().ok();
        }
    }

    #[tokio::test]
    #[ignore = "requires Docker + the local agent image"]
    async fn export_import_round_trip_reproduces_agent_without_credentials() {
        let docker = test_docker();
        let source_name = format!("exp-src-{}", std::process::id());
        let target_name = format!("exp-dst-{}", std::process::id());
        let config_dir = tempfile::TempDir::new().expect("tempdir");
        let agents_dir = config_dir.path().join("agents");
        std::fs::create_dir_all(&agents_dir).expect("agents dir");
        let code_dir = crate::agent_code::ensure_agent_code(config_dir.path()).expect("agent code");
        crate::upstream::ensure_upstream(config_dir.path(), &code_dir).expect("upstream");
        let env_config = crate::docker::AgentEnvConfig {
            config_dir: config_dir.path().to_path_buf(),
            agents_dir: agents_dir.clone(),
            vestad_port: 1,
            vestad_tunnel: None,
        };
        let _source_net = TestNetwork { name: crate::docker::agent_network_name(&source_name) };
        let _target_net = TestNetwork { name: crate::docker::agent_network_name(&target_name) };

        // Source agent: created (never started), credentials planted as in the scrub test.
        let src_cname = crate::docker::container_name(&source_name);
        let port = crate::docker::allocate_port().expect("port");
        crate::docker::create_container(
            &docker,
            &env_config,
            crate::docker::ContainerSpec {
                cname: &src_cname,
                image: &test_agent_image(),
                port,
                agent_name: &source_name,
                user_mounts: &[],
            },
        )
        .await
        .expect("create source");
        let creds_dir = tempfile::TempDir::new().expect("tempdir");
        plant_credentials(&src_cname, creds_dir.path());
        std::fs::write(crate::docker::constitution_host_path(&agents_dir, &source_name), "be kind").expect("constitution");

        let bundle_path = config_dir.path().join("agent.tar.gz");
        export_agent(
            &docker,
            ExportRequest {
                name: &source_name,
                output: &bundle_path,
                core_dir: &code_dir.join("core"),
                constitution: "be kind".into(),
                user_desired: crate::settings::UserDesired::Stopped,
                mounts: vec![crate::mounts::HostMount {
                    host_path: "/tmp".into(),
                    container_path: "/mnt/t".into(),
                    writable: false,
                }],
            },
        )
        .await
        .expect("export");

        let outcome = import_agent(
            &docker,
            ImportRequest {
                input: &bundle_path,
                name_override: Some(&target_name),
                env_config: &env_config,
            },
        )
        .await
        .expect("import");
        assert_eq!(outcome.name, target_name);
        let manifest = outcome.manifest.expect("bundle manifest");
        assert_eq!(manifest.agent_name, source_name);
        assert_eq!(manifest.user_desired, crate::settings::UserDesired::Stopped);
        assert_eq!(manifest.mounts.len(), 1);

        // Stopped stays stopped: the imported container exists but is not running.
        let dst_cname = crate::docker::container_name(&target_name);
        assert_eq!(
            crate::docker::container_status(&docker, &dst_cname).await,
            crate::docker::ContainerStatus::Stopped
        );
        // Constitution landed on the new host side.
        let imported_constitution =
            std::fs::read_to_string(crate::docker::constitution_host_path(&agents_dir, &target_name)).expect("read constitution");
        assert_eq!(imported_constitution, "be kind");

        // No credentials inside the imported container: commit it and reuse the scrub-test probe.
        let target_verify_image = format!("vesta-export-verify:{target_name}");
        let commit_status = std::process::Command::new("docker")
            .args(["commit", &dst_cname, &target_verify_image])
            .status()
            .expect("docker commit runs");
        assert!(commit_status.success());
        let verify_cname = format!("vesta-export-verify-run-{target_name}");
        assert_no_credentials(&docker, &target_verify_image, &verify_cname).await;

        // Cleanup: containers, the loaded scrubbed image (timestamp-tagged under the source
        // name on load, so list by repo), the verify image, and the bundle. Networks clean up
        // via TestNetwork's Drop.
        crate::docker::remove_container_force(&docker, &src_cname).await.ok();
        crate::docker::remove_container_force(&docker, &dst_cname).await.ok();
        crate::docker::remove_image(&docker, &target_verify_image).await.ok();
        let listed = std::process::Command::new("docker")
            .args(["images", "-q", &format!("vesta-export-{source_name}")])
            .output()
            .expect("docker images runs");
        for image_id in String::from_utf8_lossy(&listed.stdout).split_whitespace() {
            crate::docker::remove_image(&docker, image_id).await.ok();
        }
        std::fs::remove_file(&bundle_path).ok();
    }

    #[tokio::test]
    #[ignore = "requires Docker + the local agent image"]
    async fn import_legacy_gzipped_image_creates_and_starts_agent() {
        let docker = test_docker();
        let image = test_agent_image();
        let target_name = format!("exp-legacy-{}", std::process::id());
        let config_dir = tempfile::TempDir::new().expect("tempdir");
        let agents_dir = config_dir.path().join("agents");
        std::fs::create_dir_all(&agents_dir).expect("agents dir");
        let code_dir = crate::agent_code::ensure_agent_code(config_dir.path()).expect("agent code");
        crate::upstream::ensure_upstream(config_dir.path(), &code_dir).expect("upstream");
        let env_config = crate::docker::AgentEnvConfig {
            config_dir: config_dir.path().to_path_buf(),
            agents_dir,
            vestad_port: 1,
            vestad_tunnel: None,
        };
        let _target_net = TestNetwork { name: crate::docker::agent_network_name(&target_name) };

        // A legacy export: a gzipped `docker save` tar with no manifest.
        let tar_path = config_dir.path().join("legacy-image.tar");
        let save_status = std::process::Command::new("docker")
            .args(["save", "-o", &tar_path.display().to_string(), &image])
            .status()
            .expect("docker save runs");
        assert!(save_status.success());
        let legacy_path = config_dir.path().join("legacy.tar.gz");
        let mut input = std::fs::File::open(&tar_path).expect("open tar");
        let output = std::fs::File::create(&legacy_path).expect("create gz");
        let mut encoder = flate2::write::GzEncoder::new(output, flate2::Compression::default());
        std::io::copy(&mut input, &mut encoder).expect("gzip tar");
        encoder.finish().expect("finish gzip");
        std::fs::remove_file(&tar_path).ok();

        let outcome = import_agent(
            &docker,
            ImportRequest {
                input: &legacy_path,
                name_override: Some(&target_name),
                env_config: &env_config,
            },
        )
        .await
        .expect("import legacy");
        assert_eq!(outcome.name, target_name);
        assert!(outcome.manifest.is_none());

        let dst_cname = crate::docker::container_name(&target_name);
        assert_eq!(
            crate::docker::container_status(&docker, &dst_cname).await,
            crate::docker::ContainerStatus::Running
        );

        // Cleanup: container and bundle file. The image tag is the pre-existing base agent
        // image (docker save/load round-trips the tag unchanged), so it is left alone.
        crate::docker::remove_container_force(&docker, &dst_cname).await.ok();
        std::fs::remove_file(&legacy_path).ok();
    }
}
