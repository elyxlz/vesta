//! The daemon's persisted settings store (`settings.json` in the config dir):
//! the schema, its defaults, and atomic load/save. Handlers in serve.rs mutate
//! it through `AppState.settings`; this module owns the file and the shapes.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

pub(crate) const DEFAULT_AUTO_BACKUP_HOUR: u8 = 4;

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
    #[serde(default = "default_backup_hour")]
    pub(crate) hour: u8,
    #[serde(default = "default_retention")]
    pub(crate) retention: crate::types::RetentionPolicy,
    #[serde(default)]
    pub(crate) agents: HashMap<String, AgentBackupOverride>,
}

impl Default for BackupGlobalSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            hour: DEFAULT_AUTO_BACKUP_HOUR,
            retention: default_retention(),
            agents: HashMap::new(),
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

fn default_backup_hour() -> u8 { DEFAULT_AUTO_BACKUP_HOUR }

pub(crate) fn default_retention() -> crate::types::RetentionPolicy {
    crate::types::RetentionPolicy {
        daily: crate::backup::DEFAULT_RETENTION_DAILY,
        weekly: crate::backup::DEFAULT_RETENTION_WEEKLY,
        monthly: crate::backup::DEFAULT_RETENTION_MONTHLY,
    }
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

pub(crate) fn load_settings() -> Settings {
    let path = settings_file();

    if let Ok(data) = std::fs::read_to_string(&path) {
        match serde_json::from_str(&data) {
            Ok(settings) => {
                // Re-write to persist any new fields added with defaults
                save_settings(&settings);
                return settings;
            }
            Err(err) => {
                tracing::warn!(path = %path.display(), error = %err, "corrupt settings.json, using defaults");
            }
        }
    }

    let settings = Settings::default();

    // Always write settings to disk so users can edit the file
    save_settings(&settings);

    settings
}

pub(crate) fn save_settings(settings: &Settings) {
    let path = settings_file();
    if let Some(parent) = path.parent() {
        if let Err(err) = std::fs::create_dir_all(parent) {
            tracing::warn!(error = %err, "failed to create settings dir");
            return;
        }
    }
    let data = match serde_json::to_string_pretty(settings) {
        Ok(data) => data,
        Err(err) => {
            tracing::warn!(error = %err, "failed to serialize settings");
            return;
        }
    };
    let tmp = path.with_extension("json.tmp");
    if let Err(err) = std::fs::write(&tmp, &data) {
        tracing::warn!(error = %err, "failed to write settings.json.tmp");
        return;
    }
    if let Err(err) = std::fs::rename(&tmp, &path) {
        tracing::warn!(error = %err, "failed to rename settings.json.tmp");
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
    fn settings_auto_update_false_is_honored() {
        let s: Settings =
            serde_json::from_str(r#"{"auto_update": false}"#).expect("valid Settings");
        assert!(!s.auto_update);
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
