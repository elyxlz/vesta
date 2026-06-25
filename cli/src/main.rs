use clap::{Parser, Subcommand};
use std::io::{self, Write};
use std::path::PathBuf;
use std::process;
mod client;
mod common;
mod platform;

use common::{fetch_latest_release_tag, version_less_than};

const VERSION_CACHE_TTL_SECS: u64 = 3600;
const UPDATE_CHECK_TIMEOUT_MS: u64 = 100;
const UPDATE_CHECK_POLL_MS: u64 = 10;
// Pads for first-start setup (git fetch, npm install, vite build, etc.).
const START_READY_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(900);

fn format_size(bytes: u64) -> String {
    if bytes >= 1_000_000_000 {
        format!("{:.1}GB", bytes as f64 / 1_000_000_000.0)
    } else if bytes >= 1_000_000 {
        format!("{:.1}MB", bytes as f64 / 1_000_000.0)
    } else if bytes >= 1_000 {
        format!("{:.0}kB", bytes as f64 / 1_000.0)
    } else {
        format!("{bytes}B")
    }
}

fn try_open_browser(url: &str) {
    #[cfg(target_os = "linux")]
    let (program, args): (&str, &[&str]) = ("xdg-open", &[url]);
    #[cfg(target_os = "macos")]
    let (program, args): (&str, &[&str]) = ("open", &[url]);
    #[cfg(target_os = "windows")]
    let (program, args): (&str, &[&str]) = ("cmd", &["/c", "start", "", url]);
    let _child = process::Command::new(program)
        .args(args)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn();
}

#[derive(Parser)]
#[command(name = "vesta", version, about = "manage your vesta agents")]
struct Cli {
    /// Server host (overrides config)
    #[arg(long, global = true)]
    host: Option<String>,
    /// API token (overrides config)
    #[arg(long, global = true)]
    token: Option<String>,
    #[command(subcommand)]
    command: Option<Command>,
}

/// Flags shared by `setup` and `create` for running an agent on OpenRouter instead of a Claude account.
#[derive(clap::Args)]
struct OpenRouterFlags {
    /// Run on OpenRouter with this API key instead of a Claude account (requires --openrouter-model)
    #[arg(long)]
    openrouter_key: Option<String>,
    /// OpenRouter model slug, e.g. "anthropic/claude-sonnet-4-6"
    #[arg(long)]
    openrouter_model: Option<String>,
}

#[derive(Subcommand)]
enum Command {
    /// Create agent, start it, and authenticate (prompts for Claude vs OpenRouter)
    Setup {
        /// Skip prompts: assume yes, and default to a Claude account unless --openrouter-key is given
        #[arg(long, short)]
        yes: bool,
        /// Agent name (prompted interactively if omitted)
        #[arg(long)]
        name: Option<String>,
        /// Use the Docker image's baked-in code instead of vestad-managed core code
        #[arg(long)]
        no_manage_core_code: bool,
        /// Claude OAuth credentials JSON, to provision Claude without the interactive
        /// login (the non-interactive counterpart to the OpenRouter flags). Get it
        /// from `vesta auth` or an existing agent.
        #[arg(long)]
        claude_token: Option<String>,
        /// Claude model: opus | sonnet | haiku (prompted on an interactive Claude setup if omitted)
        #[arg(long)]
        claude_model: Option<String>,
        /// Context window in tokens, e.g. 200000 / 500000 / 1000000 (prompted if omitted; Claude default is 1M)
        #[arg(long)]
        context_window: Option<u64>,
        #[command(flatten)]
        openrouter: OpenRouterFlags,
    },
    /// Create an agent container (without starting or authenticating)
    Create {
        /// Agent name (prompted interactively if omitted)
        #[arg(long)]
        name: Option<String>,
        /// Use the Docker image's baked-in code instead of vestad-managed core code
        #[arg(long)]
        no_manage_core_code: bool,
        #[command(flatten)]
        openrouter: OpenRouterFlags,
    },
    /// Start an agent (or all agents if no name given)
    Start {
        /// Agent name (starts all if omitted)
        name: Option<String>,
    },
    /// Stop an agent
    Stop {
        /// Agent name
        name: String,
    },
    /// Restart an agent
    Restart {
        /// Agent name
        name: String,
    },
    /// Manage the remote vestad gateway daemon
    Gateway {
        #[command(subcommand)]
        action: GatewayAction,
    },
    /// Authenticate Claude for an agent
    Auth {
        /// Agent name
        name: String,
        /// Provide a token directly (skip interactive flow)
        #[arg(long)]
        token: Option<String>,
    },
    /// Interactive chat with an agent
    Chat {
        /// Agent name
        name: String,
    },
    /// Tail agent logs
    Logs {
        /// Agent name
        name: String,
        /// Number of lines to show initially
        #[arg(long, default_value = "500")]
        tail: u64,
    },
    /// Show agent status
    Status {
        /// Agent name
        name: String,
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Manage agent backups
    Backup {
        #[command(subcommand)]
        action: BackupAction,
    },
    /// View or change agent settings. With no flags, prints model + context window
    /// (manage_agent_code is fixed at create time and read-only here).
    Settings {
        /// Agent name
        name: String,
        /// Change the model: opus | sonnet | haiku (Claude), or an OpenRouter slug
        #[arg(long)]
        model: Option<String>,
        /// Change the context window in tokens, e.g. 200000 / 500000 / 1000000
        #[arg(long)]
        context_window: Option<u64>,
    },
    /// Sign out an agent: clear its provider credentials. It stays running but can't respond
    /// until you reconnect a provider with `vesta auth`.
    Logout {
        /// Agent name
        name: String,
    },
    /// View or edit an agent's constitution (a charter prepended to its memory; the agent
    /// cannot edit it). With no flags, prints the current constitution.
    Constitution {
        /// Agent name
        name: String,
        /// Open the current constitution in $EDITOR and save on exit
        #[arg(long)]
        edit: bool,
        /// Set the constitution from a file ('-' reads stdin)
        #[arg(long, conflicts_with_all = ["edit", "clear"])]
        file: Option<PathBuf>,
        /// Clear the constitution
        #[arg(long, conflicts_with_all = ["edit", "file"])]
        clear: bool,
    },
    /// Destroy an agent (irreversible)
    Destroy {
        /// Agent name
        name: String,
    },
    /// Snapshot, destroy, recreate, restore auth
    Rebuild {
        /// Agent name
        name: String,
    },
    /// Wait for agent to become ready
    WaitReady {
        /// Agent name
        name: String,
        /// Timeout in seconds
        #[arg(long, default_value = "30")]
        timeout: u64,
    },
    /// List all agents
    List {
        /// Output as JSON
        #[arg(long)]
        json: bool,
    },
    /// Connect to a remote server (paste the connect link vestad printed)
    Connect {
        /// The connect link vestad printed, e.g. https://host/app#k=key
        link: String,
    },
    /// Update vesta to the latest version
    Update,
    /// Show or set the release channel (stable or beta) on the connected vestad
    Channel {
        /// Channel to switch to: stable or beta. Omit to show the current channel.
        channel: Option<String>,
    },
    /// Show or set whether vestad applies updates automatically
    AutoUpdate {
        /// Set to "on" or "off" (omit to show current status)
        toggle: Option<Toggle>,
    },
    /// Uninstall vesta CLI and remove config
    Uninstall,
    /// Print version information
    Version,
}

#[derive(Subcommand)]
enum GatewayAction {
    /// Restart the remote vestad daemon
    Restart,
    /// Stream vestad logs from the remote gateway
    Logs {
        /// Number of lines to show initially
        #[arg(long, default_value = "500")]
        tail: u64,
        /// Follow the log (tail -f)
        #[arg(long, short)]
        follow: bool,
    },
}

#[derive(Subcommand)]
enum BackupAction {
    /// Create a new backup
    Create {
        /// Agent name
        name: String,
    },
    /// List existing backups
    List {
        /// Agent name
        name: String,
    },
    /// List all backups across all agents (including orphaned)
    ListAll,
    /// Restore an agent from a backup
    Restore {
        /// Agent name
        name: String,
        /// Backup ID (from `vesta backup list`)
        backup_id: String,
    },
    /// Delete a backup
    Delete {
        /// Agent name
        name: String,
        /// Backup ID (from `vesta backup list`)
        backup_id: String,
    },
    /// Show or set auto-backup status
    AutoBackup {
        /// Set to "on" or "off" (omit to show current status)
        toggle: Option<Toggle>,
    },
    /// Show or set backup retention policy
    Retention {
        /// Daily backups to keep
        #[arg(long)]
        daily: Option<usize>,
        /// Weekly backups to keep
        #[arg(long)]
        weekly: Option<usize>,
        /// Monthly backups to keep
        #[arg(long)]
        monthly: Option<usize>,
    },
    /// Show or set per-agent backup settings
    Settings {
        /// Agent name
        name: String,
        /// Enable or disable backups for this agent
        #[arg(long)]
        enabled: Option<Toggle>,
        /// Daily backups to keep (per-agent override)
        #[arg(long)]
        daily: Option<usize>,
        /// Weekly backups to keep (per-agent override)
        #[arg(long)]
        weekly: Option<usize>,
        /// Monthly backups to keep (per-agent override)
        #[arg(long)]
        monthly: Option<usize>,
        /// Remove per-agent override, revert to global settings
        #[arg(long)]
        reset: bool,
    },
}

#[derive(Clone, clap::ValueEnum)]
enum Toggle {
    On,
    Off,
}

/// Build a `{daily?, weekly?, monthly?}` retention object from the optional flags,
/// omitting any the user didn't pass.
fn retention_map(daily: Option<usize>, weekly: Option<usize>, monthly: Option<usize>) -> serde_json::Map<String, serde_json::Value> {
    let mut ret = serde_json::Map::new();
    if let Some(d) = daily { ret.insert("daily".into(), d.into()); }
    if let Some(w) = weekly { ret.insert("weekly".into(), w.into()); }
    if let Some(m) = monthly { ret.insert("monthly".into(), m.into()); }
    ret
}

/// Pull the `(daily, weekly, monthly)` counts out of a retention object,
/// defaulting any missing field to 0.
fn retention_fields(ret: &serde_json::Value) -> (u64, u64, u64) {
    (
        ret["daily"].as_u64().unwrap_or(0),
        ret["weekly"].as_u64().unwrap_or(0),
        ret["monthly"].as_u64().unwrap_or(0),
    )
}

fn print_retention(ret: &serde_json::Value) {
    let (daily, weekly, monthly) = retention_fields(ret);
    eprintln!("retention: daily={daily}, weekly={weekly}, monthly={monthly}");
}

fn print_agent_backup_settings(result: &serde_json::Value) {
    let enabled = result["enabled"].as_bool().unwrap_or(true);
    let has_override = result["has_override"].as_bool().unwrap_or(false);
    eprintln!("  enabled: {} {}", if enabled { "yes" } else { "no" },
        if has_override { "(override)" } else { "(global)" });
    let (daily, weekly, monthly) = retention_fields(&result["retention"]);
    eprintln!("  retention: daily={daily}, weekly={weekly}, monthly={monthly}");
}

fn read_file_or_stdin(path: &std::path::Path) -> String {
    if path == std::path::Path::new("-") {
        let mut buf = String::new();
        io::Read::read_to_string(&mut io::stdin(), &mut buf)
            .unwrap_or_else(|e| platform::die(&format!("failed to read stdin: {e}")));
        return buf;
    }
    std::fs::read_to_string(path)
        .unwrap_or_else(|e| platform::die(&format!("failed to read {}: {e}", path.display())))
}

/// Open `initial` in $EDITOR (falling back to vi) and return the edited contents.
fn edit_in_editor(initial: &str) -> String {
    let editor = std::env::var("EDITOR")
        .or_else(|_| std::env::var("VISUAL"))
        .unwrap_or_else(|_| "vi".to_string());
    let mut tmp = std::env::temp_dir();
    tmp.push(format!("vesta-constitution-{}.md", process::id()));
    std::fs::write(&tmp, initial)
        .unwrap_or_else(|e| platform::die(&format!("failed to write temp file: {e}")));
    let status = process::Command::new(&editor)
        .arg(&tmp)
        .status()
        .unwrap_or_else(|e| platform::die(&format!("failed to launch editor '{editor}': {e}")));
    if !status.success() {
        std::fs::remove_file(&tmp).ok();
        platform::die("editor exited with an error, aborting");
    }
    let edited = std::fs::read_to_string(&tmp)
        .unwrap_or_else(|e| platform::die(&format!("failed to read temp file: {e}")));
    std::fs::remove_file(&tmp).ok();
    edited
}

fn prompt_raw(label: &str) -> String {
    eprint!("{label}: ");
    io::stderr().flush().ok();
    let mut input = String::new();
    io::stdin()
        .read_line(&mut input)
        .unwrap_or_else(|_| platform::die(&format!("failed to read {label}")));
    input.trim().to_string()
}

fn prompt(label: &str) -> String {
    let value = prompt_raw(label);
    if value.is_empty() {
        platform::die(&format!("{label} is required"));
    }
    value
}

fn prompt_name() -> String {
    prompt("agent name")
}

fn build_openrouter_args(flags: OpenRouterFlags) -> Option<client::OpenRouterArgs> {
    let key = flags.openrouter_key?;
    let model = flags.openrouter_model.unwrap_or_else(|| platform::die("--openrouter-model is required with --openrouter-key"));
    Some(client::OpenRouterArgs { key, model })
}

/// Claude model + context window chosen for a `vesta setup`. Both optional: unset
/// fields let vestad apply its defaults (Opus, 1M window).
#[derive(Default)]
struct ClaudeOptions {
    model: Option<String>,
    max_context_tokens: Option<u64>,
}

/// How `vesta setup` will provision the agent once it's created.
enum ProvisionPlan {
    /// Run on OpenRouter (key already validated).
    OpenRouter(client::OpenRouterArgs),
    /// Provision Claude from credentials supplied up front (non-interactive).
    ClaudeCredentials { credentials: String, opts: ClaudeOptions },
    /// Provision Claude via the interactive OAuth dance after create.
    ClaudeOAuth { opts: ClaudeOptions },
}

/// Resolve how `vesta setup` should provision the agent. Every interactive prompt
/// has a non-interactive flag equivalent:
/// - `--openrouter-key` (+ `--openrouter-model`) -> OpenRouter, no prompts
/// - `--claude-token` -> Claude from supplied credentials, no prompts
/// - `--yes` with neither -> defaults to Claude (OAuth dance still runs)
/// - otherwise -> prompt for the provider (and key/model, or OAuth)
#[allow(clippy::too_many_arguments)]
fn resolve_setup_provider(c: &client::Client, flags: OpenRouterFlags, claude_token: Option<String>, claude_model: Option<String>, context_window: Option<u64>, yes: bool) -> ProvisionPlan {
    if flags.openrouter_key.is_some() && claude_token.is_some() {
        platform::die("--openrouter-key and --claude-token are mutually exclusive");
    }
    if flags.openrouter_key.is_some() {
        let args = build_openrouter_args(flags).unwrap_or_else(|| platform::die("internal: openrouter key vanished"));
        eprintln!("checking OpenRouter key...");
        c.validate_openrouter_key(&args.key).unwrap_or_else(|e| platform::die(&e));
        return ProvisionPlan::OpenRouter(args);
    }
    if let Some(credentials) = claude_token {
        // Non-interactive Claude: model/context come from flags only (no prompts).
        return ProvisionPlan::ClaudeCredentials {
            credentials,
            opts: ClaudeOptions { model: claude_model, max_context_tokens: context_window },
        };
    }
    if yes || !prompt_use_openrouter() {
        return ProvisionPlan::ClaudeOAuth { opts: resolve_claude_options(c, claude_model, context_window, yes) };
    }
    ProvisionPlan::OpenRouter(prompt_openrouter_interactive(c, flags.openrouter_model))
}

/// Collect the Claude model + context window for setup. Flags win; otherwise prompt
/// interactively. With `--yes` and no flags, leave both unset so vestad applies its
/// defaults (Opus, 1M window).
fn resolve_claude_options(c: &client::Client, model_flag: Option<String>, ctx_flag: Option<u64>, yes: bool) -> ClaudeOptions {
    let model = model_flag.or_else(|| (!yes).then(|| prompt_claude_model(c)));
    let max_context_tokens = ctx_flag.or_else(|| if yes { None } else { prompt_context_window(c) });
    ClaudeOptions { model, max_context_tokens }
}

/// Show a numbered list and return the chosen 0-based index. Empty input picks
/// `default_idx`; an out-of-range number reprompts. Used by the fixed-list pickers
/// (Claude model, context window); the OpenRouter picker is richer (search + custom
/// slug) and stays separate.
fn prompt_indexed_choice(labels: &[String], default_idx: usize) -> usize {
    for (idx, label) in labels.iter().enumerate() {
        let marker = if idx == default_idx { "  (default)" } else { "" };
        eprintln!("  {}) {label}{marker}", idx + 1);
    }
    loop {
        match prompt_raw(&format!("choice [{}]", default_idx + 1)).as_str() {
            "" => return default_idx,
            s => match s.parse::<usize>().ok().filter(|n| (1..=labels.len()).contains(n)) {
                Some(n) => return n - 1,
                None => eprintln!("  pick a number between 1 and {}", labels.len()),
            },
        }
    }
}

/// Prompt for a Claude model from the curated list (default = first entry, Opus).
/// Falls back to "opus" if the list can't be fetched.
fn prompt_claude_model(c: &client::Client) -> String {
    let models = match c.fetch_manifest() {
        Ok(manifest) => match manifest.providers.get("claude").map(|p| &p.models) {
            Some(client::ModelCatalog::Static(slugs)) if !slugs.is_empty() => slugs.clone(),
            _ => return "opus".to_string(),
        },
        Err(_) => return "opus".to_string(),
    };
    eprintln!("which Claude model?");
    models[prompt_indexed_choice(&models, 0)].clone()
}

/// Prompt for a context-window preset. The presets and the default come from the manifest
/// (GET /manifest), so the CLI keeps no copy. Returns None if they can't be fetched, letting
/// the server apply its own default.
fn prompt_context_window(c: &client::Client) -> Option<u64> {
    let manifest = c.fetch_manifest().ok()?;
    let context = &manifest.providers.get("claude")?.context;
    if context.presets.is_empty() {
        return None;
    }
    eprintln!("context window?");
    let labels: Vec<String> = context.presets.iter().map(|p| format!("{} — {}", p.label, p.note)).collect();
    let default_idx = context.presets.iter().position(|p| p.tokens == context.default).unwrap_or(0);
    Some(context.presets[prompt_indexed_choice(&labels, default_idx)].tokens)
}

/// Ask the user which provider to run the agent on. Defaults to a Claude
/// account (empty input or "1"). Returns true if the user picked OpenRouter.
fn prompt_use_openrouter() -> bool {
    eprintln!("how should this agent authenticate?");
    eprintln!("  1) Claude account  — log in with your Claude subscription (default)");
    eprintln!("  2) OpenRouter      — run on an OpenRouter API key");
    loop {
        match prompt_raw("choice [1]").as_str() {
            "" | "1" => return false,
            "2" => return true,
            _ => eprintln!("  please enter 1 or 2"),
        }
    }
}

/// Interactively collect an OpenRouter key (validated, with retry) and a model
/// slug. A model passed via `--openrouter-model` is reused without prompting.
fn prompt_openrouter_interactive(c: &client::Client, preset_model: Option<String>) -> client::OpenRouterArgs {
    let key = loop {
        let key = prompt("OpenRouter API key (from openrouter.ai/keys)");
        eprintln!("checking key...");
        match c.validate_openrouter_key(&key) {
            Ok(()) => break key,
            Err(e) => eprintln!("  {e}. try again."),
        }
    };
    let model = preset_model.unwrap_or_else(|| prompt_openrouter_model(c));
    client::OpenRouterArgs { key, model }
}

/// Format a model's input/output/cache-read price (USD per million tokens) for the
/// picker list, or None when OpenRouter doesn't report pricing. Cache read is shown
/// only when present and non-zero.
fn fmt_model_price(input: Option<f64>, output: Option<f64>, cache_read: Option<f64>) -> Option<String> {
    let (input, output) = (input?, output?);
    if input == 0.0 && output == 0.0 && cache_read.unwrap_or(0.0) == 0.0 {
        return Some("free".to_string());
    }
    let mut price = format!("{} in / {} out", fmt_usd(input), fmt_usd(output));
    if let Some(cache) = cache_read.filter(|c| *c > 0.0) {
        price.push_str(&format!(" / {} cache read", fmt_usd(cache)));
    }
    price.push_str(" per Mtok");
    Some(price)
}

/// `$15`, `$1.25`, `$0.10`, `$0.0028` — two decimals in the cents range, trailing
/// zeros trimmed at/above a dollar, and widened precision below a cent so tiny
/// cache-read prices don't round away to `$0.00`.
fn fmt_usd(price: f64) -> String {
    if price == 0.0 {
        "$0".to_string()
    } else if price >= 1.0 {
        format!("${price:.2}").trim_end_matches('0').trim_end_matches('.').to_string()
    } else if price >= 0.01 {
        format!("${price:.2}")
    } else {
        format!("${price:.4}").trim_end_matches('0').trim_end_matches('.').to_string()
    }
}

/// Prompt for an OpenRouter model. Shows the top-weekly models as a numbered
/// list (pick by number) and always accepts a custom `provider/model` slug.
/// Falls back to a free-text prompt if the model list can't be fetched.
fn prompt_openrouter_model(c: &client::Client) -> String {
    let models = match c.fetch_top_openrouter_models() {
        Ok(models) if !models.is_empty() => models,
        _ => return prompt("model slug (e.g. anthropic/claude-sonnet-4-6)"),
    };
    eprintln!("top models on OpenRouter this week:");
    for (idx, model) in models.iter().enumerate() {
        match fmt_model_price(model.input_price, model.output_price, model.cache_read_price) {
            Some(price) => eprintln!("  {:>2}) {} ({}) — {}  [{}]", idx + 1, model.label, model.author, model.slug, price),
            None => eprintln!("  {:>2}) {} ({}) — {}", idx + 1, model.label, model.author, model.slug),
        }
    }
    eprintln!("  or type a custom provider/model slug");
    loop {
        let input = prompt("model (number or slug)");
        if let Ok(choice) = input.parse::<usize>() {
            match models.get(choice.wrapping_sub(1)) {
                Some(model) => return model.slug.clone(),
                None => {
                    eprintln!("  pick a number between 1 and {}", models.len());
                    continue;
                }
            }
        }
        return input;
    }
}

// Agent-less OAuth dance: prints the auth URL, prompts for the pasted code,
// returns the credentials JSON. Caller passes it to update_settings.
fn oauth_dance(client: &client::Client) -> String {
    let auth = client
        .start_auth_standalone()
        .unwrap_or_else(|e| platform::die(&e));
    eprintln!("open this URL to authenticate:");
    eprintln!("  {}", auth.auth_url);
    try_open_browser(&auth.auth_url);

    let code = prompt("paste the auth code");
    client
        .complete_auth_standalone(&auth.session_id, &code)
        .unwrap_or_else(|e| platform::die(&e))
}

fn authenticate_agent(client: &client::Client, name: &str) {
    let credentials = oauth_dance(client);
    // Reauth only: model, context window, and timezone are preserved server-side (None = keep).
    client
        .update_settings(name, Some(client::claude_auth(&credentials)), None, None, None)
        .unwrap_or_else(|e| platform::die(&e));
    eprintln!("authenticated!");
}

fn get_client(host: Option<&str>, token: Option<&str>) -> client::Client {
    let config = platform::load_server_config(host, token)
        .unwrap_or_else(|| platform::die("no server configured. run: vesta connect <host>"));
    let client = client::Client::new(&config).unwrap_or_else(|e| platform::die(&e));
    enforce_version_match(&client);
    client
}

/// Which side is out of date when the CLI and gateway versions differ.
#[derive(Debug, PartialEq)]
enum VersionGate {
    Match,
    /// The CLI is older — it should self-update to the gateway's version.
    CliOlder,
    /// The gateway is older — it should self-update via POST /gateway/update.
    GatewayOlder,
}

fn classify_version_gate(cli: &str, gateway: &str) -> VersionGate {
    if cli == gateway {
        VersionGate::Match
    } else if version_less_than(cli, gateway) {
        VersionGate::CliOlder
    } else {
        VersionGate::GatewayOlder
    }
}

/// Refuse to drive a vestad whose version differs from this CLI, mirroring the
/// app's version-mismatch gate. The CLI is a client just like the app, so it
/// offers the matching fix: self-update the CLI to the gateway's version when the
/// CLI is older, or update the gateway when the gateway is older. A definitive
/// mismatch exits non-zero; an unreachable or pre-version gateway is left alone so
/// the command can surface its own error.
fn enforce_version_match(client: &client::Client) {
    let gateway = match client.gateway_version() {
        Ok(version) => version,
        Err(_) => return,
    };
    let cli = env!("CARGO_PKG_VERSION");
    match classify_version_gate(cli, &gateway) {
        VersionGate::Match => return,
        VersionGate::CliOlder => {
            eprintln!("version mismatch: vesta CLI v{cli} is older than gateway v{gateway}");
            if confirm("update the CLI now?") {
                run_cli_self_update(Some(&gateway));
                eprintln!("re-run your command now.");
            } else {
                eprintln!("run 'vesta update' to update the CLI, then retry.");
            }
        }
        VersionGate::GatewayOlder => {
            eprintln!("version mismatch: gateway v{gateway} is older than vesta CLI v{cli}");
            if confirm("update the gateway now?") {
                client.update_gateway().unwrap_or_else(|e| platform::die(&format!("gateway update failed: {e}")));
                eprintln!("gateway update started; wait for it to restart, then re-run your command.");
            } else {
                eprintln!("update the gateway, then retry.");
            }
        }
    }
    process::exit(1);
}

/// Prompt for a yes/no confirmation, defaulting to no on empty input or a
/// non-interactive stdin (so scripts get a clean non-zero exit, not a hang).
fn confirm(question: &str) -> bool {
    eprint!("{question} [y/N] ");
    io::stderr().flush().ok();
    let mut answer = String::new();
    if io::stdin().read_line(&mut answer).is_err() {
        return false;
    }
    answer.trim().eq_ignore_ascii_case("y")
}

// Ask the configured vestad for the latest release tag so the CLI does not hit
// the GitHub API directly. vestad keeps a cached, ETag-conditional view of the
// latest release. Returns None when no server is configured or the request
// fails, letting callers fall back to a direct GitHub check.
fn fetch_latest_via_gateway(force: bool) -> Option<String> {
    let config = common::load_server_config()?;
    let client = client::Client::new(&config).ok()?;
    let result = if force {
        client.check_latest_release_tag()
    } else {
        client.latest_release_tag()
    };
    result.ok().flatten()
}

fn check_latest_version() -> Option<String> {
    let current = env!("CARGO_PKG_VERSION");
    eprintln!("current version: v{current}");

    let latest = fetch_latest_via_gateway(true)
        .or_else(|| fetch_latest_release_tag(None))
        .unwrap_or_else(|| platform::die("failed to check for updates"));

    if latest == current {
        eprintln!("already up to date");
        return None;
    }
    eprintln!("updating to v{latest}...");
    Some(latest)
}

// Download and self-replace the CLI binary. `target_version` pins a specific
// version (the gateway's, when resolving a mismatch — like the app's "update your
// app" which targets the gateway's exact version); `None` resolves the latest
// release for the explicit `vesta update`.
fn cli_self_update(target_version: Option<&str>, rust_target: &str, is_zip: bool, binary_subpath: &str) -> Option<PathBuf> {
    let latest = match target_version {
        Some(version) => {
            eprintln!("current version: v{}", env!("CARGO_PKG_VERSION"));
            if version == env!("CARGO_PKG_VERSION") {
                eprintln!("already up to date");
                return None;
            }
            eprintln!("updating to v{version}...");
            version.to_string()
        }
        None => check_latest_version()?,
    };

    let ext = if is_zip { "zip" } else { "tar.gz" };
    let archive_name = format!("vesta-{rust_target}.{ext}");
    let url = format!(
        "https://github.com/elyxlz/vesta/releases/download/v{latest}/{archive_name}"
    );

    let current_exe =
        std::env::current_exe().unwrap_or_else(|e| platform::die(&format!("cannot determine binary path: {e}")));
    let exe_dir = current_exe
        .parent()
        .unwrap_or_else(|| platform::die("cannot determine binary directory"));

    let tmp_dir = {
        let primary = exe_dir.join(".vesta-update-tmp");
        let _ = std::fs::remove_dir_all(&primary);
        if std::fs::create_dir_all(&primary).is_ok() {
            primary
        } else {
            let fallback = std::env::temp_dir().join("vesta-update");
            let _ = std::fs::remove_dir_all(&fallback);
            std::fs::create_dir_all(&fallback)
                .unwrap_or_else(|e| platform::die(&format!("failed to create temp dir: {e}")));
            fallback
        }
    };

    let archive = tmp_dir.join(&archive_name);
    let dl = process::Command::new("curl")
        .args(["-fsSL", "-o"])
        .arg(&archive)
        .arg(&url)
        .status()
        .unwrap_or_else(|_| platform::die("curl not found"));
    if !dl.success() {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        platform::die("failed to download update");
    }

    let tar_flag = if is_zip { "-xf" } else { "-xzf" };
    let extract = process::Command::new("tar")
        .arg(tar_flag)
        .arg(&archive)
        .arg("-C")
        .arg(&tmp_dir)
        .status()
        .unwrap_or_else(|_| platform::die("tar not found"));
    if !extract.success() {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        platform::die("failed to extract update");
    }

    let new_binary = tmp_dir.join(binary_subpath);
    self_replace::self_replace(&new_binary).unwrap_or_else(|e| {
        let _ = std::fs::remove_dir_all(&tmp_dir);
        platform::die(&format!("failed to replace binary: {e}"));
    });

    eprintln!("updated to v{latest}");
    Some(tmp_dir)
}

// The release artifact for this platform: (rust target triple, is_zip, binary
// path inside the archive). The arch→triple match dies on an unsupported CPU.
fn update_target() -> (&'static str, bool, &'static str) {
    #[cfg(target_os = "linux")]
    {
        let target = match std::env::consts::ARCH {
            "x86_64" => "x86_64-unknown-linux-gnu",
            "aarch64" => "aarch64-unknown-linux-gnu",
            other => platform::die(&format!("unsupported architecture: {other}")),
        };
        (target, false, "vesta")
    }
    #[cfg(target_os = "macos")]
    {
        let target = match std::env::consts::ARCH {
            "x86_64" => "x86_64-apple-darwin",
            "aarch64" => "aarch64-apple-darwin",
            other => platform::die(&format!("unsupported architecture: {other}")),
        };
        (target, false, "vesta")
    }
    #[cfg(target_os = "windows")]
    {
        ("x86_64-pc-windows-msvc", true, "vesta-windows/vesta.exe")
    }
}

// Resolve the platform target/archive and run the self-update. `target_version`
// pins a specific version (the gateway's) or is `None` for the latest release.
fn run_cli_self_update(target_version: Option<&str>) {
    let (target, is_zip, binary_subpath) = update_target();
    if let Some(tmp_dir) = cli_self_update(target_version, target, is_zip, binary_subpath) {
        let _ = std::fs::remove_dir_all(&tmp_dir);
    }
}

fn check_update_cached() -> Option<std::thread::JoinHandle<Option<String>>> {
    let cache_dir = dirs::cache_dir().unwrap_or_else(std::env::temp_dir);
    let cache_file = cache_dir.join("vesta-version-check");

    if let Ok(contents) = std::fs::read_to_string(&cache_file) {
        if let Ok(meta) = std::fs::metadata(&cache_file) {
            if let Ok(modified) = meta.modified() {
                if modified.elapsed().unwrap_or_default() < std::time::Duration::from_secs(VERSION_CACHE_TTL_SECS) {
                    let latest = contents.trim();
                    if !latest.is_empty() && latest != env!("CARGO_PKG_VERSION") {
                        if version_less_than(latest, env!("CARGO_PKG_VERSION")) {
                            let _ = std::fs::remove_file(&cache_file);
                        } else {
                            print_update_available(latest);
                        }
                    }
                    return None;
                }
            }
        }
    }

    Some(std::thread::spawn(move || {
        let latest = fetch_latest_via_gateway(false).or_else(|| fetch_latest_release_tag(Some(5)))?;
        let _ = std::fs::create_dir_all(&cache_dir);
        let _ = std::fs::write(&cache_file, &latest);
        if version_less_than(env!("CARGO_PKG_VERSION"), &latest) {
            Some(latest)
        } else {
            None
        }
    }))
}

fn detect_timezone() -> Option<String> {
    if let Ok(tz) = std::env::var("TZ") {
        if !tz.is_empty() {
            return Some(tz);
        }
    }
    if let Ok(content) = std::fs::read_to_string("/etc/timezone") {
        let tz = content.trim().to_string();
        if !tz.is_empty() {
            return Some(tz);
        }
    }
    if let Ok(link) = std::fs::read_link("/etc/localtime") {
        let path = link.to_string_lossy();
        if let Some(tz) = path.strip_prefix("/usr/share/zoneinfo/") {
            return Some(tz.to_string());
        }
    }
    None
}

fn print_update_available(latest: &str) {
    eprintln!("\nUpdate available: v{} → v{} (run 'vesta update')", env!("CARGO_PKG_VERSION"), latest);
}

fn print_welcome() {
    println!("vesta — your personal AI assistant");
    println!();
    println!("quick start:");
    println!("  vesta setup        create an agent, authenticate, and start");
    println!("  vesta list         list all agents");
    println!();
    println!("run 'vesta --help' for all commands.");
}

fn run(cli: Cli) {
    let Some(command) = cli.command else {
        print_welcome();
        return;
    };

    let bg_handle = if matches!(command, Command::Update) { None } else { check_update_cached() };

    let host_ref = cli.host.as_deref();
    let token_ref = cli.token.as_deref();

    match command {
        Command::Setup { yes, name, no_manage_core_code, claude_token, claude_model, context_window, openrouter } => {
            let c = get_client(host_ref, token_ref);

            let name = name
                .map(|name| name.trim().to_string())
                .unwrap_or_else(prompt_name);

            // Choose the provider before creating anything: with no flags this
            // prompts interactively (Claude vs OpenRouter). The OpenRouter key
            // is validated client-side here so a bad key fails fast, before we
            // create an agent we'd immediately fail to provision. Claude needs
            // no pre-validation; OAuth happens after create.
            let plan = resolve_setup_provider(&c, openrouter, claude_token, claude_model, context_window, yes);
            let timezone = detect_timezone();

            // 1. Create an empty agent. Vestad no longer accepts credentials or timezone at
            //    create time — the agent owns its own auth state and config store. Timezone rides
            //    the provider provisioning call below.
            let created_name = match c.create_agent(&name, !no_manage_core_code) {
                Ok(n) => { eprintln!("created agent '{n}'"); n }
                Err(e) if e.contains("already exists") && yes => {
                    eprintln!("agent '{name}' already exists, continuing...");
                    name.clone()
                }
                Err(e) if e.contains("already exists") => {
                    platform::die(&format!("agent '{name}' already exists. use --yes to continue"));
                }
                Err(e) => platform::die(&e),
            };

            // 2. Wait for the agent's HTTP server to be up so it can receive PUT /config.
            eprintln!("waiting for agent to start...");
            c.wait_until_running(&created_name, START_READY_TIMEOUT)
                .unwrap_or_else(|e| platform::die(&e));

            // 3. Provision the provider. OpenRouter and supplied Claude credentials
            //    are a single API call; an interactive Claude setup runs the OAuth
            //    dance first.
            match plan {
                ProvisionPlan::OpenRouter(or) => {
                    c.update_settings(&created_name, Some(client::openrouter_auth(&or)), None, None, timezone.as_deref())
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("running on OpenRouter (no Claude login needed)");
                }
                ProvisionPlan::ClaudeCredentials { credentials, opts } => {
                    c.update_settings(&created_name, Some(client::claude_auth(&credentials)), opts.model.as_deref(), opts.max_context_tokens, timezone.as_deref())
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("authenticated (claude)");
                }
                ProvisionPlan::ClaudeOAuth { opts } => {
                    eprintln!("authenticating claude...");
                    let credentials = oauth_dance(&c);
                    c.update_settings(&created_name, Some(client::claude_auth(&credentials)), opts.model.as_deref(), opts.max_context_tokens, timezone.as_deref())
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("authenticated!");
                }
            }

            // 4. Wait for the agent to come fully alive after the provision-triggered
            //    restart. "alive" now means first-start setup actually completed — a
            //    bad provider (e.g. an OpenRouter key with no credits) flips the agent
            //    to not_authenticated here instead of falsely reporting ready. The
            //    agent passes through `setting_up` while it runs its first-start tasks.
            c.wait_until_alive_with_progress(&created_name, START_READY_TIMEOUT, |status| match status {
                "setting_up" => eprintln!("agent is setting itself up (first-start tasks)... this can take several minutes"),
                "starting" => eprintln!("waiting for the agent to boot..."),
                _ => {}
            })
            .unwrap_or_else(|e| platform::die(&format!(
                "{e}\nfirst-start setup did not complete. check the agent's logs: vesta logs {created_name}"
            )));
            eprintln!("agent '{created_name}' is ready.");

        }

        Command::Create { name, no_manage_core_code, openrouter } => {
            let c = get_client(host_ref, token_ref);
            let name = name
                .map(|name| name.trim().to_string())
                .unwrap_or_else(prompt_name);
            let openrouter = build_openrouter_args(openrouter);
            let timezone = detect_timezone();

            if let Some(or) = &openrouter {
                eprintln!("checking OpenRouter key...");
                c.validate_openrouter_key(&or.key)
                    .unwrap_or_else(|e| platform::die(&e));
            }

            let name = c.create_agent(&name, !no_manage_core_code)
                .unwrap_or_else(|e| platform::die(&e));

            // If --openrouter-key was provided, finish provisioning the agent immediately, carrying
            // the timezone in the same call. Otherwise leave it unprovisioned for `vesta auth` later;
            // the agent boots on UTC and asks for the timezone at first wake.
            if let Some(or) = &openrouter {
                eprintln!("waiting for agent to start...");
                c.wait_until_running(&name, START_READY_TIMEOUT)
                    .unwrap_or_else(|e| platform::die(&e));
                c.update_settings(&name, Some(client::openrouter_auth(or)), None, None, timezone.as_deref())
                    .unwrap_or_else(|e| platform::die(&e));
                eprintln!("created (running on OpenRouter)");
            } else {
                eprintln!("created (run 'vesta auth {name}' to authenticate)");
            }
        }

        Command::Settings { name, model, context_window } => {
            let c = get_client(host_ref, token_ref);
            if model.is_some() || context_window.is_some() {
                c.update_settings(&name, None, model.as_deref(), context_window, None)
                    .unwrap_or_else(|e| platform::die(&e));
                eprintln!("updated. the agent is restarting to apply the change.");
            } else {
                let result = c.get_agent_settings(&name).unwrap_or_else(|e| platform::die(&e));
                eprintln!("manage_agent_code = {}", result["manage_agent_code"].as_bool().unwrap_or(true));
                // Only report model/context when a provider is actually configured; a signed-out
                // agent (kind "none") has a stored default model but no active provider.
                if let Ok(provider) = c.get_provider(&name) {
                    if provider["authed"].as_bool() != Some(true) {
                        eprintln!("provider = not configured (run 'vesta auth {name}')");
                    } else {
                        if let Some(m) = provider["model"].as_str() {
                            eprintln!("model = {m}");
                        }
                        match provider["max_context_tokens"].as_u64() {
                            Some(ctx) => eprintln!("context_window = {ctx}"),
                            None if provider["kind"].as_str() == Some("openrouter") => {
                                eprintln!("context_window = default (model window, capped at 200K)")
                            }
                            None if provider["kind"].as_str() == Some("claude") => {
                                eprintln!("context_window = default (1M for Claude)")
                            }
                            None => eprintln!("context_window = default"),
                        }
                    }
                }
            }
        }

        Command::Constitution { name, edit, file, clear } => {
            let c = get_client(host_ref, token_ref);
            let new_content: Option<String> = if clear {
                Some(String::new())
            } else if let Some(path) = file {
                Some(read_file_or_stdin(&path))
            } else if edit {
                let current = c.get_agent_constitution(&name).unwrap_or_else(|e| platform::die(&e));
                Some(edit_in_editor(&current))
            } else {
                None
            };

            match new_content {
                None => {
                    let content = c.get_agent_constitution(&name).unwrap_or_else(|e| platform::die(&e));
                    print!("{content}");
                    if !content.ends_with('\n') {
                        println!();
                    }
                }
                Some(content) => {
                    c.set_agent_constitution(&name, &content).unwrap_or_else(|e| platform::die(&e));
                    // Restart so the new constitution is loaded into the system prompt.
                    c.restart_agent(&name).unwrap_or_else(|e| platform::die(&e));
                    eprintln!("{name}: constitution updated, agent restarting");
                }
            }
        }

        Command::Start { name } => {
            let c = get_client(host_ref, token_ref);
            match name {
                Some(name) => {
                    c.start_agent(&name).unwrap_or_else(|e| platform::die(&e));
                    c.wait_until_alive(&name, START_READY_TIMEOUT)
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("{name}: ready");
                }
                None => {
                    let results = c.start_all().unwrap_or_else(|e| platform::die(&e));
                    if results.is_empty() {
                        eprintln!("no agents found. create one with: vesta setup");
                    } else {
                        for r in &results {
                            if !r.ok {
                                eprintln!(
                                    "{}: {}",
                                    r.name,
                                    r.error.as_deref().unwrap_or("failed")
                                );
                                continue;
                            }
                            match c.wait_until_alive(&r.name, START_READY_TIMEOUT) {
                                Ok(()) => eprintln!("{}: ready", r.name),
                                Err(e) => eprintln!("{}: {}", r.name, e),
                            }
                        }
                    }
                }
            }
        }

        Command::Stop { name } => {
            let c = get_client(host_ref, token_ref);
            c.stop_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{name}: stopped");
        }

        Command::Restart { name } => {
            let c = get_client(host_ref, token_ref);
            c.restart_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{name}: restarted");
        }

        Command::Logout { name } => {
            let c = get_client(host_ref, token_ref);
            c.logout(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{name}: signed out (reconnect a provider with `vesta auth {name}`)");
        }

        Command::Gateway { action } => match action {
            GatewayAction::Restart => {
                let c = get_client(host_ref, token_ref);
                c.restart_gateway().unwrap_or_else(|e| platform::die(&e));
                eprintln!("vestad: restart initiated");
            }
            GatewayAction::Logs { tail, follow } => {
                let c = get_client(host_ref, token_ref);
                c.stream_gateway_logs(tail, follow).unwrap_or_else(|e| platform::die(&e));
            }
        },

        Command::Auth { name, token } => {
            let c = get_client(host_ref, token_ref);
            if let Some(token_str) = token {
                c.update_settings(&name, Some(client::claude_auth(&token_str)), None, None, None)
                    .unwrap_or_else(|e| platform::die(&e));
                eprintln!("{name}: authenticated");
            } else {
                authenticate_agent(&c, &name);
            }
        }

        Command::Chat { name } => {
            let c = get_client(host_ref, token_ref);
            client::chat(&c, &name).unwrap_or_else(|e| platform::die(&e));
        }

        Command::Logs { name, tail } => {
            let c = get_client(host_ref, token_ref);
            c.stream_logs(&name, tail).unwrap_or_else(|e| platform::die(&e));
        }

        Command::Status { name, json } => {
            let c = get_client(host_ref, token_ref);
            let status = c.agent_status(&name).unwrap_or_else(|e| {
                if json && e.contains("not found") {
                    println!(
                        "{}",
                        serde_json::json!({
                            "name": name,
                            "status": "not_found",
                            "ws_port": 0
                        })
                    );
                    process::exit(0);
                }
                platform::die(&e);
            });
            if json {
                println!("{}", serde_json::to_string(&status).unwrap_or_else(|e| platform::die(&format!("failed to serialize: {e}"))));
            } else {
                println!("name:   {}", status.name);
                println!("status: {}", status.status);
                if let Some(id) = &status.id {
                    println!("id:     {id}");
                }
                println!("port:   {}", status.ws_port);
            }
        }

        Command::List { json } => {
            let c = get_client(host_ref, token_ref);
            let agents = c.list_agents().unwrap_or_else(|e| platform::die(&e));
            if json {
                println!("{}", serde_json::to_string(&agents).unwrap_or_else(|e| platform::die(&format!("failed to serialize: {e}"))));
            } else if agents.is_empty() {
                println!("no agents. run: vesta setup");
            } else {
                for e in &agents {
                    println!(
                        "  {} — {}  (port {})",
                        e.name, e.status, e.ws_port
                    );
                }
            }
        }

        Command::Backup { action } => {
            let c = get_client(host_ref, token_ref);
            match action {
                BackupAction::Create { name } => {
                    eprintln!("creating backup for '{name}'...");
                    let backup = c.create_backup(&name).unwrap_or_else(|e| platform::die(&e));
                    eprintln!("backup created: {} ({})", backup.id, format_size(backup.size));
                }
                BackupAction::List { name } => {
                    let backups = c.list_backups(&name).unwrap_or_else(|e| platform::die(&e));
                    if backups.is_empty() {
                        eprintln!("no backups for '{name}'");
                    } else {
                        eprintln!("  {:<22} {:<13} {:>8}   ID", "DATE", "TYPE", "SIZE");
                        for b in &backups {
                            println!(
                                "  {:<22} {:<13} {:>8}   {}",
                                b.created_at, b.backup_type, format_size(b.size), b.id
                            );
                        }
                    }
                }
                BackupAction::ListAll => {
                    let backups = c.list_all_backups().unwrap_or_else(|e| platform::die(&e));
                    if backups.is_empty() {
                        eprintln!("no backups found");
                    } else {
                        eprintln!("  {:<16} {:<22} {:<13} {:>8}   ID", "AGENT", "DATE", "TYPE", "SIZE");
                        for b in &backups {
                            println!(
                                "  {:<16} {:<22} {:<13} {:>8}   {}",
                                b.agent_name, b.created_at, b.backup_type, format_size(b.size), b.id
                            );
                        }
                    }
                }
                BackupAction::Restore { name, backup_id } => {
                    eprintln!("restoring '{name}' from backup...");
                    c.restore_backup(&name, &backup_id)
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("{name}: restored from {backup_id}");
                }
                BackupAction::Delete { name, backup_id } => {
                    c.delete_backup(&name, &backup_id)
                        .unwrap_or_else(|e| platform::die(&e));
                    eprintln!("backup deleted: {backup_id}");
                }
                BackupAction::AutoBackup { toggle } => match toggle {
                    Some(toggle) => {
                        let enabled = matches!(toggle, Toggle::On);
                        c.set_auto_backup_settings(&serde_json::json!({"enabled": enabled}))
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("auto-backup: {}", if enabled { "enabled" } else { "disabled" });
                    }
                    None => {
                        let settings = c.get_auto_backup_settings().unwrap_or_else(|e| platform::die(&e));
                        let enabled = settings["enabled"].as_bool().unwrap_or(true);
                        eprintln!("auto-backup: {}", if enabled { "enabled" } else { "disabled" });
                    }
                },
                BackupAction::Retention { daily, weekly, monthly } => {
                    if daily.is_none() && weekly.is_none() && monthly.is_none() {
                        let settings = c.get_auto_backup_settings().unwrap_or_else(|e| platform::die(&e));
                        print_retention(&settings["retention"]);
                    } else {
                        let ret = retention_map(daily, weekly, monthly);
                        let settings = c.set_auto_backup_settings(&serde_json::json!({"retention": ret}))
                            .unwrap_or_else(|e| platform::die(&e));
                        print_retention(&settings["retention"]);
                    }
                },
                BackupAction::Settings { name, enabled, daily, weekly, monthly, reset } => {
                    if reset {
                        let result = c.delete_agent_backup_settings(&name)
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("{name}: backup settings reset to global defaults");
                        print_agent_backup_settings(&result);
                    } else if enabled.is_none() && daily.is_none() && weekly.is_none() && monthly.is_none() {
                        let result = c.get_agent_backup_settings(&name)
                            .unwrap_or_else(|e| platform::die(&e));
                        print_agent_backup_settings(&result);
                    } else {
                        let mut body = serde_json::Map::new();
                        if let Some(toggle) = enabled {
                            body.insert("enabled".into(), matches!(toggle, Toggle::On).into());
                        }
                        if daily.is_some() || weekly.is_some() || monthly.is_some() {
                            body.insert("retention".into(), retention_map(daily, weekly, monthly).into());
                        }
                        let result = c.set_agent_backup_settings(&name, &serde_json::Value::Object(body))
                            .unwrap_or_else(|e| platform::die(&e));
                        eprintln!("{name}: backup settings updated");
                        print_agent_backup_settings(&result);
                    }
                },
            }
        }

        Command::Destroy { name } => {
            let c = get_client(host_ref, token_ref);
            c.destroy_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{name}: destroyed");
        }

        Command::Rebuild { name } => {
            let c = get_client(host_ref, token_ref);
            c.rebuild_agent(&name).unwrap_or_else(|e| platform::die(&e));
            eprintln!("{name}: rebuilt and running");
        }

        Command::WaitReady { name, timeout } => {
            let c = get_client(host_ref, token_ref);
            c.wait_until_alive(&name, std::time::Duration::from_secs(timeout))
                .unwrap_or_else(|e| platform::die(&e));
            eprintln!("{name}: ready");
        }

        Command::Connect { link } => {
            let (url, key) = common::parse_connect_link(&link)
                .unwrap_or_else(|| platform::die("paste the connect link vestad printed"));

            let url = common::normalize_url(&url);
            if key.is_empty() {
                platform::die("API key is required");
            }

            let config = platform::ServerConfig {
                url: url.clone(),
                api_key: key,
                cert_fingerprint: None,
                cert_pem: None,
            };

            let client = client::Client::new(&config).unwrap_or_else(|e| platform::die(&e));
            client
                .health()
                .unwrap_or_else(|e| platform::die(&format!("cannot reach server: {e}")));

            platform::save_server_config(&config)
                .unwrap_or_else(|e| platform::die(&e));
            eprintln!("connected to {url}");
        }

        Command::Uninstall => {
            eprint!("This will remove the vesta CLI binary and its config. Continue? [y/N] ");
            io::stderr().flush().ok();
            let mut answer = String::new();
            if io::stdin().read_line(&mut answer).is_err() {
                eprintln!("failed to read input");
                process::exit(1);
            }
            if !answer.trim().eq_ignore_ascii_case("y") {
                eprintln!("Aborted.");
                process::exit(0);
            }

            match std::fs::remove_dir_all(common::config_dir()) {
                Ok(()) => eprintln!("  removed {}", common::config_dir().display()),
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
                Err(err) => eprintln!("warning: failed to remove config: {err}"),
            }

            if let Ok(exe) = std::env::current_exe() {
                if let Err(err) = std::fs::remove_file(&exe) {
                    eprintln!("warning: could not remove binary {}: {}", exe.display(), err);
                    eprintln!("  remove it manually: rm {}", exe.display());
                } else {
                    eprintln!("  removed {}", exe.display());
                }
            }

            eprintln!("\nvesta has been uninstalled.");
        }
        Command::Version => {
            println!("v{}", env!("CARGO_PKG_VERSION"));
            return;
        }

        Command::Update => {
            run_cli_self_update(None);
        }

        Command::Channel { channel } => {
            let c = get_client(host_ref, token_ref);
            match channel {
                Some(channel) => {
                    let set = c.set_channel(&channel).unwrap_or_else(|e| platform::die(&e));
                    eprintln!("release channel set to '{set}' on vestad");
                    eprintln!("run 'vesta update' to move the daemon onto the {set} channel");
                }
                None => {
                    let current = c.get_channel().unwrap_or_else(|e| platform::die(&e));
                    println!("{current}");
                }
            }
        }

        Command::AutoUpdate { toggle } => {
            let c = get_client(host_ref, token_ref);
            match toggle {
                Some(toggle) => {
                    let enabled = matches!(toggle, Toggle::On);
                    let set = c.set_auto_update(enabled).unwrap_or_else(|e| platform::die(&e));
                    eprintln!("auto-update: {}", if set { "enabled" } else { "disabled" });
                }
                None => {
                    let enabled = c.get_auto_update().unwrap_or_else(|e| platform::die(&e));
                    eprintln!("auto-update: {}", if enabled { "enabled" } else { "disabled" });
                }
            }
        }
    }

    // Check update notification
    if let Some(handle) = bg_handle {
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(UPDATE_CHECK_TIMEOUT_MS);
        while !handle.is_finished() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(UPDATE_CHECK_POLL_MS));
        }
        if handle.is_finished() {
            if let Ok(Some(latest)) = handle.join() {
                print_update_available(&latest);
            }
        }
    }
}

fn main() {
    let cli = Cli::parse();
    run(cli);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_size_cases() {
        for (input, expected) in [
            (0u64, "0B"),
            (1, "1B"),
            (999, "999B"),
            (1_000, "1kB"),
            (1_500, "2kB"),
            (1_000_000, "1.0MB"),
            (1_500_000, "1.5MB"),
            (1_000_000_000, "1.0GB"),
            (2_500_000_000, "2.5GB"),
        ] {
            assert_eq!(format_size(input), expected, "format_size({input})");
        }
    }

    #[test]
    fn version_gate_classification() {
        assert_eq!(classify_version_gate("1.2.3", "1.2.3"), VersionGate::Match);
        assert_eq!(classify_version_gate("1.2.3", "1.2.4"), VersionGate::CliOlder);
        assert_eq!(classify_version_gate("1.2.3", "2.0.0"), VersionGate::CliOlder);
        assert_eq!(classify_version_gate("1.3.0", "1.2.9"), VersionGate::GatewayOlder);
        assert_eq!(classify_version_gate("2.0.0", "1.9.9"), VersionGate::GatewayOlder);
    }
}
