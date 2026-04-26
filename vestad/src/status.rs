use std::fmt::Write as _;
use std::path::Path;

use serde::Serialize;

use crate::{tunnel, update_check};

const FINGERPRINT_HEX_CHARS: usize = 12;

/// Stable JSON shape returned by `vestad status --json` and `GET /status`.
/// Every field is a primitive or an `Option`; consumers can rely on the field
/// set staying additive across versions.
#[derive(Serialize, Clone, Debug)]
pub struct StatusReport {
    /// Compiled vestad version (matches `CARGO_PKG_VERSION`).
    pub version: String,
    /// Path of the running vestad binary, if the OS can report it.
    pub binary_path: Option<String>,
    /// Latest released version reported by GitHub. `None` when the background
    /// update check has not produced a result yet (e.g. fresh start, network
    /// unreachable). Surface as null in JSON, dash in human output.
    pub latest_version: Option<String>,
    /// True when `latest_version` is strictly greater than `version`. `None`
    /// when `latest_version` is unknown.
    pub update_available: Option<bool>,
    /// HTTPS port vestad is listening on for client connections.
    pub https_port: Option<u16>,
    /// Local URL clients can hit on this machine.
    pub local_url: Option<String>,
    /// Cloudflare tunnel state. Always present; `configured = false` means no
    /// tunnel is set up.
    pub tunnel: TunnelStatus,
    /// systemd unit state (`active` / `inactive` / `failed` / `unknown` /
    /// `not-installed`). Always present.
    pub systemd_state: String,
    /// MainPID reported by systemd, when the unit is running.
    pub systemd_pid: Option<u32>,
    /// First 12 hex chars of `sha256(api_key)`. Stable across runs for the
    /// same key. Used as a non-sensitive identifier.
    pub api_key_fingerprint: Option<String>,
    /// Full API key. Only populated when the caller explicitly asked for
    /// secrets (`vestad status --show-secrets`); `None` everywhere else,
    /// including over HTTP.
    pub api_key: Option<String>,
    /// Number of agents known on disk (one `.env` file per agent under
    /// `~/.config/vesta/vestad/agents/`).
    pub agent_count: usize,
}

/// Tunnel sub-report. Always emitted; `configured = false` means no tunnel.
#[derive(Serialize, Clone, Debug)]
pub struct TunnelStatus {
    /// Whether a tunnel is configured (a `tunnel.json` was found).
    pub configured: bool,
    /// `https://<hostname>` when configured.
    pub url: Option<String>,
    /// FQDN of the tunnel hostname.
    pub hostname: Option<String>,
    /// Cloudflare tunnel id.
    pub tunnel_id: Option<String>,
}

/// Inputs to `gather_status`. Kept as a plain struct so callers (CLI and HTTP
/// handler) can supply whatever they have on hand without coupling to global
/// state.
pub struct StatusInputs<'a> {
    pub config_dir: &'a Path,
    pub https_port: Option<u16>,
    pub api_key: Option<String>,
    pub include_api_key: bool,
    pub latest_version: Option<String>,
    pub binary_path: Option<String>,
    pub systemd_state: String,
    pub systemd_pid: Option<u32>,
}

pub fn gather_status(inputs: StatusInputs<'_>) -> StatusReport {
    let StatusInputs {
        config_dir,
        https_port,
        api_key,
        include_api_key,
        latest_version,
        binary_path,
        systemd_state,
        systemd_pid,
    } = inputs;

    let local_url = https_port.map(|port| format!("http://localhost:{}", port + 1));

    let tunnel_config = tunnel::get_tunnel_config(config_dir);
    let tunnel = match &tunnel_config {
        Some(tc) => TunnelStatus {
            configured: true,
            url: Some(format!("https://{}", tc.hostname)),
            hostname: Some(tc.hostname.clone()),
            tunnel_id: Some(tc.tunnel_id.clone()),
        },
        None => TunnelStatus {
            configured: false,
            url: None,
            hostname: None,
            tunnel_id: None,
        },
    };

    let version = env!("CARGO_PKG_VERSION").to_string();
    let update_available = latest_version
        .as_ref()
        .map(|latest| update_check::version_less_than(&version, latest));

    let api_key_fingerprint = api_key.as_deref().map(fingerprint_api_key);
    let api_key_field = if include_api_key { api_key } else { None };

    let agent_count = count_agents(&config_dir.join("agents"));

    StatusReport {
        version,
        binary_path,
        latest_version,
        update_available,
        https_port,
        local_url,
        tunnel,
        systemd_state,
        systemd_pid,
        api_key_fingerprint,
        api_key: api_key_field,
        agent_count,
    }
}

pub fn fingerprint_api_key(key: &str) -> String {
    let digest = ring::digest::digest(&ring::digest::SHA256, key.as_bytes());
    let mut out = String::with_capacity(FINGERPRINT_HEX_CHARS);
    for byte in digest.as_ref().iter().take(FINGERPRINT_HEX_CHARS / 2) {
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// Resolves the running vestad binary path. `None` when the OS can't report
/// it; trims the `" (deleted)"` suffix Linux appends after self-update.
pub fn current_binary_path() -> Option<String> {
    std::env::current_exe()
        .ok()
        .and_then(|path| path.to_str().map(|raw| raw.trim_end_matches(" (deleted)").to_string()))
}

fn count_agents(agents_dir: &Path) -> usize {
    let Ok(entries) = std::fs::read_dir(agents_dir) else {
        return 0;
    };
    entries
        .flatten()
        .filter(|entry| {
            entry.file_type().map(|file_type| file_type.is_file()).unwrap_or(false)
                && entry
                    .file_name()
                    .to_str()
                    .map(|name| name.ends_with(".env"))
                    .unwrap_or(false)
        })
        .count()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprint_is_stable_and_short() {
        let first = fingerprint_api_key("hunter2");
        let second = fingerprint_api_key("hunter2");
        assert_eq!(first, second);
        assert_eq!(first.len(), FINGERPRINT_HEX_CHARS);
        assert!(first.chars().all(|character| character.is_ascii_hexdigit()));
        assert_ne!(first, fingerprint_api_key("hunter3"));
    }

    #[test]
    fn count_agents_handles_missing_dir() {
        let tmp = tempfile::tempdir().unwrap();
        assert_eq!(count_agents(&tmp.path().join("agents")), 0);
    }

    #[test]
    fn count_agents_counts_only_env_files() {
        let tmp = tempfile::tempdir().unwrap();
        let agents = tmp.path().join("agents");
        std::fs::create_dir_all(&agents).unwrap();
        std::fs::write(agents.join("alpha.env"), "WS_PORT=1\n").unwrap();
        std::fs::write(agents.join("beta.env"), "WS_PORT=2\n").unwrap();
        std::fs::write(agents.join("notes.txt"), "ignore me").unwrap();
        assert_eq!(count_agents(&agents), 2);
    }

    #[test]
    fn gather_status_omits_api_key_when_not_requested() {
        let tmp = tempfile::tempdir().unwrap();
        let report = gather_status(StatusInputs {
            config_dir: tmp.path(),
            https_port: Some(8000),
            api_key: Some("secret".into()),
            include_api_key: false,
            latest_version: Some("99.0.0".into()),
            binary_path: Some("/usr/bin/vestad".into()),
            systemd_state: "active".into(),
            systemd_pid: Some(42),
        });
        assert!(report.api_key.is_none());
        assert_eq!(report.api_key_fingerprint.as_deref(), Some(fingerprint_api_key("secret").as_str()));
        assert_eq!(report.local_url.as_deref(), Some("http://localhost:8001"));
        assert_eq!(report.update_available, Some(true));
        assert_eq!(report.https_port, Some(8000));
        assert!(!report.tunnel.configured);
    }

    #[test]
    fn gather_status_includes_api_key_when_requested() {
        let tmp = tempfile::tempdir().unwrap();
        let report = gather_status(StatusInputs {
            config_dir: tmp.path(),
            https_port: None,
            api_key: Some("secret".into()),
            include_api_key: true,
            latest_version: None,
            binary_path: None,
            systemd_state: "inactive".into(),
            systemd_pid: None,
        });
        assert_eq!(report.api_key.as_deref(), Some("secret"));
        assert!(report.update_available.is_none());
        assert!(report.latest_version.is_none());
    }

    #[test]
    fn json_keys_are_stable() {
        let tmp = tempfile::tempdir().unwrap();
        let report = gather_status(StatusInputs {
            config_dir: tmp.path(),
            https_port: Some(8000),
            api_key: None,
            include_api_key: false,
            latest_version: None,
            binary_path: None,
            systemd_state: "unknown".into(),
            systemd_pid: None,
        });
        let value = serde_json::to_value(&report).unwrap();
        for key in [
            "version",
            "binary_path",
            "latest_version",
            "update_available",
            "https_port",
            "local_url",
            "tunnel",
            "systemd_state",
            "systemd_pid",
            "api_key_fingerprint",
            "api_key",
            "agent_count",
        ] {
            assert!(value.get(key).is_some(), "missing key: {key}");
        }
        for key in ["configured", "url", "hostname", "tunnel_id"] {
            assert!(value["tunnel"].get(key).is_some(), "missing tunnel key: {key}");
        }
    }
}
