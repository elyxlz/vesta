//! Everything about updating the gateway itself: the periodic release check that feeds the
//! UpdatePill, the phase model and durable ledger that make an update observable, the orchestrator
//! that drives one update from pre-update snapshots to the restart, and the binary swap it applies.

use std::fmt;

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

#[derive(Clone, Debug)]
pub struct UpdateInfo {
    pub latest: String,
    pub update_available: bool,
}

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
