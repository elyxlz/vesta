//! Defaults a brand-new agent gets. Model/provider/personality come from the agent's embedded
//! `core/defaults.json` (its config floor), so vestad and the agent share one source. The
//! context-window presets are create-wizard UI metadata and stay here.

use serde::{Deserialize, Serialize};

pub const DEFAULT_CONTEXT_TOKENS: u32 = 1_000_000;

/// Context-window presets for the create wizard, largest first; the first is the default.
pub const CONTEXT_PRESETS: &[ContextPreset] = &[
    ContextPreset { tokens: 1_000_000, label: "1M", note: "most context" },
    ContextPreset { tokens: 500_000, label: "500K", note: "balanced" },
    ContextPreset { tokens: 200_000, label: "200K", note: "cheapest prompt-cache reads, compacts soonest" },
];

#[derive(Serialize, Clone, Copy)]
pub struct ContextPreset {
    pub tokens: u32,
    pub label: &'static str,
    pub note: &'static str,
}

/// The model/provider/personality defaults, read verbatim from the shipped `core/defaults.json`.
#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct ShippedDefaults {
    pub agent_model: String,
    pub agent_provider: String,
    pub agent_personality: String,
}

/// Read the embedded `core/defaults.json`. It ships in the binary, so a failure here is a build bug.
pub fn shipped_defaults() -> ShippedDefaults {
    let raw = crate::agent_embed::AgentSource::get("core/defaults.json").expect("core/defaults.json embedded in agent source");
    serde_json::from_slice(&raw.data).expect("core/defaults.json is valid ShippedDefaults JSON")
}

#[derive(Serialize)]
pub struct AgentDefaults {
    #[serde(flatten)]
    pub shipped: ShippedDefaults,
    pub context_tokens: u32,
    pub context_presets: &'static [ContextPreset],
}

/// `GET /agent-defaults`: everything the create wizard needs to pre-select.
pub async fn agent_defaults_handler() -> axum::Json<AgentDefaults> {
    axum::Json(AgentDefaults {
        shipped: shipped_defaults(),
        context_tokens: DEFAULT_CONTEXT_TOKENS,
        context_presets: CONTEXT_PRESETS,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shipped_defaults_match_the_agent_floor() {
        // The single source of truth: vestad serves exactly what the agent ships as its defaults.
        let defaults = shipped_defaults();
        assert_eq!(defaults.agent_provider, "claude");
        assert_eq!(defaults.agent_model, "opus");
        assert_eq!(defaults.agent_personality, "dry");
    }
}
