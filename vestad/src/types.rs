use serde::{Deserialize, Serialize};

/// The kind of client behind a `/sync` connection. Serialized on the wire (`client_context.client`,
/// `DeviceInfo.kind`) and persisted in the device registry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClientKind {
    Web,
    Mobile,
    Desktop,
    #[default]
    Unknown,
}

impl ClientKind {
    pub(crate) fn display_name(self) -> &'static str {
        match self {
            Self::Web => "Vesta Web App",
            Self::Mobile => "Vesta Mobile App",
            Self::Desktop => "Vesta Desktop App",
            Self::Unknown => "Vesta App",
        }
    }
}

/// The mobile OS a push subscription targets.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MobilePlatform {
    Ios,
    Android,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum BackupType {
    Manual,
    Periodic,
    PreUpdate,
    PreRestore,
}

impl std::fmt::Display for BackupType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Manual => write!(f, "manual"),
            Self::Periodic => write!(f, "periodic"),
            Self::PreUpdate => write!(f, "pre-update"),
            Self::PreRestore => write!(f, "pre-restore"),
        }
    }
}

impl std::str::FromStr for BackupType {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "manual" => Ok(Self::Manual),
            // LEGACY(remove-when: fleet restic repos hold no daily/weekly/monthly-tagged
            // snapshots): tier-tagged snapshots from the old scheduler parse as periodic so
            // they list, satisfy staleness checks, and age out through normal retention.
            "periodic" | "daily" | "weekly" | "monthly" => Ok(Self::Periodic),
            "pre-update" => Ok(Self::PreUpdate),
            "pre-restore" => Ok(Self::PreRestore),
            other => Err(format!("unknown backup type: {other}")),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackupInfo {
    pub id: String,
    pub agent_name: String,
    pub backup_type: BackupType,
    pub created_at: String,
    pub size: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub from_version: Option<String>,
    /// The vestad version that captured this snapshot; absent on pre-stamp snapshots.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub vestad_version: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct RetentionPolicy {
    #[serde(default = "default_retention_periodic")]
    pub periodic: usize,
    #[serde(default = "default_retention_pre_update_versions")]
    pub pre_update_versions: usize,
}

fn default_retention_periodic() -> usize {
    crate::backup::DEFAULT_RETENTION_PERIODIC
}

fn default_retention_pre_update_versions() -> usize {
    crate::backup::DEFAULT_RETENTION_PRE_UPDATE_VERSIONS
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backup_type_roundtrips_and_parses_legacy_tiers() {
        use std::str::FromStr;
        for (s, t) in [
            ("manual", BackupType::Manual),
            ("periodic", BackupType::Periodic),
            ("pre-update", BackupType::PreUpdate),
            ("pre-restore", BackupType::PreRestore),
        ] {
            assert_eq!(BackupType::from_str(s).expect("parses"), t);
            assert_eq!(t.to_string(), s);
        }
        for legacy in ["daily", "weekly", "monthly"] {
            assert_eq!(BackupType::from_str(legacy).expect("parses"), BackupType::Periodic);
        }
        assert!(BackupType::from_str("bogus").is_err());
    }

    #[test]
    fn retention_policy_deserializes_legacy_shape_with_defaults() {
        let ret: RetentionPolicy =
            serde_json::from_str(r#"{"daily": 3, "weekly": 2, "monthly": 1}"#).expect("valid");
        assert_eq!(ret.periodic, 2);
        assert_eq!(ret.pre_update_versions, 2);
    }
}
