//! The box's Vesta Cloud account link.
//!
//! A box holds a Vesta Cloud account when the control plane recognizes its
//! `(server_id, api_key)`. A managed VM gets that identity from cloud-init env
//! (`VESTA_CLOUD_SERVER_ID`); a self-hosted box acquires it through the pairing
//! flow (`/agents/{name}/vesta-cloud/pair`, RFC 8628 device-authorization
//! shape) and persists it here as `<config_dir>/vesta-cloud-account.json`.
//! `resolve_vesta_cloud_identity` is the single answer to "what is this box's
//! Vesta Cloud identity": cloud-init env first, else the persisted pairing.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

pub(crate) const DEFAULT_CONTROL_URL: &str = "https://vesta.run/api";

/// The persisted account link: which control-plane server this box IS, and the
/// control-plane API base it was paired against (staging vs prod).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct VestaCloudAccount {
    pub(crate) server_id: String,
    pub(crate) control_url: String,
}

pub(crate) fn vesta_cloud_account_path(config_dir: &Path) -> PathBuf {
    config_dir.join("vesta-cloud-account.json")
}

/// Load the persisted account link. A missing file is the normal unpaired
/// state; a corrupt file is logged and treated as unpaired (re-pair heals it).
pub(crate) fn load_vesta_cloud_account(config_dir: &Path) -> Option<VestaCloudAccount> {
    let path = vesta_cloud_account_path(config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    match serde_json::from_str(&data) {
        Ok(account) => Some(account),
        Err(err) => {
            tracing::warn!(path = %path.display(), error = %err, "corrupt vesta-cloud-account.json, treating as unpaired");
            None
        }
    }
}

/// Persist the account link (owner-only: it names the box's cloud identity).
pub(crate) fn save_vesta_cloud_account(config_dir: &Path, account: &VestaCloudAccount) {
    crate::settings::save_json_atomic(
        &vesta_cloud_account_path(config_dir),
        account,
        Some(0o600),
    );
}

/// Remove the account link (unpair). A no-op when the file is absent.
pub(crate) fn clear_vesta_cloud_account(config_dir: &Path) {
    let _ = std::fs::remove_file(vesta_cloud_account_path(config_dir));
}

/// The box's Vesta Cloud identity, if any: `(server_id, control_url)`.
/// A MANAGED box answers only from cloud-init env: when the env server id is
/// missing there it has no identity, and a stray `vesta-cloud-account.json`
/// left over from a self-hosted past must never supply one (it would mint
/// tokens for, and open billing of, the old account's row). Only an unmanaged
/// box answers from the pairing file. Pure over its inputs so tests never
/// mutate process env.
pub(crate) fn resolve_vesta_cloud_identity(
    config_dir: &Path,
    cloud_managed: bool,
    env_server_id: Option<String>,
    env_control_url: Option<String>,
) -> Option<(String, Option<String>)> {
    if cloud_managed {
        return env_server_id.map(|server_id| (server_id, env_control_url));
    }
    load_vesta_cloud_account(config_dir).map(|a| (a.server_id, Some(a.control_url)))
}

/// `resolve_vesta_cloud_identity` over the live environment.
pub(crate) fn vesta_cloud_identity(config_dir: &Path) -> Option<(String, Option<String>)> {
    resolve_vesta_cloud_identity(
        config_dir,
        crate::is_cloud_managed(),
        std::env::var("VESTA_CLOUD_SERVER_ID").ok(),
        std::env::var("VESTA_CLOUD_CONTROL_URL").ok(),
    )
}

/// One in-flight pairing attempt, persisted to `<config_dir>/vesta-cloud-pairing.json`
/// so a vestad restart mid-flow can keep polling: the control plane replays a
/// consumed pairing's result to the same `device_code`, and that secret exists
/// nowhere else (it never enters the agent container).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct VestaCloudPairing {
    pub(crate) device_code: String,
    pub(crate) user_code: String,
    pub(crate) verification_url: String,
    pub(crate) interval: u64,
    pub(crate) expires_at_epoch_secs: u64,
}

impl VestaCloudPairing {
    pub(crate) fn is_expired(&self, now_epoch_secs: u64) -> bool {
        now_epoch_secs >= self.expires_at_epoch_secs
    }

    /// Seconds of code lifetime left; what a resumed `pair` reports as
    /// `expires_in` so the skill's poll deadline matches reality.
    pub(crate) fn remaining_secs(&self, now_epoch_secs: u64) -> u64 {
        self.expires_at_epoch_secs.saturating_sub(now_epoch_secs)
    }
}

pub(crate) fn vesta_cloud_pairing_path(config_dir: &Path) -> PathBuf {
    config_dir.join("vesta-cloud-pairing.json")
}

/// Load the persisted in-flight pairing; missing = none, corrupt = warn + none.
pub(crate) fn load_vesta_cloud_pairing(config_dir: &Path) -> Option<VestaCloudPairing> {
    let path = vesta_cloud_pairing_path(config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    match serde_json::from_str(&data) {
        Ok(pairing) => Some(pairing),
        Err(err) => {
            tracing::warn!(path = %path.display(), error = %err, "corrupt vesta-cloud-pairing.json, discarding");
            None
        }
    }
}

/// Persist the in-flight pairing (owner-only: it holds the poll secret).
pub(crate) fn save_vesta_cloud_pairing(config_dir: &Path, pairing: &VestaCloudPairing) {
    crate::settings::save_json_atomic(
        &vesta_cloud_pairing_path(config_dir),
        pairing,
        Some(0o600),
    );
}

/// Remove the in-flight pairing (finished or dead). No-op when absent.
pub(crate) fn clear_vesta_cloud_pairing(config_dir: &Path) {
    let _ = std::fs::remove_file(vesta_cloud_pairing_path(config_dir));
}

/// The control-plane API base to PAIR against: `VESTA_CLOUD_CONTROL_URL` (so a
/// box can pair to staging) or the production default.
pub(crate) fn control_base() -> String {
    std::env::var("VESTA_CLOUD_CONTROL_URL")
        .ok()
        .filter(|v| !v.trim().is_empty())
        .map_or_else(
            || DEFAULT_CONTROL_URL.to_string(),
            |v| v.trim().trim_end_matches('/').to_string(),
        )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn account_roundtrips_with_owner_only_mode() {
        let dir = tempfile::tempdir().expect("tempdir");
        let account = VestaCloudAccount {
            server_id: "srv_123".to_string(),
            control_url: "https://vesta.run/api".to_string(),
        };
        save_vesta_cloud_account(dir.path(), &account);
        assert_eq!(load_vesta_cloud_account(dir.path()), Some(account));

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(vesta_cloud_account_path(dir.path()))
                .expect("metadata")
                .permissions()
                .mode();
            assert_eq!(mode & 0o777, 0o600);
        }
    }

    #[test]
    fn corrupt_account_file_is_unpaired() {
        let dir = tempfile::tempdir().expect("tempdir");
        std::fs::write(vesta_cloud_account_path(dir.path()), "not json").expect("write");
        assert_eq!(load_vesta_cloud_account(dir.path()), None);
    }

    #[test]
    fn clear_removes_the_file_and_tolerates_absence() {
        let dir = tempfile::tempdir().expect("tempdir");
        clear_vesta_cloud_account(dir.path()); // absent: no-op
        save_vesta_cloud_account(
            dir.path(),
            &VestaCloudAccount {
                server_id: "srv".to_string(),
                control_url: "u".to_string(),
            },
        );
        clear_vesta_cloud_account(dir.path());
        assert_eq!(load_vesta_cloud_account(dir.path()), None);
    }

    #[test]
    fn identity_prefers_cloud_env_over_pairing_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        save_vesta_cloud_account(
            dir.path(),
            &VestaCloudAccount {
                server_id: "srv_paired".to_string(),
                control_url: "https://staging.vesta.run/api".to_string(),
            },
        );
        let identity = resolve_vesta_cloud_identity(
            dir.path(),
            true,
            Some("srv_env".to_string()),
            Some("https://vesta.run/api".to_string()),
        );
        assert_eq!(
            identity,
            Some((
                "srv_env".to_string(),
                Some("https://vesta.run/api".to_string())
            ))
        );
    }

    #[test]
    fn identity_falls_back_to_pairing_file_when_unmanaged() {
        let dir = tempfile::tempdir().expect("tempdir");
        save_vesta_cloud_account(
            dir.path(),
            &VestaCloudAccount {
                server_id: "srv_paired".to_string(),
                control_url: "https://staging.vesta.run/api".to_string(),
            },
        );
        let identity = resolve_vesta_cloud_identity(dir.path(), false, None, None);
        assert_eq!(
            identity,
            Some((
                "srv_paired".to_string(),
                Some("https://staging.vesta.run/api".to_string())
            ))
        );
    }

    #[test]
    fn identity_none_when_neither_source_exists() {
        let dir = tempfile::tempdir().expect("tempdir");
        assert_eq!(resolve_vesta_cloud_identity(dir.path(), false, None, None), None);
        assert_eq!(resolve_vesta_cloud_identity(dir.path(), true, None, None), None);
    }

    #[test]
    fn managed_box_without_env_id_never_reads_a_stale_pairing_file() {
        // A managed VM whose cloud-init seeding failed must answer "no
        // identity", not adopt the identity of a self-hosted past.
        let dir = tempfile::tempdir().expect("tempdir");
        save_vesta_cloud_account(
            dir.path(),
            &VestaCloudAccount {
                server_id: "srv_stale".to_string(),
                control_url: "https://vesta.run/api".to_string(),
            },
        );
        assert_eq!(resolve_vesta_cloud_identity(dir.path(), true, None, None), None);
    }

    #[test]
    fn pairing_roundtrips_expires_and_clears() {
        let dir = tempfile::tempdir().expect("tempdir");
        assert_eq!(load_vesta_cloud_pairing(dir.path()), None);

        let pairing = VestaCloudPairing {
            device_code: "d".repeat(64),
            user_code: "BCDF-2345".to_string(),
            verification_url: "https://vesta.run/pair?code=BCDF-2345".to_string(),
            interval: 5,
            expires_at_epoch_secs: 1_000,
        };
        save_vesta_cloud_pairing(dir.path(), &pairing);
        assert_eq!(load_vesta_cloud_pairing(dir.path()), Some(pairing.clone()));

        assert!(!pairing.is_expired(999));
        assert!(pairing.is_expired(1_000));
        assert_eq!(pairing.remaining_secs(400), 600);
        assert_eq!(pairing.remaining_secs(2_000), 0);

        clear_vesta_cloud_pairing(dir.path());
        assert_eq!(load_vesta_cloud_pairing(dir.path()), None);
        clear_vesta_cloud_pairing(dir.path()); // absent: no-op
    }
}
