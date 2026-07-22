//! The provider manifest vestad serves pre-agent at `GET /manifest`: the hand-authored catalog +
//! new-agent defaults (embedded `core/manifest.json`, the single source the agent also reads for its
//! field defaults), merged with the personality presets parsed from the embedded skill files (their
//! natural home). The app/CLI/onboard read this one document.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// The embedded `core/manifest.json` with the personality catalog merged in. Shipped in the binary, so
/// a parse failure here is a build bug.
pub fn manifest() -> Value {
    let raw = crate::agent_embed::AgentSource::get("core/manifest.json")
        .expect("core/manifest.json embedded in agent source");
    let mut manifest: Value =
        serde_json::from_slice(&raw.data).expect("core/manifest.json is valid JSON");
    if let Value::Object(map) = &mut manifest {
        map.insert("personalities".to_string(), json!(personalities()));
    }
    manifest
}

/// `GET /manifest`: everything the create wizard needs to render providers + personalities + defaults.
pub async fn manifest_handler() -> axum::Json<Value> {
    axum::Json(manifest())
}

#[derive(Deserialize)]
struct PresetFrontmatter {
    #[serde(default)]
    emoji: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    sample: String,
    #[serde(default = "default_preset_order")]
    order: u32,
}

fn default_preset_order() -> u32 {
    u32::MAX
}

#[derive(Serialize)]
struct Personality {
    name: String,
    emoji: String,
    title: String,
    description: String,
    sample: String,
    order: u32,
}

/// Parse the embedded personality skill presets (YAML frontmatter), sorted by declared order then name.
fn personalities() -> Vec<Personality> {
    const PREFIX: &str = "skills/personality/presets/";
    let mut results: Vec<Personality> = Vec::new();
    for path in crate::agent_embed::AgentSource::iter() {
        let Some(rest) = path.strip_prefix(PREFIX) else {
            continue;
        };
        let Some(name) = rest.strip_suffix(".md") else {
            continue;
        };
        let Some(file) = crate::agent_embed::AgentSource::get(&path) else {
            continue;
        };
        let Ok(content) = std::str::from_utf8(&file.data) else {
            continue;
        };
        // Preset files open with a YAML frontmatter block delimited by `---`.
        let Some(rest) = content.strip_prefix("---\n") else {
            continue;
        };
        let Some((yaml, _body)) = rest.split_once("\n---") else {
            continue;
        };
        let Ok(meta) = serde_yaml::from_str::<PresetFrontmatter>(yaml) else {
            continue;
        };
        let title = if meta.title.is_empty() {
            name.replace('-', " ")
        } else {
            meta.title
        };
        results.push(Personality {
            name: name.to_string(),
            emoji: meta.emoji,
            title,
            description: meta.description,
            sample: meta.sample,
            order: meta.order,
        });
    }
    results.sort_by(|a, b| a.order.cmp(&b.order).then_with(|| a.name.cmp(&b.name)));
    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manifest_carries_providers_defaults_and_personalities() {
        let manifest = manifest();
        let providers = manifest.get("providers").expect("providers key");
        assert!(providers.get("claude").is_some());
        assert!(providers.get("openrouter").is_some());
        assert!(providers.get("zai").is_some());
        assert!(providers.get("kimi").is_some());
        assert!(providers.get("openai").is_some());
        assert_eq!(
            manifest.get("default_provider").and_then(Value::as_str),
            Some("claude")
        );
        assert_eq!(
            manifest.get("default_personality").and_then(Value::as_str),
            Some("dry")
        );
        assert!(manifest
            .get("personalities")
            .and_then(Value::as_array)
            .is_some_and(|presets| !presets.is_empty()));
    }
}
