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

pub trait GatewayApi {
    /// The agent's status (`alive`, `setting_up`, ...), `None` when it does not exist.
    fn agent_status(&self, name: &str) -> Result<Option<String>, String>;
    fn create_agent(&self, name: &str) -> Result<(), String>;
    fn put_provider(&self, name: &str, body: &serde_json::Value) -> Result<(), String>;
    fn put_config(&self, name: &str, body: &serde_json::Value) -> Result<(), String>;
    fn restart(&self, name: &str) -> Result<(), String>;
    fn delete_agent(&self, name: &str) -> Result<(), String>;
}

pub struct Readiness {
    pub timeout: std::time::Duration,
    pub poll: std::time::Duration,
}

pub fn ensure_absent(api: &impl GatewayApi, name: &str) -> Result<(), String> {
    match api.agent_status(name)? {
        None => Ok(()),
        Some(_) => Err(format!(
            "an agent named '{name}' already exists on this gateway"
        )),
    }
}

/// Create the agent, then sign in, configure, restart, and wait. Everything after the create is
/// all or nothing: a failure deletes the agent this call created.
pub fn provision_agent(
    api: &impl GatewayApi,
    plan: &Plan,
    readiness: &Readiness,
) -> Result<(), String> {
    let name = plan.agent_name.as_str();
    eprintln!("creating agent '{name}' (the first agent on a machine pulls the image)...");
    api.create_agent(name)?;
    let Err(error) = finish_agent(api, plan, readiness) else {
        return Ok(());
    };
    eprintln!("removing the agent '{name}' this run created...");
    match api.delete_agent(name) {
        Ok(()) => Err(error),
        Err(delete_error) => Err(format!(
            "{error}; the agent '{name}' could not be removed ({delete_error}): delete it before running provision again"
        )),
    }
}

fn finish_agent(api: &impl GatewayApi, plan: &Plan, readiness: &Readiness) -> Result<(), String> {
    let name = plan.agent_name.as_str();
    eprintln!("signing in...");
    api.put_provider(name, &plan.provider_body)?;
    eprintln!("applying configuration...");
    api.put_config(name, &plan.config_body)?;
    eprintln!("restarting the agent...");
    api.restart(name)?;
    wait_until_ready(api, name, readiness)
}

/// Poll until the agent runs. Only a rejected credential or a dead container ends the wait early:
/// right after a restart the gateway can still report the agent missing, stopped, or with its
/// pre-restart readiness, so every other status is waited out.
fn wait_until_ready(
    api: &impl GatewayApi,
    name: &str,
    readiness: &Readiness,
) -> Result<(), String> {
    let deadline = std::time::Instant::now() + readiness.timeout;
    let mut last_seen = None;
    loop {
        match api.agent_status(name)?.as_deref() {
            Some("alive" | "setting_up") => return Ok(()),
            Some("not_authenticated") => return Err("the credential was rejected".to_string()),
            Some("dead") => return Err("the agent did not start (dead)".to_string()),
            Some(state) => last_seen = Some(state.to_string()),
            None => {}
        }
        if std::time::Instant::now() >= deadline {
            let last =
                last_seen.map_or_else(String::new, |state| format!(" (last status: {state})"));
            return Err(format!(
                "the agent did not become ready within {}s{last}",
                readiness.timeout.as_secs()
            ));
        }
        std::thread::sleep(readiness.poll);
    }
}

/// Create (the first agent on a machine pulls the image) and restart (a drifted container is
/// rebuilt) can take minutes; this matches vestad's own deadline for them, so the client never
/// gives up on a request the gateway still runs.
const LONGRUN_REQUEST_TIMEOUT_SECS: u64 = 1800;
const REQUEST_TIMEOUT_SECS: u64 = 120;

/// `GatewayApi` over the gateway's loopback HTTP port, authenticated with the api key.
pub struct HttpGatewayApi {
    base_url: String,
    api_key: String,
    runtime: tokio::runtime::Runtime,
    client: reqwest::Client,
}

impl HttpGatewayApi {
    pub fn new(base_url: String, api_key: String) -> Result<Self, String> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| format!("could not start the runtime: {e}"))?;
        let client = reqwest::Client::builder()
            .build()
            .map_err(|e| format!("could not build the http client: {e}"))?;
        Ok(Self {
            base_url,
            api_key,
            runtime,
            client,
        })
    }

    fn send(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&serde_json::Value>,
        timeout_secs: u64,
    ) -> Result<(reqwest::StatusCode, serde_json::Value), String> {
        self.runtime.block_on(async {
            let mut request = self
                .client
                .request(method, format!("{}{path}", self.base_url))
                .bearer_auth(&self.api_key)
                .timeout(std::time::Duration::from_secs(timeout_secs));
            if let Some(body) = body {
                request = request.json(body);
            }
            let response = request
                .send()
                .await
                .map_err(|e| format!("could not reach vestad: {e}"))?;
            let status = response.status();
            let json = response.json().await.unwrap_or(serde_json::Value::Null);
            Ok((status, json))
        })
    }

    /// Send and require a 2xx; vestad names every failure in the body's `error`.
    fn expect_success(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&serde_json::Value>,
        timeout_secs: u64,
    ) -> Result<(), String> {
        let (status, json) = self.send(method, path, body, timeout_secs)?;
        if status.is_success() {
            return Ok(());
        }
        Err(json["error"].as_str().map_or_else(
            || format!("vestad answered {status} on {path}"),
            str::to_string,
        ))
    }
}

impl GatewayApi for HttpGatewayApi {
    fn agent_status(&self, name: &str) -> Result<Option<String>, String> {
        let (status, json) = self.send(
            reqwest::Method::GET,
            &format!("/agents/{name}"),
            None,
            REQUEST_TIMEOUT_SECS,
        )?;
        if status == reqwest::StatusCode::NOT_FOUND {
            return Ok(None);
        }
        match json["status"].as_str() {
            Some("not_found") => Ok(None),
            Some(state) => Ok(Some(state.to_string())),
            None => Err(format!("vestad answered {status} for the agent status")),
        }
    }
    fn create_agent(&self, name: &str) -> Result<(), String> {
        let body = serde_json::json!({"name": name});
        self.expect_success(
            reqwest::Method::POST,
            "/agents",
            Some(&body),
            LONGRUN_REQUEST_TIMEOUT_SECS,
        )
    }
    fn put_provider(&self, name: &str, body: &serde_json::Value) -> Result<(), String> {
        self.expect_success(
            reqwest::Method::PUT,
            &format!("/agents/{name}/provider"),
            Some(body),
            REQUEST_TIMEOUT_SECS,
        )
    }
    fn put_config(&self, name: &str, body: &serde_json::Value) -> Result<(), String> {
        self.expect_success(
            reqwest::Method::PUT,
            &format!("/agents/{name}/config"),
            Some(body),
            REQUEST_TIMEOUT_SECS,
        )
    }
    fn restart(&self, name: &str) -> Result<(), String> {
        self.expect_success(
            reqwest::Method::POST,
            &format!("/agents/{name}/restart"),
            None,
            LONGRUN_REQUEST_TIMEOUT_SECS,
        )
    }
    fn delete_agent(&self, name: &str) -> Result<(), String> {
        self.expect_success(
            reqwest::Method::DELETE,
            &format!("/agents/{name}"),
            None,
            REQUEST_TIMEOUT_SECS,
        )
    }
}

const GATEWAY_PROBE_TIMEOUT_SECS: u64 = 3;
const GATEWAY_READY_TIMEOUT_SECS: u64 = 60;
const AGENT_READY_TIMEOUT_SECS: u64 = 300;
const AGENT_READY_POLL_MILLIS: u64 = 2000;

/// Whether this HOME's gateway answers its health port within `timeout_secs`.
fn gateway_answers(config: &std::path::Path, timeout_secs: u64) -> Result<bool, String> {
    let Some(url) = crate::local_health_url(config) else {
        return Ok(false);
    };
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("could not start the runtime: {e}"))?;
    let client = reqwest::Client::new();
    Ok(runtime.block_on(crate::wait_for_health(
        &client,
        &url,
        std::time::Duration::from_secs(timeout_secs),
    )))
}

/// Settle the tunnel and start the gateway service, unless a gateway already answers (then its
/// tunnel is left as it is). Then create the agent and return the connect link.
pub fn run(config_path: &std::path::Path) -> Result<String, String> {
    let plan = read_plan(config_path)?;
    let config = crate::config_dir();
    if gateway_answers(&config, GATEWAY_PROBE_TIMEOUT_SECS)? {
        if plan.cloudflare.is_some() || plan.subdomain.is_some() {
            eprintln!("warning: the gateway already runs; its tunnel is left as it is");
        }
    } else {
        match &plan.cloudflare {
            Some(creds) => {
                eprintln!("setting up the tunnel...");
                let tunnel =
                    crate::tunnel::provision_tunnel(&config, creds, plan.subdomain.as_deref())?;
                eprintln!("tunnel ready at {}", tunnel.url());
            }
            None => crate::tunnel::decline_tunnel(&config)?,
        }
        eprintln!("starting the gateway service...");
        crate::install_service()?;
        crate::start_installed_service(&config)?;
        if !gateway_answers(&config, GATEWAY_READY_TIMEOUT_SECS)? {
            return Err(format!(
                "the gateway did not answer within {GATEWAY_READY_TIMEOUT_SECS}s: see `vestad logs`"
            ));
        }
    }
    let port = crate::read_port_file(&config).ok_or("the gateway wrote no port file")?;
    let api_key = crate::read_api_key(&config).ok_or("the gateway has no api key")?;
    let http_port = port.checked_add(1).ok_or("invalid gateway port")?;
    let api = HttpGatewayApi::new(format!("http://127.0.0.1:{http_port}"), api_key.clone())?;
    ensure_absent(&api, &plan.agent_name)?;
    let readiness = Readiness {
        timeout: std::time::Duration::from_secs(AGENT_READY_TIMEOUT_SECS),
        poll: std::time::Duration::from_millis(AGENT_READY_POLL_MILLIS),
    };
    provision_agent(&api, &plan, &readiness)?;
    let base_url = crate::tunnel::get_tunnel_config(&config).map_or_else(
        || format!("http://localhost:{http_port}"),
        |tunnel| tunnel.url(),
    );
    Ok(crate::status::connect_link(&base_url, &api_key))
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

    use std::cell::RefCell;
    use std::collections::VecDeque;

    #[derive(Default)]
    struct FakeApi {
        calls: RefCell<Vec<String>>,
        statuses: RefCell<VecDeque<Option<String>>>,
        fail_on: Option<&'static str>,
        fail_delete: bool,
    }

    impl FakeApi {
        fn with_statuses(statuses: &[Option<&str>]) -> Self {
            Self {
                statuses: RefCell::new(statuses.iter().map(|s| s.map(str::to_string)).collect()),
                ..Self::default()
            }
        }
        fn record(&self, call: &str, name: &str) -> Result<(), String> {
            self.calls.borrow_mut().push(format!("{call} {name}"));
            if self.fail_on == Some(call) {
                return Err(format!("{call} refused"));
            }
            Ok(())
        }
    }

    impl GatewayApi for FakeApi {
        fn agent_status(&self, name: &str) -> Result<Option<String>, String> {
            self.calls.borrow_mut().push(format!("status {name}"));
            Ok(self.statuses.borrow_mut().pop_front().flatten())
        }
        fn create_agent(&self, name: &str) -> Result<(), String> {
            self.record("create", name)
        }
        fn put_provider(&self, name: &str, _: &serde_json::Value) -> Result<(), String> {
            self.record("provider", name)
        }
        fn put_config(&self, name: &str, _: &serde_json::Value) -> Result<(), String> {
            self.record("config", name)
        }
        fn restart(&self, name: &str) -> Result<(), String> {
            self.record("restart", name)
        }
        fn delete_agent(&self, name: &str) -> Result<(), String> {
            self.calls.borrow_mut().push(format!("delete {name}"));
            if self.fail_delete {
                Err("delete refused".to_string())
            } else {
                Ok(())
            }
        }
    }

    const FAST: Readiness = Readiness {
        timeout: std::time::Duration::from_millis(200),
        poll: std::time::Duration::from_millis(1),
    };

    fn plan() -> Plan {
        plan_from(&claude(""), PRIVATE, Some("UTC")).expect("valid")
    }

    fn calls(api: &FakeApi) -> Vec<String> {
        api.calls.borrow().clone()
    }

    #[test]
    fn a_new_agent_is_created_signed_in_configured_and_restarted_in_order() {
        let api = FakeApi::with_statuses(&[Some("restarting"), Some("setting_up")]);
        provision_agent(&api, &plan(), &FAST).expect("provisioned");
        assert_eq!(
            calls(&api),
            [
                "create aria-bot",
                "provider aria-bot",
                "config aria-bot",
                "restart aria-bot",
                "status aria-bot",
                "status aria-bot"
            ]
        );
    }

    #[test]
    fn an_existing_agent_is_an_error_with_no_change() {
        let api = FakeApi::with_statuses(&[Some("alive")]);
        let err = ensure_absent(&api, "aria-bot").expect_err("exists");
        assert!(err.contains("already exists"), "{err}");
        assert_eq!(calls(&api), ["status aria-bot"]);
    }

    #[test]
    fn a_failed_sign_in_deletes_the_new_agent_and_keeps_the_original_error() {
        let api = FakeApi {
            fail_on: Some("provider"),
            ..FakeApi::default()
        };
        let err = provision_agent(&api, &plan(), &FAST).expect_err("sign-in fails");
        assert!(err.contains("provider refused"), "{err}");
        assert_eq!(
            calls(&api),
            ["create aria-bot", "provider aria-bot", "delete aria-bot"]
        );
    }

    #[test]
    fn a_rejected_credential_is_named_and_rolled_back() {
        let api = FakeApi::with_statuses(&[Some("not_authenticated")]);
        let err = provision_agent(&api, &plan(), &FAST).expect_err("rejected");
        assert!(err.contains("credential was rejected"), "{err}");
        assert_eq!(
            calls(&api).last().map(String::as_str),
            Some("delete aria-bot")
        );
    }

    #[test]
    fn a_readiness_timeout_rolls_back() {
        let api = FakeApi::default();
        let err = provision_agent(&api, &plan(), &FAST).expect_err("never ready");
        assert!(err.contains("did not become ready"), "{err}");
        assert_eq!(
            calls(&api).last().map(String::as_str),
            Some("delete aria-bot")
        );
    }

    #[test]
    fn a_stale_status_right_after_the_restart_is_waited_out() {
        let api = FakeApi::with_statuses(&[Some("unprovisioned"), Some("stopped"), Some("alive")]);
        provision_agent(&api, &plan(), &FAST).expect("provisioned");
    }

    #[test]
    fn a_timeout_names_the_last_status_seen() {
        let api = FakeApi::with_statuses(&[Some("unprovisioned")]);
        let err = provision_agent(&api, &plan(), &FAST).expect_err("never ready");
        assert!(err.contains("last status: unprovisioned"), "{err}");
    }

    #[test]
    fn a_dead_container_fails_at_once() {
        let api = FakeApi::with_statuses(&[Some("dead")]);
        let err = provision_agent(&api, &plan(), &FAST).expect_err("dead");
        assert!(err.contains("did not start (dead)"), "{err}");
        assert_eq!(
            calls(&api)
                .iter()
                .filter(|call| call.starts_with("status"))
                .count(),
            1
        );
    }

    #[test]
    fn a_failed_create_leaves_nothing_to_delete() {
        let api = FakeApi {
            fail_on: Some("create"),
            ..FakeApi::default()
        };
        provision_agent(&api, &plan(), &FAST).expect_err("create fails");
        assert_eq!(calls(&api), ["create aria-bot"]);
    }

    #[test]
    fn a_failed_rollback_reports_both_errors() {
        let api = FakeApi {
            fail_on: Some("config"),
            fail_delete: true,
            ..FakeApi::default()
        };
        let err = provision_agent(&api, &plan(), &FAST).expect_err("both fail");
        assert!(
            err.contains("config refused") && err.contains("delete refused"),
            "{err}"
        );
        assert!(
            err.contains("aria-bot"),
            "the operator must learn which agent was left: {err}"
        );
    }
}
