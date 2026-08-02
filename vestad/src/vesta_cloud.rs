//! The box's Vesta Cloud account link.
//!
//! A box holds a Vesta Cloud account when the control plane recognizes its
//! `(server_id, api_key)`. A managed VM gets that identity from cloud-init env
//! (`VESTA_CLOUD_SERVER_ID`); a self-hosted box acquires it through the pairing
//! flow (RFC 8628 device-authorization shape, daemon routes `/vesta-cloud/*`
//! or the `vestad vesta-cloud login` CLI) and persists it here as
//! `<config_dir>/vesta-cloud-account.json`.
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

// ---------------------------------------------------------------------------
// The pairing flow core — ONE implementation, three frontends: the daemon's
// `/vesta-cloud/*` HTTP surface (apps + agents), `vestad login`/`logout` (the
// owner at the host shell), and nothing else. Every frontend goes through the
// functions below; none re-implements the control-plane exchange.
// ---------------------------------------------------------------------------

const HTTP_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

#[derive(serde::Deserialize)]
struct PairStartResponse {
    user_code: String,
    verification_url: String,
    device_code: String,
    interval: u64,
    expires_in: u64,
}

pub(crate) enum PairStartError {
    /// The control plane already recognizes this box's key as a live server.
    AlreadyPaired,
    /// A non-2xx the caller should surface (status + control-plane error text).
    Control(String),
    /// Transport failure (control plane unreachable / bad response shape).
    Transport(String),
}

pub(crate) enum PollOutcome {
    Pending,
    Linked { server_id: String, control_url: String },
    /// Terminal control-plane refusal; `gone` = the code expired (HTTP 410).
    Refused { gone: bool, reason: String },
}

pub(crate) enum UnpairOutcome {
    /// The registration was retired (or was already gone server-side).
    Unpaired { already_gone: bool },
    /// The control plane rejected the identity token; the link must be kept.
    IdentityRejected,
}

/// The current in-flight pairing, if any: loaded from its file, with an expired
/// one dropped (file removed). The FILE is the single source of truth so the
/// daemon surface, the host CLI, and a restarted vestad all see the same flow.
pub(crate) fn current_vesta_cloud_pairing(
    config_dir: &Path,
    now_epoch_secs: u64,
) -> Option<VestaCloudPairing> {
    let pairing = load_vesta_cloud_pairing(config_dir)?;
    if pairing.is_expired(now_epoch_secs) {
        clear_vesta_cloud_pairing(config_dir);
        return None;
    }
    Some(pairing)
}

/// `vestad vesta-cloud login`: pair this box to a Vesta Cloud account. Runs ON
/// THE HOST as the owner (the `api_key` never leaves this process), shows the
/// code + link, and blocks until the owner approves in their signed-in browser.
/// An in-flight pairing persists to `vesta-cloud-pairing.json`, so an
/// interrupted login resumes its code (the control plane replays a consumed
/// pairing's result).
pub(crate) fn run_login(config_dir: &Path) -> Result<(), String> {
    if crate::is_cloud_managed() {
        return Err("this box is already managed by Vesta Cloud; it has its identity from provisioning".to_string());
    }
    if load_vesta_cloud_account(config_dir).is_some() {
        return Err("already paired to a Vesta Cloud account. run `vestad vesta-cloud logout` first to unpair".to_string());
    }
    let api_key = crate::serve::ensure_api_key(config_dir)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("failed to start async runtime: {e}"))?;
    runtime.block_on(login_flow(config_dir, &api_key))
}

async fn login_flow(config_dir: &Path, api_key: &str) -> Result<(), String> {
    let client = reqwest::Client::new();
    let pairing = start_or_resume_pairing(&client, config_dir, api_key)
        .await
        .map_err(|e| match e {
            PairStartError::AlreadyPaired => "the control plane already recognizes this box's key as a live server. if your account page shows this box, unpair it there first".to_string(),
            PairStartError::Control(msg) | PairStartError::Transport(msg) => msg,
        })?;

    let now = crate::time_utils::now_epoch_secs();
    let minutes_left = pairing.remaining_secs(now).div_ceil(60);
    eprintln!();
    eprintln!(
        "  pairing code: {}",
        crate::status::paint("1", &pairing.user_code)
    );
    eprintln!(
        "  open {} while signed in and approve the link",
        crate::status::paint("1", &pairing.verification_url)
    );
    eprintln!("  waiting for approval (this code lives about {minutes_left} more minutes)...");
    eprintln!();

    let interval = std::time::Duration::from_secs(pairing.interval.max(1));
    loop {
        if crate::time_utils::now_epoch_secs() >= pairing.expires_at_epoch_secs {
            clear_vesta_cloud_pairing(config_dir);
            return Err("the code expired before it was approved. run `vestad vesta-cloud login` again for a fresh one".to_string());
        }
        // A transient network error mid-wait must not abort the flow the owner
        // is completing in the browser; keep polling until the code's deadline.
        match poll_pairing(&client, config_dir, &pairing.device_code).await {
            Ok(PollOutcome::Linked { .. }) => {
                eprintln!(
                    "  {} paired to your Vesta Cloud account",
                    crate::status::paint("32", "✓")
                );
                return Ok(());
            }
            Ok(PollOutcome::Refused { reason, .. }) => {
                return Err(format!("pairing refused: {reason}"));
            }
            Ok(PollOutcome::Pending) | Err(_) => tokio::time::sleep(interval).await,
        }
    }
}

/// Open a pairing with the control plane (or resume the unexpired in-flight
/// one, so retries never burn a code the owner is already typing). On a fresh
/// start the pairing is persisted before it is returned.
pub(crate) async fn start_or_resume_pairing(
    client: &reqwest::Client,
    config_dir: &Path,
    api_key: &str,
) -> Result<VestaCloudPairing, PairStartError> {
    let now = crate::time_utils::now_epoch_secs();
    if let Some(pairing) = current_vesta_cloud_pairing(config_dir, now) {
        return Ok(pairing);
    }
    let base = control_base();
    let response = client
        .post(format!("{base}/pair/start"))
        .timeout(HTTP_TIMEOUT)
        .json(&serde_json::json!({
            "api_key": api_key,
            "box_name": crate::tunnel::gethostname(),
        }))
        .send()
        .await
        .map_err(|e| {
            PairStartError::Transport(format!("could not reach the Vesta Cloud control plane: {e}"))
        })?;
    let status = response.status();
    let body: serde_json::Value = response.json().await.map_err(|e| {
        PairStartError::Transport(format!("invalid pairing start response: {e}"))
    })?;
    if !status.is_success() {
        let error = body.get("error").and_then(|v| v.as_str()).unwrap_or("");
        if error == "already_paired" {
            return Err(PairStartError::AlreadyPaired);
        }
        return Err(PairStartError::Control(format!(
            "control plane returned {status}: {error}"
        )));
    }
    let start: PairStartResponse = serde_json::from_value(body).map_err(|e| {
        PairStartError::Transport(format!("invalid pairing start response: {e}"))
    })?;
    let pairing = VestaCloudPairing {
        device_code: start.device_code,
        user_code: start.user_code,
        verification_url: start.verification_url,
        interval: start.interval,
        expires_at_epoch_secs: crate::time_utils::now_epoch_secs() + start.expires_in,
    };
    save_vesta_cloud_pairing(config_dir, &pairing);
    Ok(pairing)
}

/// Forward ONE control-plane poll for `device_code`. `Err` is transport-level
/// (retry later, the pairing survives); `Refused` is terminal. On `Linked` the
/// account is persisted and the in-flight pairing cleared HERE, so every
/// frontend that polls gets the same durable outcome.
pub(crate) async fn poll_pairing(
    client: &reqwest::Client,
    config_dir: &Path,
    device_code: &str,
) -> Result<PollOutcome, String> {
    let base = control_base();
    let response = client
        .post(format!("{base}/pair/poll"))
        .timeout(HTTP_TIMEOUT)
        .json(&serde_json::json!({ "device_code": device_code }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let status = response.status();
    if status.is_server_error() {
        return Err(format!("control plane returned {status}"));
    }
    let body: serde_json::Value = response.json().await.map_err(|e| e.to_string())?;
    if status.is_success() {
        return match body.get("status").and_then(|v| v.as_str()) {
            Some("pending") => Ok(PollOutcome::Pending),
            Some("linked") => {
                let (Some(server_id), Some(control_url)) = (
                    body.get("server_id").and_then(|v| v.as_str()),
                    body.get("control_url").and_then(|v| v.as_str()),
                ) else {
                    return Err("linked response missing server_id/control_url".to_string());
                };
                save_vesta_cloud_account(
                    config_dir,
                    &VestaCloudAccount {
                        server_id: server_id.to_string(),
                        control_url: control_url.to_string(),
                    },
                );
                clear_vesta_cloud_pairing(config_dir);
                Ok(PollOutcome::Linked {
                    server_id: server_id.to_string(),
                    control_url: control_url.to_string(),
                })
            }
            _ => Err("unrecognized pairing poll response".to_string()),
        };
    }
    // A 4xx is a terminal refusal (expired / unknown / account already has a
    // server), not a transient failure: the dead pairing is cleared.
    clear_vesta_cloud_pairing(config_dir);
    let error = body
        .get("error")
        .and_then(|v| v.as_str())
        .unwrap_or("pairing refused");
    Ok(PollOutcome::Refused {
        gone: status == reqwest::StatusCode::GONE,
        reason: error.to_string(),
    })
}

/// Ask the control plane to retire this box's registration. `Err` is
/// transport-level or an unexpected status; on `Unpaired` the local account
/// link is cleared HERE (a 404 means it was already gone server-side, e.g. a
/// dashboard unpair). `IdentityRejected` keeps the link on purpose.
pub(crate) async fn request_unpair(
    client: &reqwest::Client,
    config_dir: &Path,
    api_key: &str,
    account: &VestaCloudAccount,
) -> Result<UnpairOutcome, String> {
    let token = crate::jwt::create_server_identity_token(api_key, &account.server_id);
    let response = client
        .post(format!("{}/pair/unpair", account.control_url))
        .timeout(HTTP_TIMEOUT)
        .bearer_auth(token)
        .send()
        .await
        .map_err(|e| format!("could not reach the Vesta Cloud control plane: {e}"))?;

    let status = response.status();
    if status == reqwest::StatusCode::UNAUTHORIZED {
        return Ok(UnpairOutcome::IdentityRejected);
    }
    let already_gone = status == reqwest::StatusCode::NOT_FOUND;
    if !status.is_success() && !already_gone {
        let text = response.text().await.unwrap_or_default();
        return Err(format!("control plane returned {status}: {text}"));
    }
    clear_vesta_cloud_account(config_dir);
    Ok(UnpairOutcome::Unpaired { already_gone })
}

// ---------------------------------------------------------------------------
// `vestad login` / `vestad logout` — the owner-at-the-host frontend
// ---------------------------------------------------------------------------

/// `vestad vesta-cloud logout`: unpair this box from its Vesta Cloud account.
pub(crate) fn run_logout(config_dir: &Path) -> Result<(), String> {
    if crate::is_cloud_managed() {
        return Err("a managed Vesta Cloud box cannot unpair".to_string());
    }
    let Some(account) = load_vesta_cloud_account(config_dir) else {
        eprintln!("this box is not paired to a Vesta Cloud account");
        return Ok(());
    };
    let api_key = crate::serve::ensure_api_key(config_dir)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("failed to start async runtime: {e}"))?;
    runtime.block_on(async {
        let client = reqwest::Client::new();
        match request_unpair(&client, config_dir, &api_key, &account).await? {
            UnpairOutcome::IdentityRejected => Err(
                "the control plane rejected this box's identity (has the api key changed since pairing?); the link was NOT cleared. remove the box from the vesta.run dashboard, then run `vestad vesta-cloud logout` again".to_string(),
            ),
            UnpairOutcome::Unpaired { already_gone } => {
                if already_gone {
                    eprintln!("the account link was already removed on vesta.run; local link cleared");
                }
                eprintln!(
                    "  {} unpaired from Vesta Cloud",
                    crate::status::paint("32", "✓")
                );
                Ok(())
            }
        }
    })
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

    #[test]
    fn current_pairing_resumes_from_disk_and_drops_when_expired() {
        // The file is the single source of truth: a restarted vestad (or the
        // host CLI) resumes the in-flight pairing, so the device_code survives
        // to reach the control plane's consumed-pairing replay branch.
        let dir = tempfile::tempdir().expect("tempdir");
        let pairing = VestaCloudPairing {
            device_code: "d".repeat(64),
            user_code: "BCDF-2345".to_string(),
            verification_url: "https://vesta.run/pair?code=BCDF-2345".to_string(),
            interval: 5,
            expires_at_epoch_secs: 1_000,
        };
        save_vesta_cloud_pairing(dir.path(), &pairing);
        assert_eq!(current_vesta_cloud_pairing(dir.path(), 500), Some(pairing));

        // Once expired it is dropped AND its file removed.
        assert_eq!(current_vesta_cloud_pairing(dir.path(), 1_000), None);
        assert_eq!(load_vesta_cloud_pairing(dir.path()), None);
    }
}
