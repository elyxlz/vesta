//! The single owner of the device registry (`devices.json` in the config dir): every device vestad
//! knows, keyed by the client-minted installation id. Each record carries an identity facet (kind +
//! descriptor + presence, fed by `sync::presence` from `/sync` connections) and an optional mobile
//! push facet (Expo token + prefs, fed by `mobile_app`). Neither of those modules touches the file;
//! all mutation, the live-connection refcount, the roster projection, and the atomic persistence
//! live here behind the state lock, with the write serialized on a flush lock so concurrent flushers
//! never tear the file. The push token is never placed on the `/sync` wire.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tokio::sync::{watch, Mutex as AsyncMutex, Notify};

use crate::time_utils::epoch_to_rfc3339;
use crate::types::{ClientKind, MobilePlatform};

type InstallationId = String;

const STORE_FILE: &str = "devices.json";
const LEGACY_PUSH_FILE: &str = "mobile-devices.json";

/// A mobile push subscription: exactly the legacy `MobileDevice` minus the installation id, which is
/// now the record key.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub(crate) struct PushSubscription {
    pub token: String,
    pub platform: MobilePlatform,
    #[serde(default)]
    pub gateway: Option<String>,
    pub event_types: Vec<String>,
    pub previews: bool,
    pub registered_at: u64,
}

/// One device. Either facet may be absent: a web/desktop device has identity but no push; a mobile
/// device that registered push before ever opening a `/sync` socket has push but no descriptor.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq, Default)]
struct DeviceRecord {
    kind: ClientKind,
    #[serde(default)]
    descriptor: Option<String>,
    last_seen: u64,
    #[serde(default)]
    push: Option<PushSubscription>,
    #[serde(default)]
    ip: Option<String>,
    #[serde(default)]
    location: Option<String>,
}

impl DeviceRecord {
    /// A record with neither an identity descriptor nor a push facet carries nothing worth keeping.
    fn is_empty(&self) -> bool {
        self.descriptor.is_none() && self.push.is_none()
    }
}

/// The wire projection sent to `/sync` clients. Deliberately omits the push token; `push_enabled` is
/// the only push signal that crosses the wire.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DeviceInfo {
    pub id: String,
    pub kind: ClientKind,
    pub descriptor: Option<String>,
    pub present: bool,
    pub last_seen: String,
    pub push_enabled: bool,
    pub location: Option<String>,
}

/// The legacy `mobile-devices.json` element, read once to migrate into `devices.json`.
#[derive(Debug, Deserialize)]
struct LegacyPushDevice {
    installation_id: String,
    token: String,
    platform: MobilePlatform,
    #[serde(default)]
    gateway: Option<String>,
    event_types: Vec<String>,
    previews: bool,
    registered_at: u64,
}

#[derive(Debug, Default)]
struct RegistryState {
    devices: HashMap<InstallationId, DeviceRecord>,
    /// Live `/sync` connections per device (a device may hold several, e.g. two browser tabs).
    /// `present == live_counts.get(id) > 0`; never persisted.
    live_counts: HashMap<InstallationId, u32>,
}

#[derive(Debug)]
pub(crate) struct DeviceRegistry {
    state: Mutex<RegistryState>,
    devices_tx: watch::Sender<Vec<DeviceInfo>>,
    path: PathBuf,
    dirty: Notify,
    /// Serializes the write+rename so concurrent flushers (the background task and the mobile push
    /// handlers) never interleave into the same tmp file and leave a torn store on disk.
    flush_lock: AsyncMutex<()>,
}

impl DeviceRegistry {
    /// Load (or migrate) the store and publish the opening roster. Synchronous, called once at
    /// startup like `load_settings`; all later IO rides the flush task.
    pub(crate) fn load(config_dir: &Path) -> Self {
        let path = config_dir.join(STORE_FILE);
        let devices = load_or_migrate(config_dir, &path);
        let state = RegistryState { devices, live_counts: HashMap::new() };
        let (devices_tx, _rx) = watch::channel(project(&state));
        Self { state: Mutex::new(state), devices_tx, path, dirty: Notify::new(), flush_lock: AsyncMutex::new(()) }
    }

    pub(crate) fn subscribe_devices(&self) -> watch::Receiver<Vec<DeviceInfo>> {
        self.devices_tx.subscribe()
    }

    pub(crate) fn snapshot(&self) -> Vec<DeviceInfo> {
        self.devices_tx.borrow().clone()
    }

    /// A `/sync` connection reporting this device: bump the live count, upsert the identity facet,
    /// stamp `last_seen`. Non-blocking (runs in the async loop); the disk write is deferred.
    pub(crate) fn mark_connected(
        &self,
        id: &str,
        kind: ClientKind,
        descriptor: Option<String>,
        now: u64,
    ) {
        let mut state = self.state.lock().expect("device registry mutex");
        *state.live_counts.entry(id.to_string()).or_insert(0) += 1;
        let record = state.devices.entry(id.to_string()).or_default();
        record.kind = kind;
        if descriptor.is_some() {
            record.descriptor = descriptor;
        }
        record.last_seen = now;
        self.republish(&state);
        self.dirty.notify_one();
    }

    /// Record the client IP for this device (the IP stays off the wire) and report whether a geo
    /// lookup is needed: the IP changed, or no location is stored yet. Non-blocking; the disk write
    /// defers. No republish, since the IP is not projected onto the roster.
    pub(crate) fn note_ip(&self, id: &str, ip: std::net::IpAddr) -> bool {
        let mut state = self.state.lock().expect("device registry mutex");
        let ip_str = ip.to_string();
        let record = state.devices.entry(id.to_string()).or_default();
        let needs_lookup = record.ip.as_deref() != Some(ip_str.as_str()) || record.location.is_none();
        record.ip = Some(ip_str);
        self.dirty.notify_one();
        needs_lookup
    }

    /// Set the resolved location, but only if the record's IP still matches the one the lookup ran
    /// for (a racing reconnect from another IP must win). Republishes the roster on a real change.
    pub(crate) fn set_location(&self, id: &str, ip: std::net::IpAddr, location: String) {
        let mut state = self.state.lock().expect("device registry mutex");
        let ip_str = ip.to_string();
        let updated = match state.devices.get_mut(id) {
            Some(record) if record.ip.as_deref() == Some(ip_str.as_str()) => {
                record.location = Some(location);
                true
            }
            _ => false,
        };
        if updated {
            self.republish(&state);
            self.dirty.notify_one();
        }
    }

    /// A `/sync` connection for this device closing. On the device's last connection dropping, stamp
    /// `last_seen`. Non-blocking; safe from `PresenceGuard::drop`, which cannot `await`.
    pub(crate) fn mark_disconnected(&self, id: &str, now: u64) {
        let mut state = self.state.lock().expect("device registry mutex");
        let remaining = match state.live_counts.get_mut(id) {
            Some(count) => {
                *count = count.saturating_sub(1);
                *count
            }
            None => 0,
        };
        if remaining == 0 {
            state.live_counts.remove(id);
            if let Some(record) = state.devices.get_mut(id) {
                record.last_seen = now;
            }
        }
        self.republish(&state);
        self.dirty.notify_one();
    }

    /// Register or replace a device's mobile push subscription. A push-only record defaults its kind
    /// to Mobile, since only a mobile client registers push.
    pub(crate) fn upsert_push(&self, id: &str, push: PushSubscription) {
        let mut state = self.state.lock().expect("device registry mutex");
        let record = state.devices.entry(id.to_string()).or_default();
        if record.descriptor.is_none() && record.push.is_none() {
            record.kind = ClientKind::Mobile;
        }
        if record.last_seen == 0 {
            record.last_seen = push.registered_at;
        }
        record.push = Some(push);
        self.republish(&state);
        self.dirty.notify_one();
    }

    /// Clear the push facet of whichever device holds `token`, dropping the record if that leaves it
    /// with no identity either.
    pub(crate) fn clear_push_by_token(&self, token: &str) {
        let mut state = self.state.lock().expect("device registry mutex");
        let owner = state.devices.iter().find_map(|(id, record)| {
            record.push.as_ref().filter(|push| push.token == token).map(|_| id.clone())
        });
        if let Some(id) = owner {
            Self::drop_push(&mut state, &id);
        }
        self.republish(&state);
        self.dirty.notify_one();
    }

    /// Clear the push facet of every device holding one of `tokens` (Expo rejected them).
    pub(crate) fn prune_push_tokens(&self, tokens: &[String]) {
        let mut state = self.state.lock().expect("device registry mutex");
        let owners: Vec<InstallationId> = state
            .devices
            .iter()
            .filter_map(|(id, record)| {
                record.push.as_ref().filter(|push| tokens.contains(&push.token)).map(|_| id.clone())
            })
            .collect();
        for id in owners {
            Self::drop_push(&mut state, &id);
        }
        self.republish(&state);
        self.dirty.notify_one();
    }

    /// The push subscriptions subscribed to `event_type`, for the delivery worker.
    pub(crate) fn push_targets(&self, event_type: &str) -> Vec<PushSubscription> {
        let state = self.state.lock().expect("device registry mutex");
        state
            .devices
            .values()
            .filter_map(|record| record.push.clone())
            .filter(|push| push.event_types.iter().any(|subscribed| subscribed == event_type))
            .collect()
    }

    fn drop_push(state: &mut RegistryState, id: &str) {
        if let Some(record) = state.devices.get_mut(id) {
            record.push = None;
            if record.is_empty() && !state.live_counts.contains_key(id) {
                state.devices.remove(id);
            }
        }
    }

    fn republish(&self, state: &RegistryState) {
        self.devices_tx.send_replace(project(state));
    }

    /// Write the current map to `devices.json` atomically. Async so push register/delete handlers can
    /// await durability before their 200; the background flush task also drives it.
    pub(crate) async fn flush_now(&self) -> Result<(), String> {
        let _flush_guard = self.flush_lock.lock().await;
        let snapshot = self.state.lock().expect("device registry mutex").devices.clone();
        let json = serde_json::to_vec_pretty(&snapshot)
            .map_err(|error| format!("serialize device registry: {error}"))?;
        let temporary = self.path.with_extension("json.tmp");
        tokio::fs::write(&temporary, json)
            .await
            .map_err(|error| format!("write {}: {error}", temporary.display()))?;
        if let Err(error) = tokio::fs::rename(&temporary, &self.path).await {
            let _ = tokio::fs::remove_file(&temporary).await;
            return Err(format!("replace {}: {error}", self.path.display()));
        }
        Ok(())
    }

    /// The background flush loop: wake on any mutation, persist. Best-effort; a failed write is logged
    /// and retried on the next mutation.
    pub(crate) async fn run_flusher(&self) {
        loop {
            self.dirty.notified().await;
            if let Err(error) = self.flush_now().await {
                tracing::warn!(%error, "could not persist device registry");
            }
        }
    }
}

/// Project the live + persisted state into the wire roster, id-sorted for a stable UI order. Never
/// includes the push token.
fn project(state: &RegistryState) -> Vec<DeviceInfo> {
    let mut devices: Vec<DeviceInfo> = state
        .devices
        .iter()
        .map(|(id, record)| DeviceInfo {
            id: id.clone(),
            kind: record.kind,
            descriptor: record.descriptor.clone(),
            present: state.live_counts.get(id).copied().unwrap_or(0) > 0,
            last_seen: epoch_to_rfc3339(record.last_seen).unwrap_or_default(),
            push_enabled: record.push.is_some(),
            location: record.location.clone(),
        })
        .collect();
    devices.sort_by(|a, b| a.id.cmp(&b.id));
    devices
}

fn load_or_migrate(config_dir: &Path, path: &Path) -> HashMap<InstallationId, DeviceRecord> {
    if let Some(devices) = read_map(path) {
        return devices;
    }
    let legacy_path = config_dir.join(LEGACY_PUSH_FILE);
    match migrate_legacy(&legacy_path) {
        Some(devices) => {
            if let Err(error) = write_map_blocking(path, &devices) {
                tracing::error!(%error, "could not write migrated device registry");
                return devices;
            }
            let _ = std::fs::remove_file(&legacy_path);
            devices
        }
        None => HashMap::new(),
    }
}

fn read_map(path: &Path) -> Option<HashMap<InstallationId, DeviceRecord>> {
    match std::fs::read(path) {
        Ok(bytes) => match serde_json::from_slice(&bytes) {
            Ok(devices) => Some(devices),
            Err(error) => {
                tracing::error!(%error, path = %path.display(), "device registry is corrupt");
                Some(HashMap::new())
            }
        },
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => {
            tracing::error!(%error, path = %path.display(), "could not read device registry");
            Some(HashMap::new())
        }
    }
}

fn migrate_legacy(legacy_path: &Path) -> Option<HashMap<InstallationId, DeviceRecord>> {
    let bytes = std::fs::read(legacy_path).ok()?;
    let legacy: Vec<LegacyPushDevice> = match serde_json::from_slice(&bytes) {
        Ok(legacy) => legacy,
        Err(error) => {
            tracing::error!(%error, "legacy mobile device registry is corrupt, starting empty");
            return Some(HashMap::new());
        }
    };
    let mut devices = HashMap::new();
    for device in legacy {
        devices.insert(
            device.installation_id,
            DeviceRecord {
                kind: ClientKind::Mobile,
                descriptor: None,
                last_seen: device.registered_at,
                push: Some(PushSubscription {
                    token: device.token,
                    platform: device.platform,
                    gateway: device.gateway,
                    event_types: device.event_types,
                    previews: device.previews,
                    registered_at: device.registered_at,
                }),
                ip: None,
                location: None,
            },
        );
    }
    Some(devices)
}

fn write_map_blocking(path: &Path, devices: &HashMap<InstallationId, DeviceRecord>) -> Result<(), String> {
    let json = serde_json::to_vec_pretty(devices).map_err(|error| error.to_string())?;
    let temporary = path.with_extension("json.tmp");
    std::fs::write(&temporary, json).map_err(|error| error.to_string())?;
    std::fs::rename(&temporary, path).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn push(token: &str, event_types: &[&str]) -> PushSubscription {
        PushSubscription {
            token: token.to_string(),
            platform: MobilePlatform::Ios,
            gateway: None,
            event_types: event_types.iter().map(|event| (*event).to_string()).collect(),
            previews: true,
            registered_at: 1_780_000_000,
        }
    }

    fn only(registry: &DeviceRegistry, id: &str) -> DeviceInfo {
        registry.snapshot().into_iter().find(|device| device.id == id).expect("device present")
    }

    #[test]
    fn connect_marks_device_present_with_identity() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Web, Some("Chrome on macOS".into()), 100);
        let device = only(&registry, "dev-a");
        assert!(device.present);
        assert_eq!(device.kind, ClientKind::Web);
        assert_eq!(device.descriptor.as_deref(), Some("Chrome on macOS"));
        assert!(!device.push_enabled);
    }

    #[test]
    fn note_ip_stores_and_flags_lookup() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Web, Some("Chrome".into()), 100);
        let ip: std::net::IpAddr = "1.2.3.4".parse().expect("ip");
        assert!(registry.note_ip("dev-a", ip), "new ip needs a lookup");
        assert!(registry.note_ip("dev-a", ip), "same ip with no location still needs one until resolved");
    }

    #[test]
    fn note_ip_reuses_location_for_unchanged_ip() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Web, Some("Chrome".into()), 100);
        let ip: std::net::IpAddr = "1.2.3.4".parse().expect("ip");
        registry.note_ip("dev-a", ip);
        registry.set_location("dev-a", ip, "London, United Kingdom".into());
        assert!(!registry.note_ip("dev-a", ip), "unchanged ip with a location needs no lookup");
        assert_eq!(only(&registry, "dev-a").location.as_deref(), Some("London, United Kingdom"));
    }

    #[test]
    fn set_location_is_a_no_op_when_the_ip_changed() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Web, Some("Chrome".into()), 100);
        let first: std::net::IpAddr = "1.2.3.4".parse().expect("ip");
        let second: std::net::IpAddr = "5.6.7.8".parse().expect("ip");
        registry.note_ip("dev-a", first);
        registry.note_ip("dev-a", second);
        registry.set_location("dev-a", first, "Stale City, Nowhere".into());
        assert_eq!(only(&registry, "dev-a").location, None, "a lookup for the old ip does not land");
    }

    #[test]
    fn roster_never_contains_the_raw_ip() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Web, Some("Chrome".into()), 100);
        let ip: std::net::IpAddr = "203.0.113.9".parse().expect("ip");
        registry.note_ip("dev-a", ip);
        registry.set_location("dev-a", ip, "Paris, France".into());
        let serialized = serde_json::to_string(&registry.snapshot()).expect("serialize roster");
        assert!(!serialized.contains("203.0.113.9"), "roster leaked the ip: {serialized}");
        assert!(serialized.contains("Paris, France"), "roster should carry the location");
    }

    #[test]
    fn stays_present_until_the_last_connection_drops() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Web, Some("tab one".into()), 100);
        registry.mark_connected("dev-a", ClientKind::Web, Some("tab two".into()), 110);
        registry.mark_disconnected("dev-a", 120);
        assert!(only(&registry, "dev-a").present, "one tab left, still present");
        registry.mark_disconnected("dev-a", 130);
        let device = only(&registry, "dev-a");
        assert!(!device.present);
        assert_eq!(device.last_seen, epoch_to_rfc3339(130).expect("rfc3339"));
    }

    #[test]
    fn roster_never_contains_the_push_token() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.upsert_push("dev-a", push("ExponentPushToken[secret]", &["chat"]));
        let device = only(&registry, "dev-a");
        assert!(device.push_enabled);
        let serialized = serde_json::to_string(&registry.snapshot()).expect("serialize roster");
        assert!(!serialized.contains("secret"), "roster leaked the token: {serialized}");
    }

    #[test]
    fn push_only_record_defaults_to_mobile_and_absent() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.upsert_push("dev-a", push("ExponentPushToken[a]", &["chat"]));
        let device = only(&registry, "dev-a");
        assert_eq!(device.kind, ClientKind::Mobile);
        assert!(device.descriptor.is_none());
        assert!(!device.present);
    }

    #[test]
    fn clearing_push_drops_a_record_with_no_identity() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.upsert_push("dev-a", push("ExponentPushToken[a]", &["chat"]));
        registry.clear_push_by_token("ExponentPushToken[a]");
        assert!(registry.snapshot().is_empty());
    }

    #[test]
    fn clearing_push_keeps_a_record_that_still_has_identity() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.mark_connected("dev-a", ClientKind::Mobile, Some("iPhone".into()), 100);
        registry.upsert_push("dev-a", push("ExponentPushToken[a]", &["chat"]));
        registry.clear_push_by_token("ExponentPushToken[a]");
        let device = only(&registry, "dev-a");
        assert!(!device.push_enabled);
        assert_eq!(device.descriptor.as_deref(), Some("iPhone"));
    }

    #[test]
    fn push_targets_filter_by_event_type() {
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = DeviceRegistry::load(dir.path());
        registry.upsert_push("dev-a", push("ExponentPushToken[a]", &["chat"]));
        registry.upsert_push("dev-b", push("ExponentPushToken[b]", &["status"]));
        let chat = registry.push_targets("chat");
        assert_eq!(chat.len(), 1);
        assert_eq!(chat[0].token, "ExponentPushToken[a]");
    }

    #[tokio::test]
    async fn persists_and_reloads_across_construction() {
        let dir = tempfile::tempdir().expect("tempdir");
        {
            let registry = DeviceRegistry::load(dir.path());
            registry.mark_connected("dev-a", ClientKind::Desktop, Some("Vesta Desktop".into()), 100);
            registry.mark_disconnected("dev-a", 150);
            registry.flush_now().await.expect("flush");
        }
        let reloaded = DeviceRegistry::load(dir.path());
        let device = only(&reloaded, "dev-a");
        assert_eq!(device.kind, ClientKind::Desktop);
        assert_eq!(device.descriptor.as_deref(), Some("Vesta Desktop"));
        assert!(!device.present, "a reloaded device is not live");
    }

    #[test]
    fn migrates_legacy_mobile_devices_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let legacy = serde_json::json!([{
            "installation_id": "dev-a",
            "token": "ExponentPushToken[a]",
            "platform": "ios",
            "event_types": ["chat"],
            "previews": true,
            "registered_at": 1_780_000_000u64
        }]);
        std::fs::write(dir.path().join(LEGACY_PUSH_FILE), legacy.to_string()).expect("write legacy");
        let registry = DeviceRegistry::load(dir.path());
        let device = only(&registry, "dev-a");
        assert_eq!(device.kind, ClientKind::Mobile);
        assert!(device.push_enabled);
        assert_eq!(device.last_seen, epoch_to_rfc3339(1_780_000_000).expect("rfc3339"));
        assert!(!dir.path().join(LEGACY_PUSH_FILE).exists(), "legacy file removed");
        assert!(dir.path().join(STORE_FILE).exists(), "new store written");
    }

    #[tokio::test]
    async fn concurrent_flushes_never_tear_the_store() {
        use std::sync::Arc;
        let dir = tempfile::tempdir().expect("tempdir");
        let registry = Arc::new(DeviceRegistry::load(dir.path()));
        // Many devices so a torn interleave of two writers would corrupt the file, and a distinct
        // mutation before each flush so the concurrent flushers race over differing map contents.
        let mut tasks = Vec::new();
        for index in 0..64u32 {
            let registry = registry.clone();
            tasks.push(tokio::spawn(async move {
                registry.upsert_push(&format!("dev-{index}"), push(&format!("ExponentPushToken[{index}]"), &["chat"]));
                registry.flush_now().await.expect("flush");
            }));
        }
        for task in tasks {
            task.await.expect("join");
        }
        // The store parses and holds every record: no writer clobbered another into a partial file.
        let reloaded = DeviceRegistry::load(dir.path());
        assert_eq!(reloaded.snapshot().len(), 64);
    }

    #[test]
    fn corrupt_store_starts_empty() {
        let dir = tempfile::tempdir().expect("tempdir");
        std::fs::write(dir.path().join(STORE_FILE), "{ not json").expect("write corrupt");
        let registry = DeviceRegistry::load(dir.path());
        assert!(registry.snapshot().is_empty());
    }
}
