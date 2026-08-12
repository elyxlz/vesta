//! Portable agent export/import bundle format: a gzipped tar carrying a JSON
//! manifest, the agent's constitution, and a flat `docker export` filesystem
//! tar, in that fixed entry order. `write_bundle` produces one, `sniff_bundle`
//! tells a bundle apart from a legacy plain-image export without fully parsing it,
//! `open_bundle` reads the small head (manifest + constitution), and
//! `read_bundle_image` streams the trailing image entry into a caller sink.
//! `download_bundle` fetches one over http into a temp file the caller imports from.

use crate::docker::DockerError;
use bollard::Docker;
use futures_util::StreamExt;
use std::io::Read;
use std::path::{Path, PathBuf};
use tokio::io::AsyncWriteExt;

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

// --- Download ---

const HUMAN_SIZE_UNITS: [&str; 4] = ["B", "KB", "MB", "GB"];
const HUMAN_SIZE_STEP: f64 = 1024.0;
/// Progress cadence: one line per this much of a declared length, or per this many bytes when
/// the response declares none.
const DOWNLOAD_PROGRESS_STEP_PERCENT: u64 = 5;
const DOWNLOAD_PROGRESS_STEP_BYTES: u64 = 50 * 1024 * 1024;

/// A byte count to one decimal, in the largest unit that keeps it under 1024.
pub fn human_size(bytes: u64) -> String {
    let mut value = bytes as f64;
    let mut unit = 0;
    while value >= HUMAN_SIZE_STEP && unit + 1 < HUMAN_SIZE_UNITS.len() {
        value /= HUMAN_SIZE_STEP;
        unit += 1;
    }
    format!("{value:.1} {}", HUMAN_SIZE_UNITS[unit])
}

/// True for an import input the CLI must fetch before it can read it.
pub fn is_download_url(input: &str) -> bool {
    input.starts_with("http://") || input.starts_with("https://")
}

/// The progress line `downloaded` earns, or `None` while it is still within one step of the
/// `reported` point the last line named.
fn download_progress_line(downloaded: u64, total: Option<u64>, reported: u64) -> Option<String> {
    match total {
        Some(total) if total > 0 => {
            let percent = downloaded * 100 / total;
            (percent >= reported * 100 / total + DOWNLOAD_PROGRESS_STEP_PERCENT)
                .then(|| format!("downloading... {percent}%"))
        }
        _ => (downloaded >= reported + DOWNLOAD_PROGRESS_STEP_BYTES)
            .then(|| format!("downloading... {}", human_size(downloaded))),
    }
}

async fn download_to_file(url: &str, path: &Path) -> Result<(), DockerError> {
    let response = reqwest::get(url)
        .await
        .map_err(|err| docker_failed("downloading bundle", err))?
        .error_for_status()
        .map_err(|err| docker_failed("downloading bundle", err))?;
    let total = response.content_length();

    let file = tokio::fs::File::create(path)
        .await
        .map_err(|err| docker_failed("creating download file", err))?;
    let mut writer = tokio::io::BufWriter::new(file);
    let mut stream = response.bytes_stream();
    let mut downloaded: u64 = 0;
    let mut reported: u64 = 0;
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|err| docker_failed("downloading bundle", err))?;
        writer.write_all(&chunk).await.map_err(|err| docker_failed("writing download", err))?;
        downloaded += chunk.len() as u64;
        if let Some(line) = download_progress_line(downloaded, total, reported) {
            eprintln!("{line}");
            reported = downloaded;
        }
    }
    writer.flush().await.map_err(|err| docker_failed("writing download", err))?;
    Ok(())
}

/// Fetch the bundle at `url` into a temp file under `config_dir`, and return that path for the
/// import to read; the caller removes the file once it is done with it. Redirects are followed.
/// Every failure removes the partial file, so a dead download leaves nothing behind.
pub async fn download_bundle(url: &str, config_dir: &Path) -> Result<PathBuf, DockerError> {
    let tmp_dir = config_dir.join("tmp");
    std::fs::create_dir_all(&tmp_dir).map_err(|err| docker_failed("creating download directory", err))?;
    let path = tmp_dir.join(format!("import-download-{}.tar.gz", std::process::id()));

    eprintln!("downloading {url}...");
    match download_to_file(url, &path).await {
        Ok(()) => Ok(path),
        Err(err) => {
            std::fs::remove_file(&path).ok();
            Err(err)
        }
    }
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

/// What one decode of a bundle's head tells the caller: the name `import_agent` would create,
/// and the vestad version that wrote the file (`None` for a legacy file, which has no manifest).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportPeek {
    pub name: String,
    pub vestad_version: Option<String>,
}

/// Read a bundle's head before the import takes the per-agent file lock or loads a multi-GB
/// image. Cheap: a bundle's manifest is only its small tar head. Validates the name before
/// returning: the manifest's `agent_name` is untrusted file content, and the caller locks a
/// `{name}.lock` path keyed on this name before any other validation runs, so an unvalidated
/// name (e.g. `../evil` or an absolute path) could escape the lock directory.
pub fn peek_import(input: &Path, name_override: Option<&str>) -> Result<ImportPeek, DockerError> {
    let kind = sniff_bundle(input)?;
    let manifest = match kind {
        BundleKind::Bundle => Some(open_bundle(input)?.0),
        BundleKind::Legacy => None,
    };
    let name = resolve_import_name(kind, manifest.as_ref().map(|m| m.agent_name.as_str()), name_override)?;
    crate::docker::validate_name(&name)?;
    Ok(ImportPeek { name, vestad_version: manifest.map(|m| m.vestad_version) })
}

/// What an import must do about the vestad version that wrote a bundle. Newer state under older
/// code is refused; older state converges on the agent's first boot, so that one is the user's
/// call. A legacy file (`None`) and a version this vestad cannot compare both fail open.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ImportGate {
    Proceed,
    ConfirmOlder { bundle: String, current: String },
    RefuseNewer { bundle: String, current: String },
}

pub fn import_version_gate(bundle_version: Option<&str>, current: &str) -> ImportGate {
    let Some(bundle) = bundle_version else {
        return ImportGate::Proceed;
    };
    if !crate::update::version_comparable(bundle) || !crate::update::version_comparable(current) {
        return ImportGate::Proceed;
    }
    if crate::update::version_less_than(current, bundle) {
        ImportGate::RefuseNewer { bundle: bundle.to_string(), current: current.to_string() }
    } else if crate::update::version_less_than(bundle, current) {
        ImportGate::ConfirmOlder { bundle: bundle.to_string(), current: current.to_string() }
    } else {
        ImportGate::Proceed
    }
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

/// Which side of a finished import owns the error. A write that hit EPIPE only witnessed docker
/// dying, so docker's own words win there; otherwise a bundle-read error outranks the EOF docker
/// reports as its consequence.
fn import_pipeline_result(
    read_result: Result<(), DockerError>,
    write_failed: bool,
    output: &std::process::Output,
) -> Result<(), DockerError> {
    if write_failed {
        crate::docker::finish_import_output(output)?;
    }
    read_result?;
    crate::docker::finish_import_output(output)
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
        let mut write_failed = false;
        let read_result = read_bundle_image(&input_path, |chunk| {
            std::io::Write::write_all(&mut stdin, chunk).map_err(|err| {
                write_failed = true;
                docker_failed("docker import stopped reading", err)
            })
        });
        if read_result.is_err() {
            // Kill before the drop below delivers EOF: on EOF docker commits an image out
            // of the partial stream it holds.
            child.kill().ok();
        }
        drop(stdin);
        let output = child.wait_with_output().map_err(|err| docker_failed("docker import wait failed", err))?;
        import_pipeline_result(read_result, write_failed, &output)
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

/// Import a bundle: resolve and validate the name, import the image, then hand off to
/// `finish_bundle_import`. A failure anywhere past the import removes the freshly imported
/// image so a retry doesn't trip over it.
async fn import_bundle(docker: &Docker, request: ImportRequest<'_>) -> Result<ImportOutcome, DockerError> {
    let (manifest, constitution) = open_bundle(request.input)?;

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
    fn import_version_gate_refuses_newer_confirms_older_passes_equal_and_legacy() {
        assert!(matches!(import_version_gate(Some("9.9.9"), "0.2.1"), ImportGate::RefuseNewer { .. }));
        assert!(matches!(import_version_gate(Some("0.1.0"), "0.2.1"), ImportGate::ConfirmOlder { .. }));
        assert!(matches!(import_version_gate(Some("0.2.1"), "0.2.1"), ImportGate::Proceed));
        assert!(matches!(import_version_gate(None, "0.2.1"), ImportGate::Proceed));
        // Unparseable fails open, matching the client-compat convention. A `v` prefix is one such
        // shape: comparing it would drop the major component and read v0.1.0 as newer than 0.2.1.
        assert!(matches!(import_version_gate(Some("dev"), "0.2.1"), ImportGate::Proceed));
        assert!(matches!(import_version_gate(Some("v0.1.0"), "0.2.1"), ImportGate::Proceed));
    }

    #[test]
    fn human_size_scales_to_the_largest_whole_unit() {
        for (bytes, expected) in [(512u64, "512.0 B"), (1_572_864, "1.5 MB"), (3_221_225_472, "3.0 GB")] {
            assert_eq!(human_size(bytes), expected);
        }
    }

    #[test]
    fn download_urls_are_told_apart_from_file_paths() {
        assert!(is_download_url("https://example.com/apollo.tar.gz"));
        assert!(is_download_url("http://example.com/apollo.tar.gz"));
        assert!(!is_download_url("/home/u/apollo.tar.gz"));
        assert!(!is_download_url("apollo.tar.gz"));
    }

    #[test]
    fn download_progress_reports_per_percent_step_and_per_byte_step_without_a_total() {
        assert_eq!(download_progress_line(4, Some(100), 0), None);
        assert_eq!(download_progress_line(5, Some(100), 0).as_deref(), Some("downloading... 5%"));
        assert_eq!(download_progress_line(9, Some(100), 5), None);
        assert_eq!(download_progress_line(DOWNLOAD_PROGRESS_STEP_BYTES - 1, None, 0), None);
        assert_eq!(
            download_progress_line(DOWNLOAD_PROGRESS_STEP_BYTES, None, 0).as_deref(),
            Some("downloading... 50.0 MB")
        );
    }

    /// What a download may leave in `config_dir/tmp` once its caller is done with it: nothing.
    fn assert_download_tmp_empty(config_dir: &Path) {
        let leftovers: Vec<_> = std::fs::read_dir(config_dir.join("tmp"))
            .expect("tmp dir exists")
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .collect();
        assert!(leftovers.is_empty(), "got: {leftovers:?}");
    }

    /// An http server on an ephemeral loopback port, serving `router` until it is dropped.
    struct TestServer {
        base: String,
        task: tokio::task::JoinHandle<()>,
    }

    impl Drop for TestServer {
        fn drop(&mut self) {
            self.task.abort();
        }
    }

    async fn spawn_test_server(router: axum::Router) -> TestServer {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("bind loopback");
        let base = format!("http://{}", listener.local_addr().expect("listener address"));
        let task = tokio::spawn(async move {
            axum::serve(listener, router).await.ok();
        });
        TestServer { base, task }
    }

    /// A server that promises more body than it sends and then closes. The client reads the
    /// response head and some bytes before the connection dies, which is what puts the download
    /// past the point where it has created its file. No http framework will produce that, so it
    /// is written straight onto the socket.
    async fn spawn_truncating_server() -> TestServer {
        use tokio::io::AsyncReadExt;

        /// Enough for the request head reqwest sends; this server never reads a body.
        const REQUEST_DRAIN_BYTES: usize = 1024;

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("bind loopback");
        let base = format!("http://{}", listener.local_addr().expect("listener address"));
        let task = tokio::spawn(async move {
            let Ok((mut stream, _)) = listener.accept().await else { return };
            // Draining the request matters: closing a socket that still holds unread bytes sends
            // an RST, and the client would report that instead of the short body.
            let mut request = [0u8; REQUEST_DRAIN_BYTES];
            let Ok(_drained) = stream.read(&mut request).await else { return };
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 1024\r\n\r\npartial bundle")
                .await
                .ok();
        });
        TestServer { base, task }
    }

    #[tokio::test]
    async fn a_refused_download_leaves_no_partial_file() {
        // Port 1 on loopback refuses instantly, so this stays hermetic and fast.
        let dir = tempfile::TempDir::new().expect("tempdir");
        let err = download_bundle("http://127.0.0.1:1/apollo.tar.gz", dir.path())
            .await
            .expect_err("a refused connection must fail");
        assert!(err.to_string().contains("downloading bundle"), "got: {err}");
        assert_download_tmp_empty(dir.path());
    }

    #[tokio::test]
    async fn a_download_of_a_missing_url_fails_instead_of_saving_the_error_page() {
        // A router with no routes answers 404, what a wrong or expired link earns.
        let server = spawn_test_server(axum::Router::new()).await;
        let dir = tempfile::TempDir::new().expect("tempdir");
        let err = download_bundle(&format!("{}/apollo.tar.gz", server.base), dir.path())
            .await
            .expect_err("a 404 must fail");
        assert!(err.to_string().contains("downloading bundle"), "got: {err}");
        assert_download_tmp_empty(dir.path());
    }

    #[tokio::test]
    async fn a_download_cut_short_removes_the_partial_file() {
        // The failure lands on the body, so the download is already holding a file when it fails:
        // the one path on which the partial file has to be removed.
        let server = spawn_truncating_server().await;
        let dir = tempfile::TempDir::new().expect("tempdir");
        let err = download_bundle(&format!("{}/apollo.tar.gz", server.base), dir.path())
            .await
            .expect_err("a cut-short download must fail");
        assert!(err.to_string().contains("body"), "the failure must be the body, got: {err}");
        assert_download_tmp_empty(dir.path());
    }

    #[test]
    fn resolve_import_name_prefers_override_then_manifest() {
        assert_eq!(resolve_import_name(BundleKind::Bundle, Some("apollo"), Some("copy")).expect("ok"), "copy");
        assert_eq!(resolve_import_name(BundleKind::Bundle, Some("apollo"), None).expect("ok"), "apollo");
    }

    fn shell_output(script: &str) -> std::process::Output {
        std::process::Command::new("sh").args(["-c", script]).output().expect("sh runs")
    }

    #[test]
    fn dockers_own_error_wins_when_the_write_side_only_saw_the_broken_pipe() {
        let read_result = Err(docker_failed("docker import stopped reading", "Broken pipe"));
        let output = shell_output("printf 'no space left on device' >&2; exit 1");
        let err = import_pipeline_result(read_result, true, &output).expect_err("a failed import must error");
        assert!(err.to_string().contains("no space left on device"), "got: {err}");
    }

    #[test]
    fn dockers_error_surfaces_when_the_bundle_read_was_clean() {
        let output = shell_output("printf 'unexpected EOF' >&2; exit 1");
        let err = import_pipeline_result(Ok(()), false, &output).expect_err("a failed import must error");
        assert!(err.to_string().contains("unexpected EOF"), "got: {err}");
    }

    #[test]
    fn a_corrupt_bundle_outranks_the_eof_docker_reports_as_its_consequence() {
        let read_result = Err(DockerError::Failed(CORRUPT_BUNDLE_MESSAGE.to_string()));
        let output = shell_output("printf 'unexpected EOF' >&2; exit 1");
        let err = import_pipeline_result(read_result, false, &output).expect_err("a corrupt bundle must error");
        assert!(err.to_string().contains(CORRUPT_BUNDLE_MESSAGE), "got: {err}");
    }

    #[test]
    fn a_corrupt_bundle_errors_even_when_docker_exits_clean() {
        let read_result = Err(DockerError::Failed(CORRUPT_BUNDLE_MESSAGE.to_string()));
        let err = import_pipeline_result(read_result, false, &shell_output("exit 0")).expect_err("a corrupt bundle must error");
        assert!(err.to_string().contains(CORRUPT_BUNDLE_MESSAGE), "got: {err}");
    }

    #[test]
    fn a_clean_read_and_a_clean_docker_exit_pass() {
        assert!(import_pipeline_result(Ok(()), false, &shell_output("exit 0")).is_ok());
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
    fn peek_import_rejects_path_traversal_in_manifest_name() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let bundle = bundle_with_manifest_name(dir.path(), "../evil");

        let err = peek_import(&bundle, None).expect_err("must refuse traversal name");
        assert!(matches!(err, DockerError::InvalidName(_)), "got: {err}");

        // The traversal name must never have reached a caller that could lock/write a path
        // derived from it: no such file exists anywhere reachable from the tempdir or its parent.
        assert!(!dir.path().join("../evil.lock").exists());
    }

    #[test]
    fn peek_import_override_wins_and_is_validated() {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let bundle = bundle_with_manifest_name(dir.path(), "../evil");

        let peek = peek_import(&bundle, Some("apollo")).expect("valid override succeeds");
        assert_eq!(peek.name, "apollo");
        assert_eq!(peek.vestad_version.as_deref(), Some(env!("CARGO_PKG_VERSION")));
    }

    fn test_docker() -> bollard::Docker {
        crate::docker::connect().expect("docker")
    }

    fn test_agent_image() -> String {
        std::env::var(crate::docker::AGENT_IMAGE_ENV).unwrap_or_else(|_| crate::docker::vesta_image())
    }

    /// Best-effort `docker <args>`, quiet: safe to call from a `Drop` inside the tokio runtime.
    fn docker_cleanup(args: &[&str]) {
        std::process::Command::new("docker")
            .args(args)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .ok();
    }

    /// Every docker object a test creates, removed when it goes out of scope so a failed assertion
    /// leaks nothing. Containers go first: docker refuses to remove an image one still references.
    struct TestLitter {
        containers: Vec<String>,
        images: Vec<String>,
    }

    impl Drop for TestLitter {
        fn drop(&mut self) {
            for cname in &self.containers {
                docker_cleanup(&["rm", "-f", cname]);
            }
            for image in &self.images {
                docker_cleanup(&["rmi", "-f", image]);
            }
        }
    }

    /// A temp config dir set up the way vestad's own startup sets the real one up, which is what a
    /// created agent container needs: the embedded agent code extracted and the upstream repo built.
    struct TestAgentEnv {
        dir: tempfile::TempDir,
        config: crate::docker::AgentEnvConfig,
        core_dir: PathBuf,
    }

    fn test_agent_env() -> TestAgentEnv {
        let dir = tempfile::TempDir::new().expect("tempdir");
        let agents_dir = dir.path().join("agents");
        std::fs::create_dir_all(&agents_dir).expect("agents dir");
        let code_dir = crate::agent_code::ensure_agent_code(dir.path()).expect("agent code");
        crate::upstream::ensure_upstream(dir.path(), &code_dir).expect("upstream");
        let config = crate::docker::AgentEnvConfig {
            config_dir: dir.path().to_path_buf(),
            agents_dir,
            vestad_port: 1,
            vestad_tunnel: None,
        };
        TestAgentEnv { dir, config, core_dir: code_dir.join("core") }
    }

    /// Create (never start) a real agent container. A capture test needs one: only a commit of an
    /// agent carries that agent's own labels, the managed label included, onto the image.
    async fn create_test_agent(docker: &Docker, env: &TestAgentEnv, name: &str) {
        crate::docker::create_container(
            docker,
            &env.config,
            crate::docker::ContainerSpec {
                cname: &crate::docker::container_name(name),
                image: &test_agent_image(),
                port: crate::docker::allocate_port().expect("port"),
                agent_name: name,
                user_mounts: &[],
            },
        )
        .await
        .expect("create agent container");
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
        // /root/agent/data is absent in a never-booted container and present in a booted one, and
        // docker cp cannot mkdir -p, so stage the whole data dir and cp it into /root/agent: that
        // creates the directory in the first case and merges into it in the second.
        let data_dir = dir.join("data");
        std::fs::create_dir_all(&data_dir).expect("mkdir data");
        std::fs::copy(&config_json, data_dir.join("config.json")).expect("stage config");
        cp(&data_dir, "/root/agent");
    }

    /// Waits until the agent inside `cname` is past the boot step that deletes the credentials of
    /// a provider it is not signed in with, so a test can plant credentials a running agent keeps.
    /// The event db is created one step later, and the agent reads its provider at boot alone.
    async fn wait_for_agent_boot(cname: &str) {
        const BOOT_POLL_MAX: u32 = 180;

        for _ in 0..BOOT_POLL_MAX {
            let probe = std::process::Command::new("docker")
                .args(["exec", cname, "test", "-f", "/root/agent/data/events.db"])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
            if probe.is_ok_and(|status| status.success()) {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        }
        panic!("the agent in {cname} never finished booting");
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
    async fn scrub_removes_credentials_and_never_enumerates_as_an_agent() {
        let docker = test_docker();
        let name = format!("scrubtest-{}", std::process::id());
        let env = test_agent_env();
        let fixture_cname = crate::docker::container_name(&name);
        let fixture_repo = "vesta-scrub-fixture";
        let fixture_image = format!("{fixture_repo}:{name}");
        let probe_image = format!("vesta-scrub-probe:{name}");
        let scrub_cname = scrub_container_name(&name);
        let verify_cname = format!("vesta-scrub-verify-{name}");
        let _net = TestNetwork { name: crate::docker::agent_network_name(&name) };
        let _litter = TestLitter {
            containers: vec![fixture_cname.clone(), scrub_cname.clone(), verify_cname.clone()],
            images: vec![fixture_image.clone(), probe_image.clone()],
        };

        // The fixture is what an export scrubs: a commit of a real agent that has credentials on
        // disk, so the image carries both the credentials and the agent's own labels.
        create_test_agent(&docker, &env, &name).await;
        let staging = tempfile::TempDir::new().expect("tempdir");
        plant_credentials(&fixture_cname, staging.path());
        crate::docker::commit_container_to_image(&docker, &fixture_cname, fixture_repo, &name)
            .await
            .expect("commit fixture");

        let scrubbed = run_scrub_container(&docker, &name, &fixture_image, &env.core_dir)
            .await
            .expect("scrub succeeds");
        assert_eq!(scrubbed, scrub_cname);

        // The scrub container inherits `vesta.managed=true` from the image it runs from, so the
        // create has to override it: one left behind by a failed scrub would otherwise shadow the
        // agent it was made from in the name-keyed roster.
        let managed = crate::docker::list_managed_agents(&docker).await;
        let listed: Vec<&str> = managed.iter().map(|found| found.cname.as_str()).collect();
        assert!(listed.contains(&fixture_cname.as_str()), "the source agent must enumerate, got {listed:?}");
        assert!(!listed.contains(&scrub_cname.as_str()), "a scrub container must never enumerate, got {listed:?}");

        // The bundle carries the scrub container's own filesystem, so the probe runs on exactly
        // that: export it and import it back as an image a verify container can run.
        let fs_tar = env.dir.path().join("scrubbed.tar");
        crate::docker::export_container_to_file(&scrub_cname, &fs_tar).await.expect("export scrub container");
        let import_status = std::process::Command::new("docker")
            .args(["import", &fs_tar.display().to_string(), &probe_image])
            .stdout(std::process::Stdio::null())
            .status()
            .expect("docker import runs");
        assert!(import_status.success());
        assert_no_credentials(&docker, &probe_image, &verify_cname).await;
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
        let env = test_agent_env();
        let src_cname = crate::docker::container_name(&source_name);
        let dst_cname = crate::docker::container_name(&target_name);
        let verify_image = format!("vesta-export-verify:{target_name}");
        let verify_cname = format!("vesta-export-verify-run-{target_name}");
        let _source_net = TestNetwork { name: crate::docker::agent_network_name(&source_name) };
        let _target_net = TestNetwork { name: crate::docker::agent_network_name(&target_name) };
        let _litter = TestLitter {
            containers: vec![
                src_cname.clone(),
                dst_cname.clone(),
                scrub_container_name(&source_name),
                verify_cname.clone(),
            ],
            images: vec![
                format!("{EXPORT_IMAGE_REPO_PREFIX}-{source_name}:{SNAPSHOT_TAG}"),
                format!("vesta-restore:{target_name}"),
                verify_image.clone(),
            ],
        };

        // Source agent: started first and given its credentials once it is up, so the export below
        // captures a live agent that has an LLM provider signed in.
        create_test_agent(&docker, &env, &source_name).await;
        std::fs::write(crate::docker::constitution_host_path(&env.config.agents_dir, &source_name), "be kind")
            .expect("constitution");
        assert!(crate::docker::start_container(&docker, &src_cname).await, "the source agent starts");
        wait_for_agent_boot(&src_cname).await;
        let creds_dir = tempfile::TempDir::new().expect("tempdir");
        plant_credentials(&src_cname, creds_dir.path());
        let before = crate::docker::inspect_container(&docker, &src_cname, None).await;
        assert_eq!(before.status, crate::docker::ContainerStatus::Running);
        let started_at = before.started_at.expect("a started container reports StartedAt");

        let bundle_path = env.dir.path().join("agent.tar.gz");
        export_agent(
            &docker,
            ExportRequest {
                name: &source_name,
                output: &bundle_path,
                core_dir: &env.core_dir,
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

        // What capturing through a commit buys: the export never stopped the agent, and never
        // restarted it either, so the session it was in the middle of is still the same one.
        let after = crate::docker::inspect_container(&docker, &src_cname, None).await;
        assert_eq!(after.status, crate::docker::ContainerStatus::Running);
        assert_eq!(after.started_at.as_deref(), Some(started_at.as_str()), "the export must not restart the agent");

        let outcome = import_agent(
            &docker,
            ImportRequest {
                input: &bundle_path,
                name_override: Some(&target_name),
                env_config: &env.config,
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
        assert_eq!(
            crate::docker::container_status(&docker, &dst_cname).await,
            crate::docker::ContainerStatus::Stopped
        );
        // Constitution landed on the new host side.
        let imported_constitution =
            std::fs::read_to_string(crate::docker::constitution_host_path(&env.config.agents_dir, &target_name))
                .expect("read constitution");
        assert_eq!(imported_constitution, "be kind");

        // No credentials inside the imported container: commit it and reuse the scrub-test probe.
        crate::docker::commit_container_to_image(&docker, &dst_cname, "vesta-export-verify", &target_name)
            .await
            .expect("commit the imported agent");
        assert_no_credentials(&docker, &verify_image, &verify_cname).await;
    }

    /// A bundle whose image entry is a one-file filesystem tar: enough for `docker import` to
    /// build a real image and for the import to create an agent from it, without the minutes a
    /// full agent export costs. What the url leg adds is where the bytes come from, not what
    /// they hold.
    fn tiny_bundle(dir: &Path, agent_name: &str) -> PathBuf {
        let fs_tar = dir.join("fs.tar");
        let file = std::fs::File::create(&fs_tar).expect("create fs tar");
        let mut builder = tar::Builder::new(file);
        let content = b"hello";
        let mut header = gnu_header(content.len() as u64);
        builder.append_data(&mut header, "hello.txt", &content[..]).expect("append");
        builder.into_inner().expect("finish fs tar");

        let manifest = BundleManifest {
            format_version: BUNDLE_FORMAT_VERSION,
            agent_name: agent_name.to_string(),
            vestad_version: env!("CARGO_PKG_VERSION").to_string(),
            created_at: "2026-08-07T00:00:00Z".into(),
            user_desired: crate::settings::UserDesired::Stopped,
            mounts: vec![],
        };
        let bundle = dir.join("served.tar.gz");
        write_bundle(&bundle, &manifest, "be kind", &fs_tar).expect("write bundle");
        bundle
    }

    #[tokio::test]
    #[ignore = "requires Docker"]
    async fn a_bundle_imports_from_a_url_and_leaves_no_download_behind() {
        let docker = test_docker();
        let target_name = format!("exp-url-{}", std::process::id());
        let env = test_agent_env();
        let dst_cname = crate::docker::container_name(&target_name);
        let _net = TestNetwork { name: crate::docker::agent_network_name(&target_name) };
        let _litter = TestLitter {
            containers: vec![dst_cname.clone()],
            images: vec![format!("vesta-restore:{target_name}")],
        };

        let bundle_path = tiny_bundle(env.dir.path(), &target_name);
        let bytes = std::fs::read(&bundle_path).expect("read bundle");
        let router = axum::Router::new().route(
            "/agent.tar.gz",
            axum::routing::get(move || {
                let bytes = bytes.clone();
                async move { bytes }
            }),
        );
        let server = spawn_test_server(router).await;

        let downloaded = download_bundle(&format!("{}/agent.tar.gz", server.base), env.dir.path())
            .await
            .expect("download");
        assert!(downloaded.starts_with(env.dir.path().join("tmp")), "got: {}", downloaded.display());

        let outcome = import_agent(
            &docker,
            ImportRequest {
                input: &downloaded,
                name_override: None,
                env_config: &env.config,
            },
        )
        .await
        .expect("import");
        assert_eq!(outcome.name, target_name, "a bundle imported from a url still names itself");
        assert_eq!(
            crate::docker::container_status(&docker, &dst_cname).await,
            crate::docker::ContainerStatus::Stopped
        );
        let imported_constitution =
            std::fs::read_to_string(crate::docker::constitution_host_path(&env.config.agents_dir, &target_name))
                .expect("read constitution");
        assert_eq!(imported_constitution, "be kind");

        // The download is the caller's temp file, removed once the import that read it is over.
        std::fs::remove_file(&downloaded).expect("the import leaves the download in place");
        assert_download_tmp_empty(env.dir.path());
    }

    #[tokio::test]
    #[ignore = "requires Docker + the local agent image"]
    async fn import_legacy_gzipped_image_creates_and_starts_agent() {
        let docker = test_docker();
        let image = test_agent_image();
        let target_name = format!("exp-legacy-{}", std::process::id());
        let env = test_agent_env();
        let dst_cname = crate::docker::container_name(&target_name);
        let _target_net = TestNetwork { name: crate::docker::agent_network_name(&target_name) };
        let _litter = TestLitter { containers: vec![dst_cname.clone()], images: vec![] };

        // A legacy export: a gzipped `docker save` tar with no manifest.
        let tar_path = env.dir.path().join("legacy-image.tar");
        let save_status = std::process::Command::new("docker")
            .args(["save", "-o", &tar_path.display().to_string(), &image])
            .status()
            .expect("docker save runs");
        assert!(save_status.success());
        let legacy_path = env.dir.path().join("legacy.tar.gz");
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
                env_config: &env.config,
            },
        )
        .await
        .expect("import legacy");
        assert_eq!(outcome.name, target_name);
        assert!(outcome.manifest.is_none());

        // The image tag a legacy file carries is the pre-existing base agent image (docker
        // save/load round-trips the tag unchanged), so nothing here removes an image.
        assert_eq!(
            crate::docker::container_status(&docker, &dst_cname).await,
            crate::docker::ContainerStatus::Running
        );
    }
}
