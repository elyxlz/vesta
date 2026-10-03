//! The daemon's persisted settings store (`settings.json` in the config dir):
//! the schema, its defaults, and atomic load/save. Handlers in serve.rs mutate
//! it through `AppState.settings`; this module owns the file and the shapes.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

pub(crate) const DEFAULT_EVERY_N_DAYS: u8 = 1;

#[derive(Serialize, Copy, Clone, PartialEq)]
pub(crate) struct ServiceEntry {
    pub(crate) port: u16,
    #[serde(default)]
    pub(crate) public: bool,
}

impl<'de> serde::Deserialize<'de> for ServiceEntry {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Raw {
            Legacy(u16),
            Full { port: u16, #[serde(default)] public: bool },
        }
        match Raw::deserialize(deserializer)? {
            Raw::Legacy(port) => Ok(ServiceEntry { port, public: false }),
            Raw::Full { port, public } => Ok(ServiceEntry { port, public }),
        }
    }
}

#[derive(Serialize, Deserialize)]
pub(crate) struct Settings {
    #[serde(default)]
    pub(crate) services: HashMap<String, HashMap<String, ServiceEntry>>,
    #[serde(default)]
    pub(crate) backup: BackupGlobalSettings,
    #[serde(default)]
    pub(crate) agents: HashMap<String, AgentSettings>,
    /// Release channel: "stable" or "beta". Empty/unknown is treated as stable.
    #[serde(default = "default_channel")]
    pub(crate) channel: String,
    /// Apply updates automatically when the periodic check finds a newer release on
    /// the active channel. On by default; opt out at runtime via PUT /settings/auto-update.
    #[serde(default = "default_true")]
    pub(crate) auto_update: bool,
    /// Bind the HTTPS API to the LAN (0.0.0.0) instead of loopback only. A binding
    /// preference like the port file — it lives here, not in the static systemd
    /// unit, and the daemon reads it at startup. Set via `vestad serve --expose-lan`.
    #[serde(default)]
    pub(crate) expose_lan: bool,
    /// Per-kind background-push overrides for user notifications, keyed by kind. A kind absent
    /// here pushes per its default in `user_notifications::MOBILE_PUSH_ROUTES`; the delta to
    /// connected clients always fans regardless. Set via PUT /gateway/settings.
    #[serde(default)]
    pub(crate) push_notifications: HashMap<String, bool>,
    /// The docker daemon socket (`unix://...`) that vestad and every docker CLI it runs talk to;
    /// unset is the system socket. Set via `vestad docker-socket`.
    #[serde(default)]
    pub(crate) docker_socket: Option<String>,
}

// Manual `Default` (not derived) so a fresh install with no settings.json gets
// `auto_update: true` — `#[derive(Default)]` would zero the bool to `false`,
// silently shipping every new VM with auto-update off.
impl Default for Settings {
    fn default() -> Self {
        Self {
            services: HashMap::new(),
            backup: BackupGlobalSettings::default(),
            agents: HashMap::new(),
            channel: default_channel(),
            auto_update: true,
            expose_lan: false,
            push_notifications: HashMap::new(),
            docker_socket: None,
        }
    }
}

fn default_channel() -> String {
    crate::channel::Channel::Stable.as_str().to_string()
}

/// Per-agent desired run state, persisted in settings.json. vestad owns boot-start, so it needs an
/// explicit record of which agents the user wants running: after a reboot every container is
/// `exited`, so container state alone can't distinguish "user stopped this" from "everything's
/// down, start it". Defaults to Running so existing/fresh agents come up.
#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq, Default)]
#[serde(rename_all = "lowercase")]
pub(crate) enum UserDesired {
    #[default]
    Running,
    Stopped,
}

#[derive(Serialize, Deserialize, Clone, Default)]
pub(crate) struct AgentSettings {
    #[serde(default)]
    pub(crate) user_desired: UserDesired,
    #[serde(default)]
    pub(crate) mounts: Vec<crate::mounts::HostMount>,
}

impl Settings {
    /// The agent's host-folder grants, or an empty list if the agent has none recorded.
    /// One reader so every mount-consuming path (restart, rebuild, rename, restore, list,
    /// reconcile) sees grants the same way.
    pub(crate) fn agent_mounts(&self, name: &str) -> Vec<crate::mounts::HostMount> {
        self.agents.get(name).map(|s| s.mounts.clone()).unwrap_or_default()
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub(crate) struct BackupGlobalSettings {
    #[serde(default = "default_true")]
    pub(crate) enabled: bool,
    #[serde(default = "default_every_n_days")]
    pub(crate) every_n_days: u8,
    #[serde(default = "default_retention")]
    pub(crate) retention: crate::types::RetentionPolicy,
    #[serde(default)]
    pub(crate) agents: HashMap<String, AgentBackupOverride>,
    /// Absolute directory that holds the per-agent restic repos, so backups can sit on another
    /// disk; unset is `restic-repo` in the config dir. Set via `vestad backup-dir`.
    #[serde(default)]
    pub(crate) repo_dir: Option<std::path::PathBuf>,
}

impl Default for BackupGlobalSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            every_n_days: DEFAULT_EVERY_N_DAYS,
            retention: default_retention(),
            agents: HashMap::new(),
            repo_dir: None,
        }
    }
}

impl BackupGlobalSettings {
    /// Effective (enabled, retention) for `agent`, layering its override over the globals.
    /// Single owner of the override-resolution rule the settings handler and the
    /// auto-backup task both depend on.
    pub(crate) fn effective_for(&self, agent: &str) -> (bool, crate::types::RetentionPolicy) {
        let agent_override = self.agents.get(agent);
        (
            agent_override.and_then(|o| o.enabled).unwrap_or(self.enabled),
            agent_override.and_then(|o| o.retention).unwrap_or(self.retention),
        )
    }
}

fn default_true() -> bool { true }

fn default_every_n_days() -> u8 { DEFAULT_EVERY_N_DAYS }

pub(crate) fn default_retention() -> crate::types::RetentionPolicy {
    crate::types::RetentionPolicy {
        periodic: crate::backup::DEFAULT_RETENTION_PERIODIC,
        pre_update_versions: crate::backup::DEFAULT_RETENTION_PRE_UPDATE_VERSIONS,
    }
}

/// LEGACY(remove-when: 2027-08-01; every install has booted a 0.2.x vestad by then): rewrite the
/// backup defaults that older releases froze into settings.json, which `save_settings` rewrites
/// whole on every boot. No client can write these three fields, so the exact old triple is a
/// serialized default and never a choice; any deviation is a human's and leaves all three alone.
fn converge_frozen_backup_defaults(backup: &mut BackupGlobalSettings) {
    const FROZEN_OLD_DEFAULTS: (u8, usize, usize) = (3, 2, 2);
    let stored = (backup.every_n_days, backup.retention.periodic, backup.retention.pre_update_versions);
    if stored != FROZEN_OLD_DEFAULTS {
        return;
    }
    backup.every_n_days = DEFAULT_EVERY_N_DAYS;
    backup.retention = default_retention();
}

#[derive(Serialize, Deserialize, Clone)]
pub(crate) struct AgentBackupOverride {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) retention: Option<crate::types::RetentionPolicy>,
}

fn settings_file() -> std::path::PathBuf {
    crate::paths::config_dir_or_relative().join("settings.json")
}

/// What settings.json at `path` holds: `Ok(None)` when there is no file, `Err` naming the parse
/// failure when the file does not parse.
fn stored_settings_at(path: &std::path::Path) -> Result<Option<Settings>, String> {
    let Ok(data) = std::fs::read_to_string(path) else {
        return Ok(None);
    };
    serde_json::from_str(&data).map(Some).map_err(|err| {
        format!(
            "{} does not parse ({err}); fix the JSON, or move the file away to start from defaults",
            path.display()
        )
    })
}

/// Refuse a settings.json that does not parse. `main` runs this before anything else, so vestad
/// never runs on defaults that would point it at the wrong docker daemon or backup disk.
pub(crate) fn check_stored_settings() -> Result<(), String> {
    stored_settings_at(&settings_file()).map(|_| ())
}

/// The stored settings, with no write-back, so hot paths (every restic repo lookup) and the
/// docker socket export at the top of `main` can read them.
pub(crate) fn read_settings() -> Option<Settings> {
    stored_settings_at(&settings_file()).ok().flatten()
}

fn load_settings_at(path: &std::path::Path) -> Settings {
    match stored_settings_at(path) {
        Ok(stored) => {
            let mut settings = stored.unwrap_or_default();
            converge_frozen_backup_defaults(&mut settings.backup);
            // Write back: it persists fields added with defaults and leaves a file users can edit.
            save_json_atomic(path, &settings, None);
            settings
        }
        Err(err) => {
            tracing::warn!(error = %err, "using default settings; settings.json is left as it is");
            Settings::default()
        }
    }
}

pub(crate) fn load_settings() -> Settings {
    load_settings_at(&settings_file())
}

pub(crate) fn backup_repo_dir_setting() -> Option<std::path::PathBuf> {
    read_settings().and_then(|settings| settings.backup.repo_dir)
}

pub(crate) fn save_settings(settings: &Settings) {
    save_json_atomic(&settings_file(), settings, None);
}

/// `save_settings` for a caller that must report a failed write instead of logging it.
pub(crate) fn write_settings(settings: &Settings) -> Result<(), String> {
    write_json_atomic(&settings_file(), settings, None)
}

/// Atomic pretty-JSON persistence shared by vestad's stores: write `<path>.tmp`, apply
/// `unix_mode` when given (before the rename, so the final file never exists with looser
/// permissions), then rename over `path`.
pub(crate) fn write_json_atomic<T: serde::Serialize>(
    path: &std::path::Path,
    value: &T,
    unix_mode: Option<u32>,
) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| format!("failed to create {}: {err}", parent.display()))?;
    }
    let data = serde_json::to_string_pretty(value).map_err(|err| format!("failed to serialize {}: {err}", path.display()))?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, &data).map_err(|err| format!("failed to write {}: {err}", tmp.display()))?;
    #[cfg(unix)]
    if let Some(mode) = unix_mode {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(mode)).ok();
    }
    #[cfg(not(unix))]
    let _ = unix_mode;
    std::fs::rename(&tmp, path).map_err(|err| format!("failed to replace {}: {err}", path.display()))
}

/// `write_json_atomic` for the stores where a failed write is logged, never fatal.
pub(crate) fn save_json_atomic<T: serde::Serialize>(path: &std::path::Path, value: &T, unix_mode: Option<u32>) {
    if let Err(err) = write_json_atomic(path, value, unix_mode) {
        tracing::warn!(error = %err, "failed to save");
    }
}

/// The persisted LAN-exposure preference (default: loopback only). The daemon
/// reads this at startup to decide the HTTPS bind address.
pub(crate) fn expose_lan_setting() -> bool {
    load_settings().expose_lan
}

/// Persist the LAN-exposure preference. Returns `true` when the stored value
/// changed, so the caller can restart the daemon to apply the new bind address.
pub(crate) fn set_expose_lan(expose: bool) -> bool {
    let mut settings = load_settings();
    if settings.expose_lan == expose {
        return false;
    }
    settings.expose_lan = expose;
    save_settings(&settings);
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_corrupt_settings_file_is_refused_and_left_as_it_is() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        std::fs::write(&path, "{ \"docker_socket\": ").unwrap();

        let Err(err) = stored_settings_at(&path) else {
            panic!("a corrupt settings.json parsed");
        };
        assert!(err.contains("does not parse"));
        assert!(load_settings_at(&path).docker_socket.is_none());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "{ \"docker_socket\": ");
    }

    #[test]
    fn a_missing_settings_file_reads_as_none_and_loads_as_defaults() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        assert!(stored_settings_at(&path).unwrap().is_none());
        assert!(load_settings_at(&path).auto_update);
        assert!(path.exists());
    }

    #[test]
    fn write_json_atomic_reports_a_failed_write() {
        let dir = tempfile::tempdir().unwrap();
        let blocker = dir.path().join("not-a-dir");
        std::fs::write(&blocker, "").unwrap();
        let err = write_json_atomic(&blocker.join("settings.json"), &Settings::default(), None).unwrap_err();
        assert!(err.contains("failed to create"));
    }

    // --- auto_update defaults on (a fresh install and a settings.json predating the
    // field must both end up with auto-update enabled, not the bool's `false`) ---

    #[test]
    fn settings_default_enables_auto_update() {
        assert!(Settings::default().auto_update);
    }

    #[test]
    fn settings_missing_auto_update_field_deserializes_true() {
        // A settings.json written before auto_update existed has no such key.
        let s: Settings = serde_json::from_str("{}").expect("empty object is valid Settings");
        assert!(s.auto_update);
    }

    #[test]
    fn settings_with_a_stale_user_context_key_still_parse() {
        // Older daemons persisted a gateway-wide user_context switch; the key is ignored, so an
        // existing settings.json loads with nothing lost.
        let s: Settings = serde_json::from_str(r#"{"user_context": false, "auto_update": false}"#).expect("parse");
        assert!(!s.auto_update);
    }

    #[test]
    fn settings_auto_update_false_is_honored() {
        let s: Settings =
            serde_json::from_str(r#"{"auto_update": false}"#).expect("valid Settings");
        assert!(!s.auto_update);
    }

    // --- backup settings: a settings.json written by the old tiered scheduler (hour +
    // daily/weekly/monthly retention) must deserialize to the new shape's defaults
    // without losing unrelated fields ---

    #[test]
    fn settings_with_legacy_backup_shape_keeps_unrelated_fields() {
        let s: Settings = serde_json::from_str(
            r#"{
                "services": {"okami": {"web": 8080}},
                "channel": "beta",
                "backup": {"enabled": false, "hour": 4,
                           "retention": {"daily": 3, "weekly": 2, "monthly": 1}}
            }"#,
        )
        .expect("legacy settings.json must deserialize");
        assert_eq!(s.channel, "beta");
        assert!(!s.backup.enabled);
        assert_eq!(s.backup.every_n_days, 1);
        assert_eq!(s.backup.retention.periodic, 1);
        assert_eq!(s.backup.retention.pre_update_versions, 5);
        assert!(s.services.contains_key("okami"));
    }

    // --- the old defaults froze into every existing settings.json (save_settings writes the whole
    // struct back on every boot), and no client can write these fields, so the exact old triple is
    // a serialized default that must converge; anything else is a human's edit ---

    fn backup_settings(json: &str) -> BackupGlobalSettings {
        let mut backup: BackupGlobalSettings = serde_json::from_str(json).expect("valid backup settings");
        converge_frozen_backup_defaults(&mut backup);
        backup
    }

    #[test]
    fn frozen_old_backup_defaults_converge_to_the_new_ones() {
        let b = backup_settings(r#"{"every_n_days": 3, "retention": {"periodic": 2, "pre_update_versions": 2}}"#);
        assert_eq!(b.every_n_days, DEFAULT_EVERY_N_DAYS);
        assert_eq!(b.retention.periodic, crate::backup::DEFAULT_RETENTION_PERIODIC);
        assert_eq!(b.retention.pre_update_versions, crate::backup::DEFAULT_RETENTION_PRE_UPDATE_VERSIONS);
    }

    #[test]
    fn a_chosen_cadence_survives_convergence() {
        let b = backup_settings(r#"{"every_n_days": 7, "retention": {"periodic": 2, "pre_update_versions": 2}}"#);
        assert_eq!(b.every_n_days, 7);
        assert_eq!(b.retention.periodic, 2);
        assert_eq!(b.retention.pre_update_versions, 2);
    }

    #[test]
    fn a_chosen_retention_survives_convergence() {
        let b = backup_settings(r#"{"every_n_days": 3, "retention": {"periodic": 2, "pre_update_versions": 3}}"#);
        assert_eq!(b.every_n_days, 3);
        assert_eq!(b.retention.periodic, 2);
        assert_eq!(b.retention.pre_update_versions, 3);
    }

    #[test]
    fn a_settings_file_already_on_the_new_defaults_is_untouched() {
        let b = backup_settings(r#"{"every_n_days": 1, "retention": {"periodic": 1, "pre_update_versions": 5}}"#);
        assert_eq!(b.every_n_days, 1);
        assert_eq!(b.retention.periodic, 1);
        assert_eq!(b.retention.pre_update_versions, 5);
    }

    #[test]
    fn backup_defaults() {
        let b = BackupGlobalSettings::default();
        assert!(b.enabled);
        assert_eq!(b.every_n_days, 1);
        assert_eq!(b.retention.periodic, 1);
        assert_eq!(b.retention.pre_update_versions, 5);
    }

    // --- expose_lan defaults off: a settings.json predating the field must keep the
    // HTTPS API on loopback, never silently bind a fleet of agents to the LAN ---

    #[test]
    fn settings_default_keeps_lan_unexposed() {
        assert!(!Settings::default().expose_lan);
    }

    #[test]
    fn settings_missing_expose_lan_field_deserializes_false() {
        let s: Settings = serde_json::from_str("{}").expect("empty object is valid Settings");
        assert!(!s.expose_lan);
    }

    #[test]
    fn settings_expose_lan_true_is_honored() {
        let s: Settings =
            serde_json::from_str(r#"{"expose_lan": true}"#).expect("valid Settings");
        assert!(s.expose_lan);
    }

    // --- user_desired drives vestad's boot-start; a wrong default would silently keep every
    // agent down (Stopped) or start a user-stopped one (if it didn't persist) ---

    #[test]
    fn agent_settings_default_user_desired_running() {
        assert_eq!(AgentSettings::default().user_desired, UserDesired::Running);
    }

    #[test]
    fn agent_settings_missing_user_desired_deserializes_running() {
        // An agent entry written before the field existed (an empty object) must come up.
        let s: AgentSettings = serde_json::from_str(r#"{}"#).expect("valid AgentSettings");
        assert_eq!(s.user_desired, UserDesired::Running);
    }

    #[test]
    fn agent_settings_user_desired_stopped_round_trips() {
        let s = AgentSettings {
            user_desired: UserDesired::Stopped,
            mounts: Vec::new(),
        };
        let json = serde_json::to_string(&s).expect("serialize");
        assert!(json.contains(r#""user_desired":"stopped""#), "serialized as: {json}");
        let back: AgentSettings = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(back.user_desired, UserDesired::Stopped);
    }

    // --- mounts persists user-granted host filesystem access; a settings.json predating the
    // field must still deserialize (to no grants), and a granted mount must round-trip ---

    #[test]
    fn agent_settings_defaults_mounts_to_empty() {
        let json = r#"{"user_desired": "running"}"#;
        let s: AgentSettings = serde_json::from_str(json).expect("valid AgentSettings");
        assert!(s.mounts.is_empty());
    }

    #[test]
    fn agent_settings_roundtrips_mounts() {
        let s = AgentSettings {
            user_desired: UserDesired::Running,
            mounts: vec![crate::mounts::HostMount {
                host_path: "/mnt/media".into(),
                container_path: "/mnt/media".into(),
                writable: false,
            }],
        };
        let json = serde_json::to_string(&s).expect("serialize");
        let back: AgentSettings = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(back.mounts, s.mounts);
    }
}
