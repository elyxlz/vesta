//! Everything about updating the gateway itself: the periodic release check that feeds the
//! `UpdatePill`, the durable ledger and boot recovery that make an interrupted update visible, the
//! orchestrator that drives one update from pre-update snapshots to the restart, and the binary swap
//! it applies. The phases it drives, and the slot it claims, live in `operation`.

use std::fmt;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::operation::{ActiveOperation, ActiveUpdate, UpdateInfo, UpdatePhase, UpdateStage};
use crate::state::SharedState;

// Poll GitHub for new releases every 5 hours: often enough that the UpdatePill and a
// power user's manual update see a release promptly. This only governs detection; an
// auto-update is applied later, by the maintenance cycle in the fleet's 4-5am quiet
// window (see serve.rs run_maintenance). The desktop app can force an immediate check
// via POST /version/check.
pub const CHECK_INTERVAL_SECS: u64 = 5 * 60 * 60;
const FETCH_TIMEOUT_SECS: u64 = 10;
const ERROR_SNIPPET_MAX_LEN: usize = 300;
const HTTP_STATUS_SENTINEL: &str = "\n__VESTA_HTTP_STATUS__:";
const CACHE_FILE_NAME: &str = "update-check-cache.json";

use crate::channel::Channel;

// Stable follows the GitHub "latest" alias (excludes prereleases). Beta lists all
// releases (newest first, prereleases included) and takes the newest one.
const GITHUB_RELEASES_LATEST_URL: &str =
    "https://api.github.com/repos/elyxlz/vesta/releases/latest";
const GITHUB_RELEASES_LIST_URL: &str =
    "https://api.github.com/repos/elyxlz/vesta/releases?per_page=10";

pub fn check_once(channel: Channel) -> Result<UpdateInfo, String> {
    let latest = fetch_latest_release_tag(Some(FETCH_TIMEOUT_SECS), channel)?;
    let update_available = version_less_than(env!("CARGO_PKG_VERSION"), &latest);

    Ok(UpdateInfo {
        latest,
        update_available,
    })
}

pub(crate) fn version_less_than(a: &str, b: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> { v.split('.').filter_map(|s| s.parse().ok()).collect() };
    parse(a) < parse(b)
}

pub fn fetch_latest_tag(channel: Channel) -> Option<String> {
    fetch_latest_release_tag(Some(FETCH_TIMEOUT_SECS), channel).ok()
}

// Persisted across restarts so the conditional request below keeps working
// after vestad bounces. GitHub does not count a 304 response against the
// unauthenticated rate limit, so a stored ETag makes steady-state polling free.
#[derive(serde::Serialize, serde::Deserialize, Default)]
struct CacheEntry {
    etag: String,
    tag: String,
}

fn cache_path(channel: Channel) -> Option<std::path::PathBuf> {
    // Per-channel cache file: stable and beta query different URLs with different
    // ETags, so they must not share a conditional-request cache.
    let file = match channel {
        Channel::Stable => CACHE_FILE_NAME.to_string(),
        Channel::Beta => format!("{CACHE_FILE_NAME}.beta"),
    };
    crate::paths::config_dir().map(|dir| dir.join(file))
}

fn read_cache(channel: Channel) -> Option<CacheEntry> {
    let path = cache_path(channel)?;
    let contents = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&contents).ok()
}

fn write_cache(channel: Channel, etag: &str, tag: &str) {
    let Some(path) = cache_path(channel) else {
        return;
    };
    if let Some(parent) = path.parent() {
        if std::fs::create_dir_all(parent).is_err() {
            return;
        }
    }
    let entry = CacheEntry {
        etag: etag.to_string(),
        tag: tag.to_string(),
    };
    if let Ok(json) = serde_json::to_string(&entry) {
        let _ = std::fs::write(path, json);
    }
}

fn fetch_latest_release_tag(timeout_secs: Option<u64>, channel: Channel) -> Result<String, String> {
    let cache = read_cache(channel);

    // Dump response headers to a temp file (portable across curl versions,
    // unlike `-w %header{etag}`) so we can read the ETag without parsing it out
    // of the body, which contains release notes with blank lines.
    let header_file =
        std::env::temp_dir().join(format!("vesta-update-headers-{}.txt", std::process::id()));

    // Omit curl's `-f` so HTTP errors still return a body. This surfaces
    // GitHub's rate-limit message to the caller instead of collapsing every
    // failure into a generic error.
    let mut args: Vec<String> = vec![
        "-sSL".into(),
        "-H".into(),
        "Accept: application/vnd.github+json".into(),
        "-H".into(),
        "User-Agent: vesta-release-check".into(),
        "-D".into(),
        header_file.to_string_lossy().into_owned(),
        "-w".into(),
        format!("{HTTP_STATUS_SENTINEL}%{{http_code}}"),
    ];
    if let Some(entry) = &cache {
        if !entry.etag.is_empty() {
            args.push("-H".into());
            args.push(format!("If-None-Match: {}", entry.etag));
        }
    }
    if let Some(t) = timeout_secs {
        args.push("--connect-timeout".into());
        args.push(t.to_string());
        args.push("--max-time".into());
        args.push(t.to_string());
    }
    let url = match channel {
        Channel::Stable => GITHUB_RELEASES_LATEST_URL,
        Channel::Beta => GITHUB_RELEASES_LIST_URL,
    };
    args.push(url.into());

    let output = std::process::Command::new("curl")
        .args(&args)
        .output()
        .map_err(|e| format!("failed to spawn curl: {e}"))?;

    let headers = std::fs::read_to_string(&header_file).unwrap_or_default();
    let _ = std::fs::remove_file(&header_file);

    if !output.status.success() {
        let code = output
            .status
            .code().map_or_else(|| "signal".into(), |c| c.to_string());
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "curl failed (exit {code}): {}",
            snippet(stderr.trim())
        ));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let (body, status) = match stdout.rsplit_once(HTTP_STATUS_SENTINEL) {
        Some((body, status)) => (body, status.trim()),
        None => return Err("curl output missing HTTP status sentinel".into()),
    };

    let status_code: u16 = status
        .parse()
        .map_err(|_| format!("unparseable HTTP status {status:?}"))?;

    // 304 Not Modified: the release is unchanged since our last check and this
    // response did not cost us a rate-limit unit. Reuse the cached tag.
    if status_code == 304 {
        match cache {
            Some(entry) if !entry.tag.is_empty() => return Ok(entry.tag),
            _ => return Err("received 304 but no cached tag available".into()),
        }
    }

    if !(200..300).contains(&status_code) {
        return Err(format!("HTTP {status_code}: {}", snippet(body.trim())));
    }

    let tag = extract_tag(body, channel)?;

    if let Some(etag) = parse_etag(&headers) {
        write_cache(channel, &etag, &tag);
    }

    Ok(tag)
}

/// Pull the version tag out of a GitHub releases response. Stable parses the single
/// release object returned by the `/latest` alias; beta parses the releases array
/// and takes the first (newest) entry, prereleases included.
fn extract_tag(body: &str, channel: Channel) -> Result<String, String> {
    let data: serde_json::Value =
        serde_json::from_str(body).map_err(|e| format!("failed to parse response JSON: {e}"))?;
    let release = match channel {
        Channel::Stable => &data,
        Channel::Beta => data
            .as_array()
            .and_then(|releases| releases.first())
            .ok_or_else(|| format!("no releases in list response: {}", snippet(body.trim())))?,
    };
    let tag = release
        .get("tag_name")
        .ok_or_else(|| format!("response missing tag_name: {}", snippet(body.trim())))?
        .as_str()
        .ok_or_else(|| "tag_name is not a string".to_string())?
        .trim()
        .trim_start_matches('v');
    if tag.is_empty() {
        return Err("tag_name is empty".into());
    }
    Ok(tag.to_string())
}

fn parse_etag(headers: &str) -> Option<String> {
    // With `-L`, headers may contain multiple response blocks (one per hop).
    // Take the last ETag so it matches the final 200 response.
    headers
        .lines()
        .rev()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            if name.trim().eq_ignore_ascii_case("etag") {
                Some(value.trim().to_string())
            } else {
                None
            }
        })
        .filter(|etag| !etag.is_empty())
}

fn snippet(s: &str) -> String {
    if s.is_empty() {
        return "<empty>".into();
    }
    match s.char_indices().nth(ERROR_SNIPPET_MAX_LEN) {
        Some((end, _)) => format!("{}…", &s[..end]),
        None => s.to_string(),
    }
}

// --- Phases, ledger, boot recovery ---

// Beside settings.json in the config dir. Present only while an update is in flight, which is what
// makes it the boot-time record: a vestad that comes up and finds one knows the update it describes
// either landed (Restarting on the target version) or died somewhere.
const LEDGER_FILE_NAME: &str = "update.json";

/// The durable record of an in-flight update, rewritten at every phase transition and deleted once a
/// terminal state is surfaced. The only state that survives the restart the update itself performs.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
pub struct UpdateLedger {
    pub target_version: String,
    pub phase: UpdatePhase,
    pub warnings: Vec<String>,
}

fn ledger_path(config_dir: &Path) -> std::path::PathBuf {
    config_dir.join(LEDGER_FILE_NAME)
}

/// The recorded update, or None when there is none or the file cannot be read as one. An unreadable
/// ledger is treated as absent on purpose: recovery then falls through to a normal boot instead of
/// blocking on a file nobody can act on.
pub fn read_ledger(config_dir: &Path) -> Option<UpdateLedger> {
    let contents = std::fs::read_to_string(ledger_path(config_dir)).ok()?;
    serde_json::from_str(&contents).ok()
}

/// Write the ledger atomically, best-effort: a failed write costs the boot-time recovery signal,
/// never the update itself (`save_json_atomic` logs it and proceeds).
pub fn write_ledger(config_dir: &Path, ledger: &UpdateLedger) {
    crate::settings::save_json_atomic(&ledger_path(config_dir), ledger, None);
}

pub fn clear_ledger(config_dir: &Path) {
    let path = ledger_path(config_dir);
    if path.exists() && std::fs::remove_file(&path).is_err() {
        tracing::warn!("could not clear the update ledger");
    }
}

/// What this boot must do about the update the ledger describes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BootRecovery {
    Normal,
    Updated {
        version: String,
        warnings: Vec<String>,
    },
    Interrupted {
        target_version: String,
        during: UpdateStage,
    },
}

/// Read the ledger once and decide: no ledger is a normal boot; a ledger whose target is the
/// version now running is the update landing, whatever step wrote it last (a death between the
/// binary swap and the `Restarting` write still boots the new binary); anything else is an update
/// that died. The ledger is always cleared, so a boot never inherits the previous boot's verdict.
pub fn recover_at_boot(config_dir: &Path, running_version: &str) -> BootRecovery {
    let Some(ledger) = read_ledger(config_dir) else {
        return BootRecovery::Normal;
    };
    clear_ledger(config_dir);
    if running_version == ledger.target_version {
        return BootRecovery::Updated {
            version: ledger.target_version,
            warnings: ledger.warnings,
        };
    }
    BootRecovery::Interrupted {
        during: ledger.phase.stage(),
        target_version: ledger.target_version,
    }
}

// --- Orchestrator ---

/// What asking for an update did. "Nothing started" has two very different causes, so each says
/// which one it was rather than leaving the caller to guess.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpdateStart {
    Started { target_version: String },
    AlreadyCurrent { version: String },
    ReleaseCheckFailed { error: String },
}

/// Start an update, unless one already holds the operation slot (then the live phase comes back as
/// the error). The update itself runs on its own task, so the caller returns immediately and every
/// client watches the phases on `/sync`.
pub async fn start_update(state: SharedState) -> Result<UpdateStart, UpdatePhase> {
    let target = match resolve_target(&state).await {
        Target::Newer(version) => version,
        Target::Current(version) => {
            // A projected failure describing an update that is moot (or, per `recover_at_boot`'s
            // edge, actually landed) must not outlive this answer: an "already current" retry has
            // nothing left to retry, so it doubles as the dismiss.
            state.operation.dismiss();
            return Ok(UpdateStart::AlreadyCurrent { version });
        }
        Target::Unknown(error) => return Ok(UpdateStart::ReleaseCheckFailed { error }),
    };
    state.operation.claim(ActiveOperation::Update(ActiveUpdate {
        target_version: target.clone(),
        phase: UpdatePhase::Snapshotting { agent: None, done: 0, total: 0 },
        warnings: Vec::new(),
    }))?;
    let run = UpdateRun {
        state,
        target: target.clone(),
    };
    // Durable from the moment the caller is told "started": a death before the first phase
    // transition still surfaces as an interrupted update at the next boot.
    run.advance(UpdatePhase::Snapshotting {
        agent: None,
        done: 0,
        total: 0,
    });
    tokio::spawn(run_update(run));
    Ok(UpdateStart::Started {
        target_version: target,
    })
}

/// The release an update would install: a newer one, the one already running, or none because the
/// check could not answer.
enum Target {
    Newer(String),
    Current(String),
    Unknown(String),
}

/// Resolve the target release with a fresh check on the channel now in effect: the periodic poll's
/// cached answer can be hours old and can predate a channel switch, so an install never trusts it.
async fn resolve_target(state: &SharedState) -> Target {
    match refresh_update_info(state).await {
        Ok(info) if info.update_available => Target::Newer(info.latest),
        Ok(info) => {
            tracing::info!(latest = %info.latest, "gateway is already current; nothing to update");
            Target::Current(env!("CARGO_PKG_VERSION").to_string())
        }
        Err(error) => {
            tracing::warn!(%error, "cannot start an update: release check failed");
            Target::Unknown(error)
        }
    }
}

/// One release check, run off the runtime, its answer remembered in the shared slot. The periodic
/// poll, the manual `/version/check`, a channel switch, and an update start all go through this one
/// owner, so the check the `UpdatePill` reads and the one an update starts from are the same answer.
pub async fn refresh_update_info(state: &SharedState) -> Result<UpdateInfo, String> {
    let channel = crate::channel::Channel::resolve(&state.settings.read().await.channel);
    match tokio::task::spawn_blocking(move || check_once(channel)).await {
        Ok(Ok(info)) => {
            *state.update_info.lock().await = Some(info.clone());
            Ok(info)
        }
        Ok(Err(error)) => Err(error),
        Err(error) => Err(error.to_string()),
    }
}

/// One update in flight: the state it drives and the identity it records at every transition.
struct UpdateRun {
    state: SharedState,
    target: String,
}

impl UpdateRun {
    /// Move to `phase` in one place: the projected operation and the durable ledger never disagree.
    fn advance(&self, phase: UpdatePhase) {
        tracing::info!(target_version = %self.target, phase = ?phase, "gateway update phase");
        let warnings = self.state.operation.set_phase(phase.clone());
        write_ledger(
            &self.state.env_config.config_dir,
            &UpdateLedger {
                target_version: self.target.clone(),
                phase,
                warnings,
            },
        );
    }

    /// End the update loudly: the failure keeps projecting until retried or dismissed, and only
    /// then the ledger goes (this vestad reported the failure itself, so the next boot has nothing
    /// to recover; a death between the two leaves the ledger for that boot to report).
    fn fail(&self, during: UpdateStage, error: String) {
        tracing::error!(target_version = %self.target, %during, %error, "gateway update failed");
        self.state
            .operation
            .set_phase(UpdatePhase::Failed { during, error });
        clear_ledger(&self.state.env_config.config_dir);
    }

    /// End the update quietly: nothing left to watch, nothing left to recover.
    fn finish(&self) {
        clear_ledger(&self.state.env_config.config_dir);
        self.state.operation.clear();
    }
}

async fn run_update(run: UpdateRun) {
    let backup_settings = run.state.settings.read().await.backup.clone();
    let agents = crate::backup::list_agent_names(&run.state.docker).await;
    let kind = crate::maintenance::PassKind::pre_update_from_current();
    let now_epoch = crate::time_utils::now_epoch_secs();
    run_snapshots(
        &agents,
        |phase| run.advance(phase),
        |warning| run.state.operation.warn(warning),
        |agent| {
            let (state, kind, settings) = (&run.state, &kind, &backup_settings);
            async move { crate::maintenance::snapshot_agent(state, &agent, kind, settings, now_epoch).await }
        },
    )
    .await;

    run.advance(UpdatePhase::Applying);
    let tag = run.target.clone();
    match tokio::task::spawn_blocking(move || update_binary(&tag)).await {
        Ok(Ok(())) => {}
        Ok(Err(error)) => return run.fail(UpdateStage::Applying, error.to_string()),
        Err(error) => return run.fail(UpdateStage::Applying, error.to_string()),
    }

    // Without systemd nothing can restart this process, so the swapped binary takes effect the next
    // time the user starts vestad. That is the end of the update, not a pending restart: leaving a
    // `Restarting` ledger behind would make the next boot report an interruption that never happened.
    if !crate::systemd::is_active() {
        tracing::info!(target_version = %run.target, "gateway binary updated; run 'vestad' to start it");
        return run.finish();
    }
    run.advance(UpdatePhase::Restarting);
    match tokio::task::spawn_blocking(crate::systemd::restart).await {
        Ok(Ok(())) => {}
        Ok(Err(error)) => run.fail(UpdateStage::Restarting, error),
        Err(error) => run.fail(UpdateStage::Restarting, error.to_string()),
    }
}

/// Snapshot each agent in turn, reporting progress and warnings as they happen so the update
/// screen shows them live. A failure never blocks the update: the agent keeps whatever rollback
/// point it already had, and a snapshot that runs too long is killed and reported the same way by
/// the pre-update timeout restic owns (`restic.rs`). Sequential, so the reported progress is one
/// honest "backing up axel 2/4" rather than several at once.
async fn run_snapshots<Snapshot, Snapshotting>(
    agents: &[String],
    progress: impl Fn(UpdatePhase),
    warn: impl Fn(String),
    snapshot: Snapshot,
) where
    Snapshot: Fn(String) -> Snapshotting,
    Snapshotting: std::future::Future<Output = Result<(), crate::docker::DockerError>>,
{
    let total = u32::try_from(agents.len()).unwrap_or(u32::MAX);
    for (index, agent) in agents.iter().enumerate() {
        progress(UpdatePhase::Snapshotting {
            agent: Some(agent.clone()),
            done: u32::try_from(index).unwrap_or(u32::MAX),
            total,
        });
        if let Err(error) = snapshot(agent.clone()).await {
            warn(format!("{agent}: backup failed ({error})"));
        }
    }
}

// --- Binary swap ---

#[derive(Debug)]
pub enum UpdateError {
    UnsupportedArch(String),
    Download(String),
    Extract(String),
    Replace(String),
}

impl fmt::Display for UpdateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedArch(arch) => write!(f, "unsupported architecture: {arch}"),
            Self::Download(msg) => write!(f, "failed to download update: {msg}"),
            Self::Extract(msg) => write!(f, "failed to extract update: {msg}"),
            Self::Replace(msg) => write!(f, "failed to replace binary: {msg}"),
        }
    }
}

pub struct UpdateOutcome {
    pub updated: bool,
    pub restarted: bool,
    pub current: String,
    pub latest: String,
}

/// Downloads the latest vestad binary from GitHub, replaces the current binary,
/// and restarts the systemd service. Agent code and container restarts are
/// handled on the next vestad startup.
/// No-op when the running version is already at or above the latest release on the
/// given channel. Channel switching never downgrades: a stable channel whose latest
/// is older than the running (beta) version is simply a no-op.
pub fn perform_update(channel: crate::channel::Channel) -> Result<UpdateOutcome, UpdateError> {
    let current = env!("CARGO_PKG_VERSION").to_string();
    let latest = fetch_latest_tag(channel)
        .ok_or_else(|| UpdateError::Download("cannot determine latest version".into()))?;

    if !version_less_than(&current, &latest) {
        tracing::info!(current = %current, latest = %latest, "already up to date, skipping");
        return Ok(UpdateOutcome {
            updated: false,
            restarted: false,
            current,
            latest,
        });
    }

    tracing::info!(tag = %latest, "starting update");

    update_binary(&latest)?;

    // Don't reinstall the systemd service here — self-replace puts the new
    // binary at the same path, so the ExecStart line doesn't change. And
    // reading /proc/self/exe after self-replace returns the path with
    // " (deleted)" appended, which would break the service file.
    // The new binary calls ensure_service_installed() on startup if needed.

    let restarted = if crate::systemd::is_active() {
        tracing::info!("restarting vestad...");
        if let Err(e) = crate::systemd::restart() {
            tracing::error!("failed to restart: {e}");
        }
        true
    } else {
        tracing::info!("updated. run 'vestad' to start.");
        false
    };

    Ok(UpdateOutcome {
        updated: true,
        restarted,
        current,
        latest,
    })
}

fn update_binary(tag: &str) -> Result<(), UpdateError> {
    let target = match std::env::consts::ARCH {
        "x86_64" => "x86_64-unknown-linux-gnu",
        "aarch64" => "aarch64-unknown-linux-gnu",
        other => return Err(UpdateError::UnsupportedArch(other.to_string())),
    };

    let archive = format!("vestad-{target}.tar.gz");
    // Download from the resolved tag's release, not the `/latest/` alias: beta tags
    // are prereleases that `/latest/` never points at, and a pinned tag also avoids
    // racing a concurrent release that moves `latest`.
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/download/v{tag}/{archive}"
    );
    let tmp = format!("/tmp/vestad-update-{}", std::process::id());
    std::fs::create_dir_all(&tmp).ok();

    tracing::info!(tag = %tag, "downloading vestad binary");
    let status = std::process::Command::new("curl")
        .args(["-fsSL", "-o", &format!("{tmp}/{archive}"), &url])
        .status();
    if !status.is_ok_and(|s| s.success()) {
        std::fs::remove_dir_all(&tmp).ok();
        return Err(UpdateError::Download("curl failed".into()));
    }

    let status = std::process::Command::new("tar")
        .args(["-xzf", &format!("{tmp}/{archive}"), "-C", &tmp])
        .status();
    if !status.is_ok_and(|s| s.success()) {
        std::fs::remove_dir_all(&tmp).ok();
        return Err(UpdateError::Extract("tar failed".into()));
    }

    let new_binary = format!("{tmp}/vestad");
    self_replace::self_replace(&new_binary).map_err(|e| UpdateError::Replace(e.to_string()))?;

    std::fs::remove_dir_all(&tmp).ok();
    tracing::info!("vestad binary replaced successfully");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ledger_of(phase: UpdatePhase) -> UpdateLedger {
        UpdateLedger {
            target_version: "0.1.190".into(),
            phase,
            warnings: vec!["axel: snapshot timed out".into()],
        }
    }

    #[test]
    fn a_ledger_round_trips_through_the_config_dir() {
        let dir = tempfile::tempdir().expect("tempdir");
        assert_eq!(read_ledger(dir.path()), None);

        let ledger = ledger_of(UpdatePhase::Snapshotting {
            agent: Some("axel".into()),
            done: 1,
            total: 4,
        });
        write_ledger(dir.path(), &ledger);
        assert_eq!(read_ledger(dir.path()), Some(ledger));

        clear_ledger(dir.path());
        assert_eq!(read_ledger(dir.path()), None);
        // Clearing an absent ledger is a no-op, not an error.
        clear_ledger(dir.path());
    }

    #[test]
    fn an_unparseable_ledger_reads_as_absent() {
        let dir = tempfile::tempdir().expect("tempdir");
        std::fs::write(dir.path().join(LEDGER_FILE_NAME), "{ not json").expect("write");
        assert_eq!(read_ledger(dir.path()), None);
    }

    #[test]
    fn boot_recovery_reads_the_ledger_and_always_clears_it() {
        let updated = BootRecovery::Updated {
            version: "0.1.190".into(),
            warnings: vec!["axel: snapshot timed out".into()],
        };
        let cases = [
            (None, "0.1.190", BootRecovery::Normal),
            // Running the target version is the update landing, whatever step wrote the ledger
            // last: a death between the binary swap and the Restarting write still boots new.
            (Some(UpdatePhase::Restarting), "0.1.190", updated.clone()),
            (Some(UpdatePhase::Applying), "0.1.190", updated),
            // Still on the old version: the update died on the recorded step.
            (
                Some(UpdatePhase::Snapshotting { agent: Some("axel".into()), done: 1, total: 4 }),
                "0.1.189",
                BootRecovery::Interrupted {
                    target_version: "0.1.190".into(),
                    during: UpdateStage::Snapshotting,
                },
            ),
            (
                Some(UpdatePhase::Applying),
                "0.1.189",
                BootRecovery::Interrupted {
                    target_version: "0.1.190".into(),
                    during: UpdateStage::Applying,
                },
            ),
        ];
        for (phase, running_version, expected) in cases {
            let dir = tempfile::tempdir().expect("tempdir");
            if let Some(phase) = phase {
                write_ledger(dir.path(), &ledger_of(phase));
            }
            assert_eq!(recover_at_boot(dir.path(), running_version), expected);
            assert_eq!(read_ledger(dir.path()), None, "recovery always clears the ledger");
        }
    }

    #[test]
    fn a_restarting_ledger_on_the_old_version_reads_as_interrupted() {
        // The binary swap or the service restart never landed: the running version is still the old
        // one, so this boot is not the updated one the ledger was written for.
        let dir = tempfile::tempdir().expect("tempdir");
        write_ledger(dir.path(), &ledger_of(UpdatePhase::Restarting));
        assert_eq!(
            recover_at_boot(dir.path(), "0.1.189"),
            BootRecovery::Interrupted {
                target_version: "0.1.190".into(),
                during: UpdateStage::Restarting,
            }
        );
    }

    #[tokio::test]
    async fn a_failed_snapshot_warns_live_and_the_pass_continues() {
        let agents = ["axel".to_string(), "mona".to_string(), "scout".to_string()];
        let phases = std::sync::Mutex::new(Vec::new());
        let warnings = std::sync::Mutex::new(Vec::new());
        run_snapshots(
            &agents,
            |phase| phases.lock().unwrap_or_else(std::sync::PoisonError::into_inner).push(phase),
            |warning| {
                warnings.lock().unwrap_or_else(std::sync::PoisonError::into_inner).push(warning);
            },
            |agent| async move {
                match agent.as_str() {
                    // What a wedged export looks like here: restic's pre-update budget killed it.
                    "axel" => Err(crate::docker::DockerError::Failed("backup timed out after 900s".into())),
                    "mona" => Err(crate::docker::DockerError::Failed("disk full".into())),
                    _ => Ok(()),
                }
            },
        )
        .await;

        let warnings = warnings.into_inner().unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(warnings.len(), 2, "one warning each for the timeout and the failure");
        assert!(warnings[0].contains("axel"));
        assert!(warnings[0].contains("timed out"));
        assert!(warnings[1].contains("mona"), "the pass carried on past the failed agent");
        assert!(warnings[1].contains("disk full"));

        let phases = phases.into_inner().unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(
            phases,
            vec![
                UpdatePhase::Snapshotting { agent: Some("axel".into()), done: 0, total: 3 },
                UpdatePhase::Snapshotting { agent: Some("mona".into()), done: 1, total: 3 },
                UpdatePhase::Snapshotting { agent: Some("scout".into()), done: 2, total: 3 },
            ]
        );
    }

    #[test]
    fn version_less_than_compares_numerically() {
        assert!(version_less_than("0.1.132", "0.1.141"));
        assert!(version_less_than("0.1.9", "0.1.10"));
        assert!(!version_less_than("0.1.141", "0.1.132"));
        assert!(!version_less_than("0.1.141", "0.1.141"));
    }

    #[test]
    fn snippet_truncates_long_strings() {
        let long = "a".repeat(1000);
        let out = snippet(&long);
        assert!(out.ends_with('…'));
        assert!(out.len() <= ERROR_SNIPPET_MAX_LEN + 4);
    }

    #[test]
    fn snippet_passes_short_strings_through() {
        assert_eq!(snippet("hi"), "hi");
        assert_eq!(snippet(""), "<empty>");
    }

    #[test]
    fn parse_etag_reads_header_case_insensitively() {
        let headers = "HTTP/2 200\r\ndate: now\r\nETag: \"abc123\"\r\n\r\n";
        assert_eq!(parse_etag(headers), Some("\"abc123\"".into()));
    }

    #[test]
    fn parse_etag_takes_last_block_on_redirect() {
        let headers = "HTTP/2 301\r\netag: \"old\"\r\n\r\nHTTP/2 200\r\netag: \"new\"\r\n\r\n";
        assert_eq!(parse_etag(headers), Some("\"new\"".into()));
    }

    #[test]
    fn parse_etag_returns_none_when_absent() {
        assert_eq!(parse_etag("HTTP/2 200\r\ndate: now\r\n\r\n"), None);
    }

    #[test]
    fn extract_tag_stable_reads_single_object() {
        let body = r#"{"tag_name": "v0.5.4", "prerelease": false}"#;
        assert_eq!(extract_tag(body, Channel::Stable).unwrap(), "0.5.4");
    }

    #[test]
    fn extract_tag_beta_reads_newest_of_list() {
        // GitHub returns the list newest-first; beta takes the first entry even
        // when it is a prerelease ahead of the latest promoted release.
        let body = r#"[
            {"tag_name": "v0.6.0", "prerelease": true},
            {"tag_name": "v0.5.4", "prerelease": false}
        ]"#;
        assert_eq!(extract_tag(body, Channel::Beta).unwrap(), "0.6.0");
    }

    #[test]
    fn extract_tag_beta_errors_on_empty_list() {
        assert!(extract_tag("[]", Channel::Beta).is_err());
    }

    #[test]
    fn cache_path_differs_per_channel() {
        let stable = cache_path(Channel::Stable);
        let beta = cache_path(Channel::Beta);
        if let (Some(stable), Some(beta)) = (stable, beta) {
            assert_ne!(stable, beta);
        }
    }
}
