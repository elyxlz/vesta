//! `vestad provision`: one command from a Linux user with Docker to a running gateway and a
//! signed-in agent, printing the connect link. The config is parsed and validated into a `Plan`
//! before anything changes.

use serde::Deserialize;

const CLAUDE_DEFAULT_MODEL: &str = "opus-latest";
const CLAUDE_DEFAULT_CONTEXT_TOKENS: u64 = 500_000;
/// Group and other permission bits: a config holding credentials must grant none of them.
const LOOSE_MODE_BITS: u32 = 0o077;
const BYTE_ORDER_MARK: char = '\u{feff}';

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawConfig {
    agent_name: String,
    #[serde(default)]
    cloudflare: Option<crate::tunnel::CloudflareCreds>,
    provider: RawProvider,
    #[serde(default)]
    subdomain: Option<String>,
    #[serde(default)]
    timezone: Option<String>,
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    max_context_tokens: Option<u64>,
    #[serde(default)]
    personality: Option<String>,
    #[serde(default)]
    seed_context: Option<String>,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum RawProvider {
    Claude { credentials: serde_json::Value },
    Openrouter { key: String },
    Zai { key: String },
    Kimi { key: String },
    Openai { credentials: serde_json::Value },
}

pub struct Plan {
    pub agent_name: String,
    pub cloudflare: Option<crate::tunnel::CloudflareCreds>,
    pub subdomain: Option<String>,
    pub provider_body: serde_json::Value,
    pub config_body: serde_json::Value,
}

/// A credentials field may hold the credentials file's JSON text or the JSON itself.
fn credentials_text(value: serde_json::Value) -> Result<String, String> {
    match value {
        serde_json::Value::String(text) => Ok(text),
        serde_json::Value::Object(_) => Ok(value.to_string()),
        _ => Err("provider credentials must be the credentials file's JSON".to_string()),
    }
}

fn provider_body(
    provider: RawProvider,
    model: Option<String>,
    max_context_tokens: Option<u64>,
) -> Result<serde_json::Value, String> {
    let (mut body, is_claude) = match provider {
        RawProvider::Claude { credentials } => (
            serde_json::json!({"kind": "claude", "credentials": credentials_text(credentials)?}),
            true,
        ),
        RawProvider::Openai { credentials } => (
            serde_json::json!({"kind": "openai", "credentials": credentials_text(credentials)?}),
            false,
        ),
        RawProvider::Openrouter { key } => {
            (serde_json::json!({"kind": "openrouter", "key": key}), false)
        }
        RawProvider::Zai { key } => (serde_json::json!({"kind": "zai", "key": key}), false),
        RawProvider::Kimi { key } => (serde_json::json!({"kind": "kimi", "key": key}), false),
    };
    let model = match (model, is_claude) {
        (Some(model), _) => model,
        (None, true) => CLAUDE_DEFAULT_MODEL.to_string(),
        (None, false) => return Err("`model` is required for this provider".to_string()),
    };
    body["model"] = serde_json::Value::String(model);
    let context = max_context_tokens.or(is_claude.then_some(CLAUDE_DEFAULT_CONTEXT_TOKENS));
    if let Some(tokens) = context {
        body["max_context_tokens"] = serde_json::Value::from(tokens);
    }
    Ok(body)
}

/// serde names fields in backticks but quotes a mistyped string value (`invalid type: string
/// "..."`), which may be a secret put in the wrong place: drop every quoted span.
fn without_quoted_values(message: &str) -> String {
    message
        .split('"')
        .enumerate()
        .map(|(index, part)| if index % 2 == 0 { part } else { "..." })
        .collect::<Vec<_>>()
        .join("\"")
}

pub fn plan_from(raw: &str, file_mode: u32, system_zone: Option<&str>) -> Result<Plan, String> {
    if file_mode & LOOSE_MODE_BITS != 0 {
        return Err(format!(
            "the config holds credentials: its permissions ({file_mode:o}) must not allow group or other access (chmod 600)"
        ));
    }
    let config: RawConfig = serde_json::from_str(raw.trim_start_matches(BYTE_ORDER_MARK))
        .map_err(|e| format!("invalid config: {}", without_quoted_values(&e.to_string())))?;
    let agent_name = crate::docker::normalize_name(&config.agent_name);
    if agent_name.is_empty() {
        return Err(format!("invalid agent name '{}'", config.agent_name));
    }
    if let Some(subdomain) = &config.subdomain {
        if !crate::tunnel::is_valid_subdomain(subdomain) {
            return Err(format!(
                "invalid subdomain '{subdomain}': use lowercase letters, digits, and inner hyphens"
            ));
        }
    }
    let timezone = match config.timezone.as_deref().or(system_zone) {
        Some(zone) => jiff::tz::TimeZone::get(zone)
            .map(|_| zone.to_string())
            .map_err(|_| format!("unknown timezone '{zone}'"))?,
        None => return Err("could not read the machine's timezone: set `timezone`".to_string()),
    };
    let mut config_body = serde_json::json!({"timezone": timezone});
    if let Some(personality) = config.personality {
        config_body["agent_personality"] = serde_json::Value::String(personality);
    }
    if let Some(seed) = config.seed_context {
        config_body["seed_context"] = serde_json::Value::String(seed);
    }
    Ok(Plan {
        agent_name,
        cloudflare: config.cloudflare,
        subdomain: config.subdomain,
        provider_body: provider_body(config.provider, config.model, config.max_context_tokens)?,
        config_body,
    })
}

/// Read and validate the config file with the machine's zone as the timezone default.
pub fn read_plan(path: &std::path::Path) -> Result<Plan, String> {
    use std::os::unix::fs::PermissionsExt;
    let mode = std::fs::metadata(path)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?
        .permissions()
        .mode();
    let raw = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let system_zone = jiff::tz::TimeZone::system().iana_name().map(str::to_string);
    plan_from(&raw, mode, system_zone.as_deref())
}

#[cfg(test)]
mod tests {
    use super::*;

    const PRIVATE: u32 = 0o600;

    fn claude(extra: &str) -> String {
        format!(
            r#"{{"agent_name":"Aria Bot","provider":{{"kind":"claude","credentials":"{{\"claudeAiOauth\":{{}}}}"}}{extra}}}"#
        )
    }

    #[test]
    fn claude_defaults_fill_model_context_and_machine_zone() {
        let plan = plan_from(&claude(""), PRIVATE, Some("Europe/Rome")).expect("valid");
        assert_eq!(plan.agent_name, "aria-bot");
        assert_eq!(plan.provider_body["kind"], "claude");
        assert_eq!(plan.provider_body["model"], "opus-latest");
        assert_eq!(plan.provider_body["max_context_tokens"], 500_000);
        assert_eq!(
            plan.config_body,
            serde_json::json!({"timezone": "Europe/Rome"})
        );
        assert!(plan.cloudflare.is_none());
        assert!(plan.subdomain.is_none());
    }

    #[test]
    fn explicit_fields_pass_through() {
        let raw = claude(
            r#","timezone":"America/New_York","model":"sonnet-latest","max_context_tokens":200000,"personality":"warm","seed_context":"Lucio, likes jazz","subdomain":"otter""#,
        );
        let plan = plan_from(&raw, PRIVATE, None).expect("valid");
        assert_eq!(plan.provider_body["model"], "sonnet-latest");
        assert_eq!(plan.provider_body["max_context_tokens"], 200_000);
        assert_eq!(
            plan.config_body,
            serde_json::json!({"timezone": "America/New_York", "agent_personality": "warm", "seed_context": "Lucio, likes jazz"})
        );
        assert_eq!(plan.subdomain.as_deref(), Some("otter"));
    }

    #[test]
    fn a_credentials_object_is_accepted_as_its_json_text() {
        let raw = r#"{"agent_name":"aria","provider":{"kind":"claude","credentials":{"claudeAiOauth":{"accessToken":"a"}}}}"#;
        let plan = plan_from(raw, PRIVATE, Some("UTC")).expect("valid");
        let text = plan.provider_body["credentials"]
            .as_str()
            .expect("a string");
        assert!(text.contains("claudeAiOauth"));
    }

    #[test]
    fn a_leading_byte_order_mark_is_ignored() {
        let raw = format!("\u{feff}{}", claude(""));
        assert!(plan_from(&raw, PRIVATE, Some("UTC")).is_ok());
    }

    #[test]
    fn key_providers_need_a_model() {
        let raw = r#"{"agent_name":"aria","provider":{"kind":"openrouter","key":"sk"}}"#;
        let err = plan_from(raw, PRIVATE, Some("UTC"))
            .err()
            .expect("model required");
        assert!(err.contains("model"), "{err}");
        let raw =
            r#"{"agent_name":"aria","provider":{"kind":"openrouter","key":"sk"},"model":"x/y"}"#;
        let plan = plan_from(raw, PRIVATE, Some("UTC")).expect("valid");
        assert_eq!(
            plan.provider_body,
            serde_json::json!({"kind":"openrouter","key":"sk","model":"x/y"})
        );
    }

    #[test]
    fn invalid_inputs_are_refused_before_anything_runs() {
        let cases: [(String, u32, Option<&str>, &str); 8] = [
            (claude(""), 0o644, Some("UTC"), "permissions"),
            (
                claude(r#","personalty":"dry""#),
                PRIVATE,
                Some("UTC"),
                "personalty",
            ),
            (
                r#"{"provider":{"kind":"claude","credentials":"x"}}"#.to_string(),
                PRIVATE,
                Some("UTC"),
                "agent_name",
            ),
            (
                claude(r#","timezone":"Mars/Olympus""#),
                PRIVATE,
                None,
                "timezone",
            ),
            (claude(""), PRIVATE, None, "timezone"),
            (
                claude(r#","subdomain":"Bad_Name""#),
                PRIVATE,
                Some("UTC"),
                "subdomain",
            ),
            (
                r#"{"agent_name":"!!!","provider":{"kind":"claude","credentials":"x"}}"#
                    .to_string(),
                PRIVATE,
                Some("UTC"),
                "agent name",
            ),
            (
                r#"{"agent_name":"aria","provider":{"kind":"kimi","key":"k","extra":1},"model":"m"}"#
                    .to_string(),
                PRIVATE,
                Some("UTC"),
                "extra",
            ),
        ];
        for (raw, mode, zone, needle) in cases {
            let err = plan_from(&raw, mode, zone)
                .err()
                .unwrap_or_else(|| panic!("{raw} should fail"));
            assert!(err.contains(needle), "{needle} not in: {err}");
        }
    }

    #[test]
    fn errors_never_echo_a_secret() {
        let raw = r#"{"agent_name":"aria","provider":{"kind":"kimi","key":"sk-SECRET"},"typo":1}"#;
        let err = plan_from(raw, PRIVATE, Some("UTC"))
            .err()
            .expect("unknown field");
        assert!(!err.contains("sk-SECRET"), "{err}");
    }

    #[test]
    fn a_secret_in_the_wrong_place_is_not_echoed() {
        for raw in [
            r#"{"agent_name":"aria","provider":"sk-SECRET"}"#,
            r#"{"agent_name":"aria","provider":{"kind":"claude","credentials":"x"},"cloudflare":"cf-SECRET"}"#,
        ] {
            let err = plan_from(raw, PRIVATE, Some("UTC"))
                .err()
                .expect("wrong type");
            assert!(!err.contains("SECRET"), "{err}");
            assert!(err.contains("invalid type"), "{err}");
        }
    }
}
