//! The service-key store: the one owner of the credentials that open a private service
//! through the agent proxy. A secret exists only in the mint response and is kept here
//! solely as a SHA-256 hash, so this file never holds a usable credential. A key is
//! scoped to one service on one agent, expires, and can be revoked by id.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

/// Random bytes per secret, rendered as 64 hex chars.
const SERVICE_KEY_BYTES: usize = 32;
/// Random bytes per key id, rendered as 16 hex chars.
const SERVICE_KEY_ID_BYTES: usize = 8;
/// Lifetime of a minted key when the caller does not ask for one, so a key the agent
/// mints and forgets ages out instead of living forever.
pub(crate) const DEFAULT_KEY_TTL_SECS: u64 = 30 * 86_400;
/// Permissions for the store file on disk.
const OWNER_ONLY_FILE_MODE: u32 = 0o600;

#[derive(Serialize, Deserialize, Clone, PartialEq, Eq, Debug)]
pub(crate) struct ServiceKey {
    pub(crate) id: String,
    /// SHA-256 hex of the secret.
    hash: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    label: Option<String>,
    /// Unix seconds. `None` is a deliberately non-expiring key.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    expires_at: Option<u64>,
    created_at: u64,
}

impl ServiceKey {
    fn is_live_at(&self, now: u64) -> bool {
        self.expires_at.is_none_or(|expires_at| expires_at > now)
    }
}

/// The subset a client may see: everything but the hash.
#[derive(Serialize, Clone, PartialEq, Eq, Debug)]
pub(crate) struct ServiceKeyInfo {
    pub(crate) id: String,
    pub(crate) label: Option<String>,
    pub(crate) expires_at: Option<u64>,
    pub(crate) created_at: u64,
}

impl From<&ServiceKey> for ServiceKeyInfo {
    fn from(key: &ServiceKey) -> Self {
        Self {
            id: key.id.clone(),
            label: key.label.clone(),
            expires_at: key.expires_at,
            created_at: key.created_at,
        }
    }
}

#[derive(Serialize, Deserialize, Default, Debug)]
pub(crate) struct ServiceKeyStore {
    /// agent name -> service name -> that service's keys.
    #[serde(default)]
    by_agent: HashMap<String, HashMap<String, Vec<ServiceKey>>>,
}

fn hash_secret(secret: &str) -> String {
    hex::encode(ring::digest::digest(
        &ring::digest::SHA256,
        secret.as_bytes(),
    ))
}

impl ServiceKeyStore {
    /// Mint a key for `(agent, service)` and return its metadata plus the secret. The
    /// returned secret is the only time it exists in plaintext.
    pub(crate) fn mint(
        &mut self,
        agent: &str,
        service: &str,
        label: Option<String>,
        expires_at: Option<u64>,
        now: u64,
    ) -> (ServiceKeyInfo, String) {
        let secret = hex::encode(rand::random::<[u8; SERVICE_KEY_BYTES]>());
        let key = ServiceKey {
            id: hex::encode(rand::random::<[u8; SERVICE_KEY_ID_BYTES]>()),
            hash: hash_secret(&secret),
            label,
            expires_at,
            created_at: now,
        };
        let info = ServiceKeyInfo::from(&key);
        self.by_agent
            .entry(agent.to_string())
            .or_default()
            .entry(service.to_string())
            .or_default()
            .push(key);
        (info, secret)
    }

    /// Drop the key with this id. False when no such key exists, so revoke is idempotent.
    pub(crate) fn revoke(&mut self, agent: &str, service: &str, id: &str) -> bool {
        let Some(keys) = self
            .by_agent
            .get_mut(agent)
            .and_then(|services| services.get_mut(service))
        else {
            return false;
        };
        let before = keys.len();
        keys.retain(|key| key.id != id);
        before != keys.len()
    }

    /// Live keys for this service, newest last, without their hashes.
    pub(crate) fn list(&self, agent: &str, service: &str, now: u64) -> Vec<ServiceKeyInfo> {
        self.by_agent
            .get(agent)
            .and_then(|services| services.get(service))
            .map(|keys| {
                keys.iter()
                    .filter(|key| key.is_live_at(now))
                    .map(ServiceKeyInfo::from)
                    .collect()
            })
            .unwrap_or_default()
    }

    /// True when `presented` is a live key for exactly this `(agent, service)` pair.
    pub(crate) fn accepts(&self, agent: &str, service: &str, presented: &str, now: u64) -> bool {
        let Some(keys) = self
            .by_agent
            .get(agent)
            .and_then(|services| services.get(service))
        else {
            return false;
        };
        // Comparing SHA-256 digests, not secrets, so an ordinary `==` is right here: a timing
        // oracle on it reveals at most the stored digest, and recovering a 32 byte random secret
        // from its digest needs a preimage. `auth.rs`'s constant-time compare stays correct for
        // what it guards, the raw api key presented in a header.
        let presented_hash = hash_secret(presented);
        keys.iter()
            .any(|key| key.is_live_at(now) && key.hash == presented_hash)
    }

    /// Drop every expired key, returning how many went. Called on load and after each write.
    pub(crate) fn prune_expired(&mut self, now: u64) -> usize {
        let mut removed = 0;
        for services in self.by_agent.values_mut() {
            for keys in services.values_mut() {
                let before = keys.len();
                keys.retain(|key| key.is_live_at(now));
                removed += before - keys.len();
            }
            services.retain(|_, keys| !keys.is_empty());
        }
        self.by_agent.retain(|_, services| !services.is_empty());
        removed
    }
}

fn store_file() -> std::path::PathBuf {
    crate::paths::config_dir_or_relative().join("service-keys.json")
}

/// Read the store, dropping anything already expired. A missing or corrupt file is an
/// empty store: keys are re-mintable, so refusing to start over them would be worse.
pub(crate) fn load_store() -> ServiceKeyStore {
    load_store_at(&store_file())
}

fn load_store_at(path: &std::path::Path) -> ServiceKeyStore {
    let mut store = match std::fs::read_to_string(path) {
        Ok(data) => match serde_json::from_str::<ServiceKeyStore>(&data) {
            Ok(store) => store,
            Err(err) => {
                tracing::warn!(path = %path.display(), error = %err, "corrupt service-keys.json, starting empty");
                ServiceKeyStore::default()
            }
        },
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => ServiceKeyStore::default(),
        Err(err) => {
            tracing::warn!(path = %path.display(), error = %err, "cannot read service-keys.json, starting empty");
            ServiceKeyStore::default()
        }
    };
    let pruned = store.prune_expired(crate::time_utils::now_epoch_secs());
    if pruned > 0 {
        tracing::info!(pruned, "dropped expired service keys");
        save_store_at(path, &store);
    }
    store
}

pub(crate) fn save_store(store: &ServiceKeyStore) {
    save_store_at(&store_file(), store);
}

/// Owner-only at rest: the file holds the key hashes.
fn save_store_at(path: &std::path::Path, store: &ServiceKeyStore) {
    crate::settings::save_json_atomic(path, store, Some(OWNER_ONLY_FILE_MODE));
}

#[cfg(test)]
mod tests {
    use super::{load_store_at, save_store_at, ServiceKeyStore, DEFAULT_KEY_TTL_SECS};
    use std::path::PathBuf;

    const NOW: u64 = 1_800_000_000;
    /// `load_store_at` prunes against the real clock, so the file-IO tests need expiries that are
    /// unambiguously past and future in wall-clock terms, not relative to `NOW`.
    const PAST_EXPIRY: u64 = 1_000_000_000;
    const FAR_FUTURE_EXPIRY: u64 = 4_000_000_000;

    fn store_with_key(expires_at: Option<u64>) -> (ServiceKeyStore, String) {
        let mut store = ServiceKeyStore::default();
        let (_, secret) = store.mint("alpha", "dashboard", None, expires_at, NOW);
        (store, secret)
    }

    #[test]
    fn a_minted_secret_is_64_hex_chars_and_only_its_hash_is_kept() {
        let (store, secret) = store_with_key(Some(NOW + 600));
        assert_eq!(secret.len(), 64);
        assert!(secret.bytes().all(|byte| byte.is_ascii_hexdigit()));
        let serialized = serde_json::to_string(&store).expect("serialize store");
        assert!(
            !serialized.contains(&secret),
            "the store must never persist the secret itself"
        );
    }

    #[test]
    fn the_minted_secret_opens_its_own_service_and_nothing_else() {
        let (store, secret) = store_with_key(Some(NOW + 600));
        assert!(store.accepts("alpha", "dashboard", &secret, NOW));
        assert!(!store.accepts("alpha", "tasks", &secret, NOW));
        assert!(!store.accepts("beta", "dashboard", &secret, NOW));
        assert!(!store.accepts("alpha", "dashboard", "not-the-secret", NOW));
    }

    #[test]
    fn an_expired_key_is_refused_and_pruned() {
        let (mut store, secret) = store_with_key(Some(NOW - 1));
        assert!(!store.accepts("alpha", "dashboard", &secret, NOW));
        assert_eq!(store.prune_expired(NOW), 1);
        assert_eq!(store.prune_expired(NOW), 0);
    }

    #[test]
    fn a_key_minted_without_an_expiry_never_ages_out() {
        let (mut store, secret) = store_with_key(None);
        let far_future = NOW + DEFAULT_KEY_TTL_SECS * 100;
        assert!(store.accepts("alpha", "dashboard", &secret, far_future));
        assert_eq!(store.prune_expired(far_future), 0);
    }

    #[test]
    fn revoking_by_id_takes_effect_immediately() {
        let mut store = ServiceKeyStore::default();
        let (info, secret) = store.mint("alpha", "dashboard", None, Some(NOW + 600), NOW);
        assert!(store.accepts("alpha", "dashboard", &secret, NOW));
        assert!(store.revoke("alpha", "dashboard", &info.id));
        assert!(!store.accepts("alpha", "dashboard", &secret, NOW));
        assert!(
            !store.revoke("alpha", "dashboard", &info.id),
            "revoke is idempotent"
        );
    }

    #[test]
    fn listing_reports_live_keys_without_their_hashes() {
        let mut store = ServiceKeyStore::default();
        let (live, _) = store.mint(
            "alpha",
            "dashboard",
            Some("phone".into()),
            Some(NOW + 600),
            NOW,
        );
        store.mint("alpha", "dashboard", None, Some(NOW - 1), NOW);
        let listed = store.list("alpha", "dashboard", NOW);
        assert_eq!(listed.len(), 1, "an expired key is not listed");
        assert_eq!(listed[0].id, live.id);
        assert_eq!(listed[0].label.as_deref(), Some("phone"));
        let serialized = serde_json::to_string(&listed).expect("serialize listing");
        assert!(
            !serialized.contains("hash"),
            "listings never carry the hash"
        );
    }

    #[test]
    fn two_mints_produce_different_secrets_and_ids() {
        let mut store = ServiceKeyStore::default();
        let (first, first_secret) = store.mint("alpha", "dashboard", None, None, NOW);
        let (second, second_secret) = store.mint("alpha", "dashboard", None, None, NOW);
        assert_ne!(first_secret, second_secret);
        assert_ne!(first.id, second.id);
        assert!(store.accepts("alpha", "dashboard", &first_secret, NOW));
        assert!(store.accepts("alpha", "dashboard", &second_secret, NOW));
    }

    /// The store path plus the directory that owns it: the `TempDir` deletes it when dropped.
    fn temp_store_path() -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("service-keys.json");
        (dir, path)
    }

    #[test]
    fn a_saved_key_still_opens_its_service_after_a_reload() {
        let (_dir, path) = temp_store_path();
        let mut store = ServiceKeyStore::default();
        let (_, secret) = store.mint("alpha", "dashboard", None, Some(FAR_FUTURE_EXPIRY), NOW);
        save_store_at(&path, &store);
        let reloaded = load_store_at(&path);
        assert!(reloaded.accepts("alpha", "dashboard", &secret, NOW));
        assert!(!reloaded.accepts("alpha", "tasks", &secret, NOW));
    }

    #[cfg(unix)]
    #[test]
    fn the_saved_file_is_readable_only_by_its_owner() {
        use std::os::unix::fs::PermissionsExt;

        let (_dir, path) = temp_store_path();
        save_store_at(&path, &ServiceKeyStore::default());
        let mode = std::fs::metadata(&path)
            .expect("saved file exists")
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
    }

    #[test]
    fn a_successful_save_leaves_no_temp_file_behind() {
        let (_dir, path) = temp_store_path();
        save_store_at(&path, &ServiceKeyStore::default());
        assert!(path.exists());
        assert!(!path.with_extension("json.tmp").exists());
    }

    #[test]
    fn loading_drops_an_expired_key_and_rewrites_the_file_without_it() {
        let (_dir, path) = temp_store_path();
        let mut store = ServiceKeyStore::default();
        let (expired, _) = store.mint("alpha", "dashboard", None, Some(PAST_EXPIRY), NOW);
        save_store_at(&path, &store);
        let loaded = load_store_at(&path);
        assert!(loaded.list("alpha", "dashboard", NOW).is_empty());
        let on_disk = std::fs::read_to_string(&path).expect("read rewritten file");
        assert!(
            !on_disk.contains(&expired.id),
            "the expired key is gone from disk, not just from memory"
        );
    }

    #[test]
    fn loading_a_missing_file_yields_an_empty_store() {
        let (_dir, path) = temp_store_path();
        let loaded = load_store_at(&path);
        assert!(loaded.list("alpha", "dashboard", NOW).is_empty());
        assert!(!path.exists(), "loading does not create the file");
    }

    #[test]
    fn loading_invalid_json_yields_an_empty_store_and_leaves_the_file_alone() {
        let (_dir, path) = temp_store_path();
        let garbage = "{not json at all";
        std::fs::write(&path, garbage).expect("write garbage");
        let loaded = load_store_at(&path);
        assert!(loaded.list("alpha", "dashboard", NOW).is_empty());
        assert_eq!(
            std::fs::read_to_string(&path).expect("read file"),
            garbage,
            "an unparseable file is left for the operator to look at"
        );
    }
}
