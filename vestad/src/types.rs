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
    Daily,
    Weekly,
    Monthly,
    PreRestore,
}

impl std::fmt::Display for BackupType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Manual => write!(f, "manual"),
            Self::Daily => write!(f, "daily"),
            Self::Weekly => write!(f, "weekly"),
            Self::Monthly => write!(f, "monthly"),
            Self::PreRestore => write!(f, "pre-restore"),
        }
    }
}

impl std::str::FromStr for BackupType {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "manual" => Ok(Self::Manual),
            "daily" => Ok(Self::Daily),
            "weekly" => Ok(Self::Weekly),
            "monthly" => Ok(Self::Monthly),
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
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct RetentionPolicy {
    pub daily: usize,
    pub weekly: usize,
    pub monthly: usize,
}
