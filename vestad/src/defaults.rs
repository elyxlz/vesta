//! Single source of truth for the defaults a brand-new agent gets.
//!
//! These are the values the create wizard (web + CLI) pre-selects and that
//! `write_agent_env_file` seeds into the agent's env. The Python agent requires
//! `AGENT_MODEL` / `AGENT_PROVIDER` / `AGENT_PERSONALITY` from the env rather than
//! re-defining their defaults, so each default lives here only. Clients read them
//! from `GET /agent-defaults` instead of hardcoding their own copies.

use serde::Serialize;

pub const DEFAULT_PERSONALITY: &str = "dry";
pub const DEFAULT_PROVIDER: &str = "claude";
pub const DEFAULT_MODEL: &str = "opus";
pub const DEFAULT_CONTEXT_TOKENS: u32 = 1_000_000;

/// Selectable context-window presets, largest first. The first entry is the default
/// (`DEFAULT_CONTEXT_TOKENS` points at it). Smaller windows give cheaper prompt-cache
/// reads and compact sooner.
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

#[derive(Serialize)]
pub struct AgentDefaults {
    pub personality: &'static str,
    pub provider: &'static str,
    pub model: &'static str,
    pub context_tokens: u32,
    pub context_presets: &'static [ContextPreset],
}

/// `GET /agent-defaults`: everything the create wizard needs to pre-select.
pub async fn agent_defaults_handler() -> axum::Json<AgentDefaults> {
    axum::Json(AgentDefaults {
        personality: DEFAULT_PERSONALITY,
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        context_tokens: DEFAULT_CONTEXT_TOKENS,
        context_presets: CONTEXT_PRESETS,
    })
}
