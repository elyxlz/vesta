//! Defaults a brand-new agent gets.
//!
//! The model / provider / personality defaults live in exactly one place: the agent's
//! `agent/core/defaults.json`, which the Python agent reads as its config floor. vestad reads
//! the embedded copy of that file (see `agent_embed`) so the create wizard's pre-selected
//! defaults and the env it seeds match what the agent boots with, with no Rust/Python
//! duplication. The context-window presets are wizard-only UI metadata and stay here.

use serde::{Deserialize, Serialize};

pub const DEFAULT_CONTEXT_TOKENS: u32 = 1_000_000;

/// Selectable context-window presets, largest first. The first entry is the default
/// (`DEFAULT_CONTEXT_TOKENS` points at it). Smaller windows give cheaper prompt-cache
/// reads and compact sooner. UI metadata for the create wizard only (the agent's runtime
/// context default is "unset = model default", a different concern).
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

/// The model/provider/personality defaults, read from the agent's shipped `core/defaults.json`.
#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct ShippedDefaults {
    #[serde(rename = "agent_model")]
    pub model: String,
    #[serde(rename = "agent_provider")]
    pub provider: String,
    #[serde(rename = "agent_personality")]
    pub personality: String,
}

/// Read the embedded `core/defaults.json`. Its presence and validity are guaranteed at build
/// time (it ships in the agent source embedded into the binary), so a failure here is a build
/// bug, not a runtime condition — hence the expects.
pub fn shipped_defaults() -> ShippedDefaults {
    let raw = crate::agent_embed::AgentSource::get("core/defaults.json").expect("core/defaults.json embedded in agent source");
    serde_json::from_slice(&raw.data).expect("core/defaults.json is valid ShippedDefaults JSON")
}

#[derive(Serialize)]
pub struct AgentDefaults {
    pub personality: String,
    pub provider: String,
    pub model: String,
    pub context_tokens: u32,
    pub context_presets: &'static [ContextPreset],
}

/// `GET /agent-defaults`: everything the create wizard needs to pre-select.
pub async fn agent_defaults_handler() -> axum::Json<AgentDefaults> {
    let defaults = shipped_defaults();
    axum::Json(AgentDefaults {
        personality: defaults.personality,
        provider: defaults.provider,
        model: defaults.model,
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
        assert_eq!(defaults.provider, "claude");
        assert_eq!(defaults.model, "opus");
        assert_eq!(defaults.personality, "dry");
    }
}
