//! Per-agent authentication state.
//!
//! Manages the two ways an agent can be authenticated:
//! - Claude OAuth credentials in /root/.claude/.credentials.json
//! - OpenRouter API key + model in /root/.claude/vesta-provider.env
//!
//! The provider env file's exports override anything Claude credentials carry,
//! so it's also the source of truth for which mode the agent boots into.

use bollard::Docker;
use serde::Deserialize;

use crate::docker::{DockerError, container_name, docker_cp_content, read_container_file};

const CREDENTIALS_PATH: &str = "/root/.claude/.credentials.json";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";
pub const PROVIDER_ENV_PATH: &str = "/root/.claude/vesta-provider.env";

/// Cheap haiku-class model the SDK reaches for on background work (compaction probes,
/// summarization, intent classification). Hardcoded so picking an expensive primary
/// model doesn't silently 5–10× background spend. Editable in the provider file post-create.
const OPENROUTER_SMALL_FAST_MODEL: &str = "anthropic/claude-haiku-4.5";

/// Per-agent OpenRouter settings, injected into the container fs at PROVIDER_ENV_PATH (never on the host).
#[derive(Deserialize, Clone)]
pub struct OpenRouterConfig {
    pub api_key: String,
    pub model: String,
    pub zdr: bool,
}

/// Bound view over one agent's auth state. Cheap to construct; doesn't cache.
pub struct AgentAuth<'a> {
    docker: &'a Docker,
    cname: String,
}

impl<'a> AgentAuth<'a> {
    pub fn for_agent(docker: &'a Docker, agent_name: &str) -> Self {
        Self {
            docker,
            cname: container_name(agent_name),
        }
    }

    pub fn for_container(docker: &'a Docker, cname: impl Into<String>) -> Self {
        Self {
            docker,
            cname: cname.into(),
        }
    }

    /// True if the agent has usable credentials for the mode it's actually in.
    /// Checks the provider file first because its env vars are what the container
    /// boots with; stale Claude credentials on an OpenRouter agent don't count.
    pub async fn is_authenticated(&self) -> bool {
        if let Some(provider) = read_container_file(self.docker, &self.cname, PROVIDER_ENV_PATH).await {
            if provider_declares_openrouter(&provider) {
                return openrouter_token_present(&provider);
            }
        }
        // Claude mode: valid access token, OR a refresh token (SDK auto-refreshes on demand).
        read_container_file(self.docker, &self.cname, CREDENTIALS_PATH)
            .await
            .as_deref()
            .is_some_and(check_claude_auth)
    }

    pub async fn set_claude(&self, credentials: &str) -> Result<(), DockerError> {
        docker_cp_content(self.docker, &self.cname, credentials, CREDENTIALS_PATH).await?;
        docker_cp_content(
            self.docker,
            &self.cname,
            "{\"hasCompletedOnboarding\":true}",
            CLAUDE_JSON_PATH,
        )
        .await
    }

    pub async fn set_openrouter(&self, cfg: &OpenRouterConfig) -> Result<(), DockerError> {
        docker_cp_content(
            self.docker,
            &self.cname,
            &openrouter_provider_file(cfg),
            PROVIDER_ENV_PATH,
        )
        .await
    }

    /// Overwrite the provider file with empty content. The entrypoint will source
    /// it as a no-op, leaving any Claude credentials in effect. Used when switching
    /// an agent from OpenRouter back to Claude.
    pub async fn clear_openrouter(&self) -> Result<(), DockerError> {
        docker_cp_content(self.docker, &self.cname, "", PROVIDER_ENV_PATH).await
    }
}

fn check_claude_auth(content: &str) -> bool {
    let Ok(creds) = serde_json::from_str::<serde_json::Value>(content) else {
        return false;
    };
    let oauth = &creds["claudeAiOauth"];
    // A refresh token lets the SDK mint a fresh access token on demand, so an
    // expired expiresAt isn't a problem — the SDK refreshes transparently.
    if oauth["refreshToken"]
        .as_str()
        .is_some_and(|t| !t.is_empty())
    {
        return true;
    }
    oauth["expiresAt"]
        .as_u64()
        .is_some_and(|t| t > crate::time_utils::now_epoch_millis() as u64)
}

fn provider_declares_openrouter(file: &str) -> bool {
    file.lines()
        .any(|line| parse_shell_export(line, "AGENT_PROVIDER").as_deref() == Some("openrouter"))
}

fn openrouter_token_present(file: &str) -> bool {
    file.lines().any(|line| {
        parse_shell_export(line, "ANTHROPIC_AUTH_TOKEN").is_some_and(|v| !v.is_empty())
    })
}

/// Parse a single `[export ]KEY=value` shell line; returns the unquoted value if
/// `key` matches. Skips blank lines and `#`-comments. Strips one layer of single
/// quotes (matching `shell_single_quote`'s output).
fn parse_shell_export(line: &str, key: &str) -> Option<String> {
    let line = line.trim();
    if line.is_empty() || line.starts_with('#') {
        return None;
    }
    let line = line.strip_prefix("export ").unwrap_or(line);
    let (k, v) = line.split_once('=')?;
    if k.trim() != key {
        return None;
    }
    let v = v.trim();
    let unquoted = v
        .strip_prefix('\'')
        .and_then(|s| s.strip_suffix('\''))
        .unwrap_or(v);
    Some(unquoted.to_string())
}

/// Single-quote a value for safe sourcing (key/model are user input); escapes embedded quotes.
fn shell_single_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

/// The sourced shell file that puts an agent into OpenRouter mode. ANTHROPIC_BASE_URL is set at
/// runtime to the local ZDR proxy; the SDK sends ANTHROPIC_AUTH_TOKEN as the bearer token through it.
fn openrouter_provider_file(cfg: &OpenRouterConfig) -> String {
    let model = shell_single_quote(&cfg.model);
    let key = shell_single_quote(&cfg.api_key);
    let small_fast = shell_single_quote(OPENROUTER_SMALL_FAST_MODEL);
    let zdr = if cfg.zdr { 1 } else { 0 };
    format!(
        "export AGENT_PROVIDER=openrouter\n\
         export AGENT_MODEL={model}\n\
         export ANTHROPIC_AUTH_TOKEN={key}\n\
         export ANTHROPIC_API_KEY=\n\
         export ANTHROPIC_SMALL_FAST_MODEL={small_fast}\n\
         export OPENROUTER_ZDR={zdr}\n",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn openrouter_provider_file_format() {
        let zdr_on = openrouter_provider_file(&OpenRouterConfig {
            api_key: "sk-or-v1-xyz".into(),
            model: "anthropic/claude-sonnet-4-6".into(),
            zdr: true,
        });
        assert!(zdr_on.contains("export AGENT_PROVIDER=openrouter\n"));
        assert!(zdr_on.contains("export AGENT_MODEL='anthropic/claude-sonnet-4-6'\n"));
        assert!(zdr_on.contains("export ANTHROPIC_AUTH_TOKEN='sk-or-v1-xyz'\n"));
        assert!(zdr_on.contains("export ANTHROPIC_API_KEY=\n"));
        assert!(zdr_on.contains("export ANTHROPIC_SMALL_FAST_MODEL='anthropic/claude-haiku-4.5'\n"));
        assert!(zdr_on.contains("export OPENROUTER_ZDR=1\n"));

        let zdr_off = openrouter_provider_file(&OpenRouterConfig {
            api_key: "k".into(),
            model: "deepseek/deepseek-v4".into(),
            zdr: false,
        });
        assert!(zdr_off.contains("export OPENROUTER_ZDR=0\n"));
    }

    #[test]
    fn openrouter_auth_check_rejects_partial_or_commented_files() {
        let happy = "export AGENT_PROVIDER=openrouter\nexport ANTHROPIC_AUTH_TOKEN='sk-or-v1-xyz'\n";
        assert!(provider_declares_openrouter(happy));
        assert!(openrouter_token_present(happy));

        let commented = "# export AGENT_PROVIDER=openrouter\nexport ANTHROPIC_AUTH_TOKEN='sk-or-v1-xyz'\n";
        assert!(!provider_declares_openrouter(commented));

        let extended = "export AGENT_PROVIDER=openrouter_test\nexport ANTHROPIC_AUTH_TOKEN='sk-or-v1-xyz'\n";
        assert!(!provider_declares_openrouter(extended));

        let empty_token = "export AGENT_PROVIDER=openrouter\nexport ANTHROPIC_AUTH_TOKEN=''\n";
        assert!(provider_declares_openrouter(empty_token));
        assert!(!openrouter_token_present(empty_token));

        let no_token = "export AGENT_PROVIDER=openrouter\n";
        assert!(provider_declares_openrouter(no_token));
        assert!(!openrouter_token_present(no_token));

        let substring_only = "# example: AGENT_PROVIDER=openrouter\n";
        assert!(!provider_declares_openrouter(substring_only));
    }

    #[test]
    fn openrouter_provider_file_escapes_shell_metacharacters() {
        let injected = openrouter_provider_file(&OpenRouterConfig {
            api_key: "k'; touch /tmp/pwned #".into(),
            model: "m".into(),
            zdr: true,
        });
        assert!(injected.contains(r"export ANTHROPIC_AUTH_TOKEN='k'\''; touch /tmp/pwned #'"));
        assert!(!injected.contains("TOKEN=k';"));
    }

    #[test]
    fn claude_auth_valid_access_token() {
        let creds = serde_json::json!({
            "claudeAiOauth": {
                "accessToken": "a",
                "expiresAt": u64::MAX,
            }
        })
        .to_string();
        assert!(check_claude_auth(&creds));
    }

    #[test]
    fn claude_auth_expired_with_refresh_token_still_passes() {
        // Expired access token but refresh token present — SDK auto-refreshes.
        let creds = serde_json::json!({
            "claudeAiOauth": {
                "accessToken": "a",
                "expiresAt": 0u64,
                "refreshToken": "r",
            }
        })
        .to_string();
        assert!(check_claude_auth(&creds));
    }

    #[test]
    fn claude_auth_expired_no_refresh_fails() {
        let creds = serde_json::json!({
            "claudeAiOauth": {
                "accessToken": "a",
                "expiresAt": 0u64,
            }
        })
        .to_string();
        assert!(!check_claude_auth(&creds));
    }

    #[test]
    fn claude_auth_empty_refresh_token_doesnt_count() {
        let creds = serde_json::json!({
            "claudeAiOauth": {
                "accessToken": "a",
                "expiresAt": 0u64,
                "refreshToken": "",
            }
        })
        .to_string();
        assert!(!check_claude_auth(&creds));
    }

    #[test]
    fn claude_auth_malformed_json_fails() {
        assert!(!check_claude_auth("not json"));
        assert!(!check_claude_auth("{}"));
        assert!(!check_claude_auth(r#"{"claudeAiOauth": null}"#));
    }
}
