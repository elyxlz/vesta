//! The provider manifest vestad serves pre-agent: the per-provider catalog + new-agent defaults,
//! embedded from the agent's generated `core/manifest.json` (the single source, derived from the
//! provider models). Served verbatim at `GET /manifest` so the app/CLI/onboard read one shape.

use serde_json::Value;

/// Read the embedded `core/manifest.json`. It ships in the binary, so a failure here is a build bug.
pub fn manifest() -> Value {
    let raw = crate::agent_embed::AgentSource::get("core/manifest.json").expect("core/manifest.json embedded in agent source");
    serde_json::from_slice(&raw.data).expect("core/manifest.json is valid JSON")
}

/// `GET /manifest`: everything the create wizard needs to render providers + pre-select defaults.
pub async fn manifest_handler() -> axum::Json<Value> {
    axum::Json(manifest())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manifest_carries_both_providers_and_the_default() {
        // The single source of truth: vestad serves exactly what the agent generated from its models.
        let manifest = manifest();
        let providers = manifest.get("providers").expect("providers key");
        assert!(providers.get("claude").is_some());
        assert!(providers.get("openrouter").is_some());
        assert_eq!(manifest.get("default_provider").and_then(Value::as_str), Some("claude"));
        let prefs = manifest.get("prefs").expect("prefs key");
        assert_eq!(prefs.get("agent_personality").and_then(Value::as_str), Some("dry"));
        assert!(manifest.get("personalities").and_then(Value::as_array).is_some_and(|presets| !presets.is_empty()));
    }
}
