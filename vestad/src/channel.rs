//! Release channel: `stable` follows promoted GitHub releases, `beta` follows the
//! newest release including prereleases. The channel is owned by vestad: it is
//! persisted in `settings.json` (set via `PUT /settings/channel`) and reported on
//! `/version`. A connected app/CLI matches whatever version vestad lands on, so the
//! channel only decides which version vestad targets; the agent image (pinned to
//! vestad's own version) and embedded agent core follow automatically.
//!
//! `VESTA_CHANNEL` env var overrides the persisted setting (used by CI / advanced
//! setups). Unknown values fall back to `stable` rather than erroring, so a corrupt
//! setting can never wedge updates.

/// Env var that overrides the persisted channel.
pub const CHANNEL_ENV: &str = "VESTA_CHANNEL";

const SETTINGS_FILE_NAME: &str = "settings.json";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Channel {
    #[default]
    Stable,
    Beta,
}

impl Channel {
    pub fn as_str(self) -> &'static str {
        match self {
            Channel::Stable => "stable",
            Channel::Beta => "beta",
        }
    }

    /// Strict parse for validating user input (the `PUT /settings/channel` body and
    /// the CLI). Returns `None` for anything that is not exactly a known channel.
    pub fn parse(value: &str) -> Option<Channel> {
        match value.trim() {
            "stable" => Some(Channel::Stable),
            "beta" => Some(Channel::Beta),
            _ => None,
        }
    }

    /// Lenient parse for reading persisted/derived values: unknown -> `Stable`.
    pub fn from_setting(value: &str) -> Channel {
        Channel::parse(value).unwrap_or_default()
    }

    /// The channel in effect right now: `VESTA_CHANNEL` env wins, otherwise the
    /// persisted `settings.json` value, otherwise `stable`. Used by the no-AppState
    /// `vestad update` path; the server passes its in-memory setting through
    /// [`Channel::resolve`] instead.
    pub fn effective() -> Channel {
        if let Ok(env_value) = std::env::var(CHANNEL_ENV) {
            if let Some(channel) = Channel::parse(&env_value) {
                return channel;
            }
        }
        Channel::from_setting(&read_persisted_channel())
    }

    /// Apply the env override to an already-loaded settings value.
    pub fn resolve(settings_channel: &str) -> Channel {
        if let Ok(env_value) = std::env::var(CHANNEL_ENV) {
            if let Some(channel) = Channel::parse(&env_value) {
                return channel;
            }
        }
        Channel::from_setting(settings_channel)
    }
}

fn read_persisted_channel() -> String {
    let Some(dir) = crate::paths::config_dir() else {
        return String::new();
    };
    let Ok(contents) = std::fs::read_to_string(dir.join(SETTINGS_FILE_NAME)) else {
        return String::new();
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&contents) else {
        return String::new();
    };
    match value.get("channel").and_then(|c| c.as_str()) {
        Some(channel) => channel.to_string(),
        None => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_is_strict() {
        assert_eq!(Channel::parse("stable"), Some(Channel::Stable));
        assert_eq!(Channel::parse("beta"), Some(Channel::Beta));
        assert_eq!(Channel::parse("Beta"), None);
        assert_eq!(Channel::parse("nightly"), None);
        assert_eq!(Channel::parse(""), None);
    }

    #[test]
    fn from_setting_defaults_to_stable() {
        assert_eq!(Channel::from_setting("beta"), Channel::Beta);
        assert_eq!(Channel::from_setting("garbage"), Channel::Stable);
        assert_eq!(Channel::from_setting(""), Channel::Stable);
    }

    #[test]
    fn as_str_round_trips() {
        for channel in [Channel::Stable, Channel::Beta] {
            assert_eq!(Channel::parse(channel.as_str()), Some(channel));
        }
    }
}
