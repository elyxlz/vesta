use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

const CLOUDFLARED_DOWNLOAD_BASE: &str = "https://github.com/cloudflare/cloudflared/releases/latest/download";
const CF_API_BASE: &str = "https://api.cloudflare.com/client/v4";

#[derive(Serialize, Deserialize, Clone)]
pub struct TunnelConfig {
    pub tunnel_id: String,
    pub tunnel_token: String,
    pub hostname: String,
    pub dns_record_id: Option<String>,
}

/// Self-hosted (BYOK) Cloudflare credentials, persisted to `cloudflare.json`.
///
/// The public vestad binary ships **no** Cloudflare token — a self-hoster brings
/// their own, scoped to a domain they control (Account → Cloudflare Tunnel: Edit,
/// Zone → DNS: Edit, Zone → Zone: Read). Managed (vesta.run) VMs never reach this
/// path: the control plane creates the tunnel and seeds `tunnel.json` directly.
#[derive(Serialize, Deserialize, Clone)]
struct CloudflareCreds {
    api_token: String,
    account_id: String,
    zone_id: String,
}

fn cf_creds_path(config_dir: &Path) -> PathBuf {
    config_dir.join("cloudflare.json")
}

/// True iff usable Cloudflare credentials already exist (saved file or env).
pub fn has_cf_creds(config_dir: &Path) -> bool {
    cf_creds_path(config_dir).exists()
        || (std::env::var("CLOUDFLARE_API_TOKEN").is_ok()
            && std::env::var("CLOUDFLARE_ACCOUNT_ID").is_ok()
            && std::env::var("CLOUDFLARE_ZONE_ID").is_ok())
}

fn save_cf_creds(config_dir: &Path, creds: &CloudflareCreds) -> Result<(), String> {
    std::fs::create_dir_all(config_dir)
        .map_err(|e| format!("failed to create config dir: {}", e))?;
    let path = cf_creds_path(config_dir);
    std::fs::write(&path, serde_json::to_string_pretty(creds).unwrap())
        .map_err(|e| format!("failed to write cloudflare creds: {}", e))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).ok();
    }
    Ok(())
}

/// Resolve Cloudflare credentials for self-hosted tunnel management.
///
/// Order: the saved `cloudflare.json` (written by `vestad connect` /
/// first-run setup), then env vars (power users + CI). There is NO baked
/// build-time token anymore — the public binary carries no shared credential.
fn cf_env(config_dir: &Path) -> Result<CloudflareCreds, String> {
    if let Ok(data) = std::fs::read_to_string(cf_creds_path(config_dir)) {
        if let Ok(creds) = serde_json::from_str::<CloudflareCreds>(&data) {
            return Ok(creds);
        }
    }
    let api_token = std::env::var("CLOUDFLARE_API_TOKEN").map_err(|_| {
        "no Cloudflare credentials — run `vestad connect` to connect your domain".to_string()
    })?;
    let account_id =
        std::env::var("CLOUDFLARE_ACCOUNT_ID").map_err(|_| "CLOUDFLARE_ACCOUNT_ID not set".to_string())?;
    let zone_id =
        std::env::var("CLOUDFLARE_ZONE_ID").map_err(|_| "CLOUDFLARE_ZONE_ID not set".to_string())?;
    Ok(CloudflareCreds { api_token, account_id, zone_id })
}

fn prompt(label: &str) -> Result<String, String> {
    use std::io::Write;
    eprint!("{label}");
    std::io::stderr().flush().ok();
    let mut s = String::new();
    std::io::stdin()
        .read_line(&mut s)
        .map_err(|e| format!("failed to read input: {}", e))?;
    Ok(s.trim().to_string())
}

/// Interactively collect + validate BYOK Cloudflare credentials, then persist
/// them (0600). The user pastes just their domain + an API token; the zone id and
/// account id are auto-discovered from the domain, so there are no opaque IDs to
/// copy. Returns the resolved creds on success.
pub fn setup_cf_creds_interactive(config_dir: &Path) -> Result<(), String> {
    use std::io::IsTerminal;

    if !std::io::stdin().is_terminal() {
        return Err(
            "connecting a domain needs an interactive terminal. Run `vestad connect` \
             from a shell, or set CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / \
             CLOUDFLARE_ZONE_ID in the environment. (Or run `vestad --standalone --no-tunnel` \
             to run locally without a tunnel.)"
                .to_string(),
        );
    }

    eprintln!();
    eprintln!("  \x1b[1;35mConnect your domain\x1b[0m");
    eprintln!();
    eprintln!("  Vesta creates a secure Cloudflare tunnel to this machine and a DNS");
    eprintln!("  record for it, on a domain you own in Cloudflare. That needs an API token.");
    eprintln!();
    eprintln!("  Create one at https://dash.cloudflare.com/profile/api-tokens");
    eprintln!("  → Create Token → Create Custom Token, with these permissions:");
    eprintln!("    • Account → Cloudflare Tunnel → Edit");
    eprintln!("    • Zone     → DNS            → Edit");
    eprintln!("    • Zone     → Zone           → Read");
    eprintln!("  Scope it to your account and your domain, then paste it below.");
    eprintln!(
        "  It's stored only on this machine ({}), never sent anywhere else.",
        cf_creds_path(config_dir).display()
    );
    eprintln!();

    let domain = prompt("  Your domain (e.g. example.com): ")?.to_lowercase();
    if domain.is_empty() {
        return Err("no domain entered".into());
    }
    let api_token = prompt("  Cloudflare API token: ")?;
    if api_token.is_empty() {
        return Err("no token entered".into());
    }

    eprintln!("  verifying token and looking up zone…");
    let zones_url = format!("{}/zones?name={}", CF_API_BASE, domain);
    let resp = cf_request("GET", &zones_url, &api_token, None)
        .map_err(|e| format!("could not verify token / find zone: {}", e))?;
    let zone = resp["result"]
        .as_array()
        .and_then(|a| a.first())
        .ok_or_else(|| {
            format!(
                "no Cloudflare zone found for '{}'. Add the domain to your Cloudflare \
                 account first, and make sure the token can read it.",
                domain
            )
        })?;
    let zone_id = zone["id"]
        .as_str()
        .ok_or("zone lookup response missing zone id")?
        .to_string();
    let account_id = zone["account"]["id"]
        .as_str()
        .ok_or("zone lookup response missing account id")?
        .to_string();

    save_cf_creds(
        config_dir,
        &CloudflareCreds { api_token, account_id, zone_id },
    )?;
    eprintln!("  \x1b[32m✓\x1b[0m connected to {}", domain);
    eprintln!();
    Ok(())
}

fn cf_request(
    method: &str,
    url: &str,
    api_token: &str,
    body: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    let mut cmd = std::process::Command::new("curl");
    cmd.args(["-sS", "-X", method, url])
        .arg("-H").arg(format!("Authorization: Bearer {}", api_token))
        .arg("-H").arg("Content-Type: application/json");

    if let Some(b) = body {
        cmd.arg("-d").arg(b.to_string());
    }

    let output = cmd.output().map_err(|e| format!("curl failed: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("cloudflare API request failed: {}", stderr));
    }

    let resp: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("failed to parse cloudflare response: {}", e))?;

    if resp["success"].as_bool() != Some(true) {
        let errors = &resp["errors"];
        return Err(format!("cloudflare API error: {}", errors));
    }

    Ok(resp)
}

fn get_zone_domain(env: &CloudflareCreds) -> Result<String, String> {
    let url = format!("{}/zones/{}", CF_API_BASE, env.zone_id);
    let resp = cf_request("GET", &url, &env.api_token, None)?;
    resp["result"]["name"]
        .as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| "failed to get domain name from zone".to_string())
}

fn delete_tunnel_if_exists(env: &CloudflareCreds, tunnel_name: &str) {
    let list_url = format!(
        "{}/accounts/{}/cfd_tunnel?name={}",
        CF_API_BASE, env.account_id, tunnel_name
    );
    let resp = match cf_request("GET", &list_url, &env.api_token, None) {
        Ok(r) => r,
        Err(_) => return,
    };
    if let Some(tunnels) = resp["result"].as_array() {
        for tunnel in tunnels {
            if tunnel["deleted_at"].is_null() {
                if let Some(id) = tunnel["id"].as_str() {
                    let del_url = format!("{}/accounts/{}/cfd_tunnel/{}", CF_API_BASE, env.account_id, id);
                    tracing::info!(tunnel_id = %id, "deleting stale tunnel");
                    cf_request("DELETE", &del_url, &env.api_token, None).ok();
                }
            }
        }
    }
}

fn delete_dns_record_if_exists(env: &CloudflareCreds, subdomain: &str) {
    let domain = match get_zone_domain(env) {
        Ok(d) => d,
        Err(_) => return,
    };
    let fqdn = format!("{}.{}", subdomain, domain);
    let list_url = format!(
        "{}/zones/{}/dns_records?type=CNAME&name={}",
        CF_API_BASE, env.zone_id, fqdn
    );
    let resp = match cf_request("GET", &list_url, &env.api_token, None) {
        Ok(r) => r,
        Err(_) => return,
    };
    if let Some(records) = resp["result"].as_array() {
        for record in records {
            if let Some(id) = record["id"].as_str() {
                let del_url = format!("{}/zones/{}/dns_records/{}", CF_API_BASE, env.zone_id, id);
                tracing::info!(record_id = %id, "deleting stale DNS record");
                cf_request("DELETE", &del_url, &env.api_token, None).ok();
            }
        }
    }
}

fn tunnel_config_path(config_dir: &Path) -> PathBuf {
    config_dir.join("tunnel.json")
}

pub fn get_tunnel_config(config_dir: &Path) -> Option<TunnelConfig> {
    let path = tunnel_config_path(config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    serde_json::from_str(&data).ok()
}

/// Drop the saved tunnel config WITHOUT touching Cloudflare. Used when the box
/// can't manage the remote tunnel (no creds — e.g. an orphaned `*.vesta.run`
/// tunnel left behind on a now-self-hosted box) so future boots stop retrying a
/// tunnel that can never register.
pub fn forget_tunnel(config_dir: &Path) {
    std::fs::remove_file(tunnel_config_path(config_dir)).ok();
}

const ANIMALS: &[&str] = &[
    "alpaca", "badger", "beaver", "bison", "bobcat", "camel", "capybara", "cardinal",
    "caribou", "chameleon", "cheetah", "chinchilla", "chipmunk", "cobra", "condor",
    "cougar", "coyote", "crane", "cricket", "crow", "dingo", "dolphin", "donkey",
    "eagle", "egret", "elk", "falcon", "ferret", "finch", "flamingo", "fox",
    "gazelle", "gecko", "gopher", "grizzly", "grouse", "gull", "hamster", "hawk",
    "hedgehog", "heron", "hornet", "hyena", "ibex", "iguana", "impala", "jackal",
    "jaguar", "jay", "kestrel", "kingfisher", "kiwi", "koala", "komodo", "lark",
    "lemur", "leopard", "lion", "llama", "lobster", "lynx", "macaw", "mamba",
    "manatee", "mantis", "marmot", "marten", "merlin", "mink", "mongoose", "moose",
    "narwhal", "newt", "ocelot", "okapi", "opossum", "osprey", "otter", "owl",
    "panda", "panther", "parrot", "pelican", "penguin", "phoenix", "pika", "piranha",
    "puma", "python", "quail", "raven", "robin", "salmon", "scorpion", "shark",
    "shrike", "sparrow", "squid", "stork", "swift", "tapir", "tern", "tiger",
    "toucan", "turtle", "viper", "vulture", "walrus", "weasel", "whale", "wolf",
    "wolverine", "wombat", "wren", "yak", "zebra",
];

fn animal_for_user(username: &str, offset: usize) -> &'static str {
    let mut hash: u64 = 5381;
    for byte in username.bytes() {
        hash = hash.wrapping_mul(33).wrapping_add(byte as u64);
    }
    ANIMALS[(hash as usize + offset) % ANIMALS.len()]
}

fn current_user() -> String {
    std::env::var("USER")
        .or_else(|_| std::env::var("LOGNAME"))
        .unwrap_or_else(|_| "unknown".into())
}

/// Sanitize a string to only contain lowercase alphanumeric characters and hyphens.
fn sanitize(s: &str) -> String {
    let cleaned: String = s.to_lowercase().replace(|c: char| !c.is_alphanumeric(), "-");
    cleaned.trim_matches('-').to_string()
}

fn generate_subdomain(offset: usize) -> String {
    let animal = animal_for_user(&current_user(), offset);
    let hostname = sanitize(&gethostname());
    let short = if hostname.len() > 20 { &hostname[..20] } else { &hostname };
    format!("{}-{}", animal, short.trim_end_matches('-'))
}

fn gethostname() -> String {
    let output = std::process::Command::new("hostname")
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default();
    if output.is_empty() { "vesta".to_string() } else { output }
}

/// Full self-host connect flow (`vestad connect`): collect the user's own
/// Cloudflare credentials, make sure cloudflared is present, then create (or
/// reuse) the tunnel. Returns the live tunnel config so the caller can show the
/// URL. This is the one command a self-hoster needs — they never have to discover
/// `tunnel setup`.
pub fn connect_interactive(config_dir: &Path) -> Result<TunnelConfig, String> {
    setup_cf_creds_interactive(config_dir)?;
    ensure_cloudflared(config_dir)?;
    ensure_tunnel(config_dir)
}

pub fn ensure_tunnel(config_dir: &Path) -> Result<TunnelConfig, String> {
    // Managed (vesta.run) VMs: the control plane creates the tunnel + DNS and
    // SEEDS tunnel.json into the config dir. vestad holds no Cloudflare account
    // credential here, so it must NEVER call the Cloudflare API — it just uses the
    // seeded config as-is. This is the load-bearing half of removing the baked
    // fleet-wide token: a managed box can run its one tunnel but cannot touch the
    // zone or any other tunnel.
    if crate::is_cloud_managed() {
        return get_tunnel_config(config_dir).ok_or_else(|| {
            "managed mode: no tunnel.json seeded by the control plane".to_string()
        });
    }

    // Self-hosted deployments pin an exact subdomain via VESTA_SUBDOMAIN only when
    // set; otherwise keep the generated <animal>-<hostname>. Creation uses the
    // BYOK creds in cloudflare.json (see cf_env / setup_cf_creds_interactive).
    let preferred = std::env::var("VESTA_SUBDOMAIN")
        .ok()
        .map(|s| sanitize(&s))
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| generate_subdomain(0));

    // Reuse existing tunnel if it matches our preferred subdomain
    if let Some(tc) = get_tunnel_config(config_dir) {
        let current = tc.hostname.split('.').next().unwrap_or("");
        if current == preferred {
            return Ok(tc);
        }
        tracing::info!(old = %current, new = %preferred, "tunnel subdomain changed, recreating");
        if let Err(e) = destroy_tunnel(config_dir) {
            tracing::warn!("failed to destroy old tunnel: {e}");
            std::fs::remove_file(tunnel_config_path(config_dir)).ok();
        }
    }

    // setup_tunnel calls delete_tunnel_if_exists, so stale tunnels with our
    // preferred name are cleaned up automatically — no need to skip to a
    // different animal.
    tracing::info!(subdomain = %preferred, "creating tunnel");
    setup_tunnel(config_dir, &preferred)
}


pub fn setup_tunnel(config_dir: &Path, subdomain: &str) -> Result<TunnelConfig, String> {
    let env = cf_env(config_dir)?;
    let domain = get_zone_domain(&env)?;
    let hostname = format!("{}.{}", subdomain, domain);
    let tunnel_name = format!("vesta-{}", subdomain);

    tracing::info!(tunnel = %tunnel_name, "creating tunnel");

    delete_tunnel_if_exists(&env, &tunnel_name);

    let create_url = format!("{}/accounts/{}/cfd_tunnel", CF_API_BASE, env.account_id);
    let tunnel_secret: String = (0..32).map(|_| format!("{:02x}", rand::random::<u8>())).collect();
    let secret_b64 = {
        use base64::Engine;
        base64::engine::general_purpose::STANDARD.encode(tunnel_secret.as_bytes())
    };

    let resp = cf_request("POST", &create_url, &env.api_token, Some(serde_json::json!({
        "name": tunnel_name,
        "tunnel_secret": secret_b64,
        "config_src": "local",
    })))?;

    let tunnel_id = resp["result"]["id"]
        .as_str()
        .ok_or("missing tunnel id in response")?
        .to_string();

    let token_url = format!("{}/accounts/{}/cfd_tunnel/{}/token", CF_API_BASE, env.account_id, tunnel_id);
    let token_resp = cf_request("GET", &token_url, &env.api_token, None)?;
    let tunnel_token = token_resp["result"]
        .as_str()
        .ok_or("missing tunnel token in response")?
        .to_string();

    tracing::info!(hostname = %hostname, tunnel_id = %tunnel_id, "creating DNS record");

    delete_dns_record_if_exists(&env, subdomain);

    let dns_url = format!("{}/zones/{}/dns_records", CF_API_BASE, env.zone_id);
    let dns_resp = cf_request("POST", &dns_url, &env.api_token, Some(serde_json::json!({
        "type": "CNAME",
        "name": subdomain,
        "content": format!("{}.cfargotunnel.com", tunnel_id),
        "proxied": true,
    })))?;

    let dns_record_id = dns_resp["result"]["id"]
        .as_str()
        .map(|s| s.to_string());

    let config = TunnelConfig {
        tunnel_id,
        tunnel_token,
        hostname: hostname.clone(),
        dns_record_id,
    };

    let config_path = tunnel_config_path(config_dir);
    std::fs::create_dir_all(config_dir)
        .map_err(|e| format!("failed to create config dir: {}", e))?;
    std::fs::write(&config_path, serde_json::to_string_pretty(&config).unwrap())
        .map_err(|e| format!("failed to write tunnel config: {}", e))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o600)).ok();
    }

    tracing::info!(hostname = %hostname, "tunnel ready");
    Ok(config)
}

pub fn destroy_tunnel(config_dir: &Path) -> Result<(), String> {
    let config = get_tunnel_config(config_dir)
        .ok_or("no tunnel configured")?;

    let env = cf_env(config_dir)?;

    if let Some(record_id) = &config.dns_record_id {
        tracing::info!("deleting DNS record");
        let dns_url = format!("{}/zones/{}/dns_records/{}", CF_API_BASE, env.zone_id, record_id);
        cf_request("DELETE", &dns_url, &env.api_token, None).ok();
    }

    tracing::info!(tunnel_id = %config.tunnel_id, "deleting tunnel");
    let tunnel_url = format!(
        "{}/accounts/{}/cfd_tunnel/{}",
        CF_API_BASE, env.account_id, config.tunnel_id
    );
    cf_request("DELETE", &tunnel_url, &env.api_token, None)
        .map_err(|e| format!("failed to delete tunnel: {}", e))?;

    std::fs::remove_file(tunnel_config_path(config_dir)).ok();
    tracing::info!("tunnel destroyed");
    Ok(())
}

pub fn ensure_cloudflared(config_dir: &Path) -> Result<PathBuf, String> {
    if let Ok(path) = which("cloudflared") {
        return Ok(path);
    }

    let local_bin = config_dir.join("cloudflared");

    if let Some((bytes, fingerprint)) = crate::cloudflared_embed::vendored_cloudflared() {
        return extract_embedded_cloudflared(config_dir, bytes, fingerprint);
    }

    if local_bin.exists() {
        return Ok(local_bin);
    }

    let arch = match std::env::consts::ARCH {
        "x86_64" => "amd64",
        "aarch64" => "arm64",
        other => return Err(format!("unsupported architecture for cloudflared: {}", other)),
    };

    let url = format!("{}/cloudflared-linux-{}", CLOUDFLARED_DOWNLOAD_BASE, arch);
    tracing::info!(url = %url, "downloading cloudflared");

    std::fs::create_dir_all(config_dir)
        .map_err(|e| format!("failed to create config dir: {}", e))?;

    let status = std::process::Command::new("curl")
        .args(["-fsSL", "-o", local_bin.to_str().unwrap(), &url])
        .status()
        .map_err(|e| format!("curl failed: {}", e))?;

    if !status.success() {
        return Err("failed to download cloudflared".to_string());
    }

    set_executable(&local_bin)?;

    tracing::info!(path = %local_bin.display(), "cloudflared downloaded");
    Ok(local_bin)
}

const CLOUDFLARED_FINGERPRINT_MARKER: &str = ".cloudflared-fingerprint";

fn extract_embedded_cloudflared(
    config_dir: &Path,
    bytes: &[u8],
    fingerprint: &str,
) -> Result<PathBuf, String> {
    let local_bin = config_dir.join("cloudflared");
    let marker = config_dir.join(CLOUDFLARED_FINGERPRINT_MARKER);
    if local_bin.exists()
        && std::fs::read_to_string(&marker).ok().as_deref() == Some(fingerprint)
    {
        return Ok(local_bin);
    }

    std::fs::create_dir_all(config_dir)
        .map_err(|e| format!("failed to create config dir: {}", e))?;
    std::fs::write(&local_bin, bytes)
        .map_err(|e| format!("failed to write embedded cloudflared: {}", e))?;
    set_executable(&local_bin)?;
    std::fs::write(&marker, fingerprint)
        .map_err(|e| format!("failed to write cloudflared fingerprint: {}", e))?;

    tracing::info!(path = %local_bin.display(), "cloudflared extracted from embed");
    Ok(local_bin)
}

fn set_executable(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
        .map_err(|e| format!("chmod failed: {}", e))
}

/// Spawn one cloudflared run for the configured tunnel. Returns the child and
/// the loopback port of its metrics server (for /ready probing).
async fn start_tunnel(
    config_dir: &Path,
    port: u16,
) -> Result<(tokio::process::Child, u16), String> {
    let tc = get_tunnel_config(config_dir)
        .ok_or("no tunnel configured — run `vestad tunnel setup <subdomain>` first")?;

    let cloudflared = ensure_cloudflared(config_dir)?;

    let cf_config_path = config_dir.join("cloudflared.yml");
    let cf_config = format!(
        "tunnel: {tunnel_id}\n\
         ingress:\n\
         \x20 - hostname: {hostname}\n\
         \x20   service: https://localhost:{port}\n\
         \x20   originRequest:\n\
         \x20     noTLSVerify: true\n\
         \x20 - service: http_status:404\n",
        tunnel_id = tc.tunnel_id,
        hostname = tc.hostname,
        port = port,
    );
    std::fs::write(&cf_config_path, &cf_config)
        .map_err(|e| format!("failed to write cloudflared config: {}", e))?;

    // Loopback metrics server: exposes cloudflared's /ready endpoint, which the
    // supervisor probes for registered edge connections. Bind-and-drop to pick a
    // free port; if something grabs it before cloudflared does, cloudflared exits
    // and the supervisor respawns with a fresh port.
    let metrics_port = alloc_loopback_port()?;
    let metrics_addr = format!("127.0.0.1:{metrics_port}");

    // Force HTTP/2 over TCP instead of the QUIC/UDP default. Home and laptop NAT
    // devices aggressively time out idle UDP flows, which silently drops the
    // tunnel and yields error 1033 on the next request (e.g. the first file
    // share after an idle period). TCP keeps the connection alive far longer.
    let mut child = tokio::process::Command::new(cloudflared)
        .args([
            "tunnel", "--protocol", "http2", "--metrics", &metrics_addr,
            "--config", cf_config_path.to_str().unwrap(),
            "run", "--token", &tc.tunnel_token,
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        // SIGKILL the child if its handle is dropped without an explicit kill
        // (supervisor task aborted, runtime torn down by a panic) so cloudflared
        // is never orphaned holding the hostname.
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("failed to start cloudflared: {}", e))?;

    // cloudflared logs its connection lifecycle (registering/registered/lost connections)
    // to stderr. Forward it into vestad's tracing so `vestad logs` shows tunnel state —
    // otherwise a reconnecting tunnel looks like silence and a transient 502 has no trail.
    // This also drains the piped stderr, which would otherwise fill and stall cloudflared.
    if let Some(stderr) = child.stderr.take() {
        tokio::spawn(async move {
            use tokio::io::AsyncBufReadExt;
            let mut lines = tokio::io::BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let line = line.trim();
                if !line.is_empty() {
                    tracing::info!(target: "tunnel", "{line}");
                }
            }
        });
    }

    Ok((child, metrics_port))
}

/// Bind-and-drop an ephemeral loopback port for cloudflared's metrics server.
fn alloc_loopback_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0))
        .map_err(|e| format!("failed to allocate metrics port: {}", e))?;
    let addr = listener
        .local_addr()
        .map_err(|e| format!("failed to read metrics port: {}", e))?;
    Ok(addr.port())
}

/// How long boot-time pre-flight waits for cloudflared to register an edge
/// connection before declaring the saved tunnel dead. Generous enough to absorb
/// a slow first connect, short enough not to stall startup.
const PREFLIGHT_READY_TIMEOUT_SECS: u64 = 20;
const PREFLIGHT_POLL_INTERVAL_MS: u64 = 500;

/// Credential-free boot check that the saved tunnel can actually register.
///
/// Spawns one short-lived cloudflared and polls its /ready endpoint until it
/// reports a registered edge connection, then kills it (the supervisor owns the
/// long-lived child). Returns `false` if cloudflared exits early — e.g.
/// "Unauthorized: Tunnel not found" when the tunnel was deleted server-side or
/// its token revoked — or never registers within PREFLIGHT_READY_TIMEOUT_SECS.
/// This relies only on cloudflared's local /ready, so it works on a box that
/// holds no Cloudflare credentials and can't query the API.
pub async fn preflight_tunnel(config_dir: &Path, port: u16) -> bool {
    let (mut child, metrics_port) = match start_tunnel(config_dir, port).await {
        Ok(pair) => pair,
        Err(e) => {
            tracing::warn!("tunnel pre-flight could not start cloudflared: {e}");
            return false;
        }
    };
    let probe_client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(READY_PROBE_TIMEOUT_SECS))
        .build()
    {
        Ok(client) => client,
        Err(e) => {
            tracing::warn!("tunnel pre-flight probe client unavailable: {e}");
            child.kill().await.ok();
            return false;
        }
    };
    let probe_url = format!("http://127.0.0.1:{metrics_port}/ready");
    let deadline =
        tokio::time::Instant::now() + std::time::Duration::from_secs(PREFLIGHT_READY_TIMEOUT_SECS);
    let ready = loop {
        // cloudflared gave up on its own (dead tunnel / revoked token).
        if matches!(child.try_wait(), Ok(Some(_))) {
            break false;
        }
        let registered = match probe_client.get(&probe_url).send().await {
            Ok(resp) => resp.status().is_success(),
            Err(_) => false,
        };
        if registered {
            break true;
        }
        if tokio::time::Instant::now() >= deadline {
            break false;
        }
        tokio::time::sleep(std::time::Duration::from_millis(PREFLIGHT_POLL_INTERVAL_MS)).await;
    };
    child.kill().await.ok();
    ready
}

// --- Tunnel supervision ---
//
// cloudflared is the one long-running child vestad owns, and a dead tunnel is
// invisible from the inside: vestad stays healthy, systemd sees nothing wrong,
// and every request to the hostname gets Cloudflare error 1033 until someone
// restarts vestad by hand. Two failure modes, two layers:
//   - the process exits (crash, OOM, fatal give-up) -> respawn after a fixed delay
//   - the process wedges with its edge connections dead -> cloudflared's own
//     /ready endpoint (loopback metrics port) reports no registered connection;
//     after consecutive failures the child is killed and respawned.
// The probe is deliberately LOCAL. Probing the public hostname through the
// Cloudflare edge would conflate probe-path failures (host DNS/egress, an edge
// incident) with a wedged connector and kill a healthy tunnel — dropping every
// live session through it. /ready measures exactly the thing a restart fixes.
// Config-level death (tunnel deleted server-side, token revoked) is NOT
// self-healed here: cloudflared exits with the reason, which lands in
// `vestad logs` via the stderr forwarder; recovery is `vestad connect`.

/// Delay between cloudflared respawns. Fixed rather than exponential: the one
/// child vestad owns rarely dies, and a constant delay recovers promptly
/// without the backoff/healthy-reset bookkeeping. Permanent failure (a revoked
/// token) loops at this cadence with cloudflared's reason in `vestad logs`.
const TUNNEL_RESPAWN_DELAY_SECS: u64 = 15;
const READY_PROBE_INTERVAL_SECS: u64 = 30;
const READY_PROBE_TIMEOUT_SECS: u64 = 5;
/// Consecutive failed /ready probes before cloudflared is restarted.
const READY_PROBE_MAX_FAILURES: u32 = 3;
/// How long the tunnel must stay unregistered before the supervisor reports it
/// down to status.json. Longer than a normal restart-recovery cycle, so transient
/// blips the supervisor heals on its own keep the status showing "enabled".
const TUNNEL_DOWN_SUSTAINED_SECS: u64 = 120;

pub struct TunnelSupervisor {
    shutdown: tokio::sync::watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}

impl TunnelSupervisor {
    /// Kill the current cloudflared and stop supervising (graceful shutdown).
    pub async fn shutdown(self) {
        self.shutdown.send(true).ok();
        self.task.await.ok();
    }
}

/// Spawn cloudflared and keep it alive until `shutdown()`: respawn on exit or
/// on a failed edge probe streak, after a fixed delay between attempts.
///
/// `on_tunnel_up(bool)` is invoked on SUSTAINED edge changes (debounced) so the
/// caller can mirror tunnel health into status.json: `true` as soon as the tunnel
/// re-registers, `false` only after it has been unregistered for
/// `TUNNEL_DOWN_SUSTAINED_SECS` (so transient blips the supervisor heals don't
/// flip status). Kept as a plain `Fn(bool)` to keep this module free of caller
/// types.
pub fn supervise_tunnel(
    config_dir: PathBuf,
    port: u16,
    on_tunnel_up: std::sync::Arc<dyn Fn(bool) + Send + Sync>,
) -> TunnelSupervisor {
    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
    let task = tokio::spawn(async move {
        // One client for every probe across respawns. Build failure is
        // near-impossible; if it happens, degrade to exit-only supervision and
        // say so once instead of silently skipping every probe.
        let probe_client = match reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(READY_PROBE_TIMEOUT_SECS))
            .build()
        {
            Ok(client) => Some(client),
            Err(e) => {
                tracing::warn!("tunnel ready probe disabled, supervising exits only: {e}");
                None
            }
        };
        // Edge state for status.json, carried across cloudflared restarts. The
        // supervisor only runs once the tunnel was verified up, so we start
        // "reported up" with `now` as the last registered time.
        let mut reported_up = true;
        let mut last_registered = tokio::time::Instant::now();
        loop {
            match start_tunnel(&config_dir, port).await {
                Ok((mut child, metrics_port)) => {
                    let reason = tokio::select! {
                        _ = shutdown_rx.changed() => {
                            child.kill().await.ok();
                            return;
                        }
                        reason = run_until_unhealthy(
                            &mut child,
                            probe_client.as_ref(),
                            metrics_port,
                            on_tunnel_up.as_ref(),
                            &mut reported_up,
                            &mut last_registered,
                        ) => reason,
                    };
                    child.kill().await.ok();
                    tracing::warn!(delay_secs = TUNNEL_RESPAWN_DELAY_SECS, "tunnel unhealthy ({reason}), restarting cloudflared");
                }
                Err(e) => {
                    tracing::warn!(delay_secs = TUNNEL_RESPAWN_DELAY_SECS, "tunnel start failed: {e}");
                }
            }
            tokio::select! {
                _ = shutdown_rx.changed() => return,
                _ = tokio::time::sleep(std::time::Duration::from_secs(TUNNEL_RESPAWN_DELAY_SECS)) => {}
            }
        }
    });
    TunnelSupervisor { shutdown: shutdown_tx, task }
}

/// Watch one cloudflared run; returns the reason it must be replaced (process
/// exit, or /ready failing READY_PROBE_MAX_FAILURES times in a row). Drives the
/// debounced `on_tunnel_up` edge callback via `reported_up`/`last_registered`,
/// which persist across restarts.
async fn run_until_unhealthy(
    child: &mut tokio::process::Child,
    probe_client: Option<&reqwest::Client>,
    metrics_port: u16,
    on_tunnel_up: &(dyn Fn(bool) + Send + Sync),
    reported_up: &mut bool,
    last_registered: &mut tokio::time::Instant,
) -> String {
    let probe_url = format!("http://127.0.0.1:{metrics_port}/ready");
    let probe_interval = std::time::Duration::from_secs(READY_PROBE_INTERVAL_SECS);
    // First probe only after a full interval, so cloudflared has time to register.
    let mut probe_ticks =
        tokio::time::interval_at(tokio::time::Instant::now() + probe_interval, probe_interval);
    // Don't burst queued ticks after a host suspend/resume: three instant
    // probes would read as a failure streak and kill a tunnel that is still
    // reconnecting on its own.
    probe_ticks.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut consecutive_failures = 0u32;
    loop {
        tokio::select! {
            status = child.wait() => {
                return match status {
                    Ok(s) => format!("cloudflared exited: {s}"),
                    Err(e) => format!("cloudflared wait failed: {e}"),
                };
            }
            _ = probe_ticks.tick() => {
                let Some(client) = probe_client else { continue };
                // /ready is 200 iff cloudflared has a registered edge connection.
                let ok = match client.get(&probe_url).send().await {
                    Ok(resp) => resp.status().is_success(),
                    Err(_) => false,
                };
                // Mirror health into status.json on sustained edges only: "up" the
                // moment it re-registers, "down" only after a sustained outage.
                if ok {
                    *last_registered = tokio::time::Instant::now();
                    if !*reported_up {
                        on_tunnel_up(true);
                        *reported_up = true;
                    }
                } else if *reported_up
                    && last_registered.elapsed() >= std::time::Duration::from_secs(TUNNEL_DOWN_SUSTAINED_SECS)
                {
                    on_tunnel_up(false);
                    *reported_up = false;
                }
                let (failures, restart) = record_probe(consecutive_failures, ok);
                consecutive_failures = failures;
                if !ok {
                    tracing::warn!(consecutive_failures, "tunnel ready probe failed (no registered edge connection)");
                }
                if restart {
                    return format!("no ready edge connection for {consecutive_failures} consecutive probes");
                }
            }
        }
    }
}

/// Pure probe accounting: a success clears the failure streak; a failure
/// extends it, demanding a restart at READY_PROBE_MAX_FAILURES.
fn record_probe(consecutive_failures: u32, ok: bool) -> (u32, bool) {
    if ok {
        return (0, false);
    }
    let failures = consecutive_failures + 1;
    (failures, failures >= READY_PROBE_MAX_FAILURES)
}

fn which(name: &str) -> Result<PathBuf, ()> {
    let output = std::process::Command::new("which")
        .arg(name)
        .output()
        .map_err(|_| ())?;
    if output.status.success() {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !path.is_empty() {
            return Ok(PathBuf::from(path));
        }
    }
    Err(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn animal_for_user_is_deterministic() {
        let a1 = animal_for_user("alice", 0);
        let a2 = animal_for_user("alice", 0);
        assert_eq!(a1, a2);
    }

    #[test]
    fn animal_offset_changes_result() {
        let a = animal_for_user("alice", 0);
        let b = animal_for_user("alice", 1);
        assert_ne!(a, b, "different offsets should give different animals");
    }

    #[test]
    fn animal_is_from_list() {
        for name in ["alice", "bob", "root", "deploy", "test-user", "x"] {
            let animal = animal_for_user(name, 0);
            assert!(ANIMALS.contains(&animal), "{name} mapped to '{animal}' which is not in ANIMALS");
        }
    }

    #[test]
    fn subdomain_format_is_animal_dash_hostname() {
        let sub = generate_subdomain(0);
        assert!(sub.contains('-'), "subdomain should contain a dash: {sub}");
        let animal_part = sub.split('-').next().unwrap();
        assert!(ANIMALS.contains(&animal_part), "first part should be an animal: {sub}");
    }

    #[test]
    fn sanitize_strips_special_chars() {
        assert_eq!(sanitize("Alice.Bob"), "alice-bob");
        assert_eq!(sanitize("--test--"), "test");
        assert_eq!(sanitize("a_b@c"), "a-b-c");
    }

    #[test]
    fn probe_success_clears_the_failure_streak() {
        assert_eq!(record_probe(READY_PROBE_MAX_FAILURES - 1, true), (0, false));
    }

    #[test]
    fn probe_failures_demand_restart_only_at_threshold() {
        let mut failures = 0;
        for expected in 1..READY_PROBE_MAX_FAILURES {
            let (count, restart) = record_probe(failures, false);
            assert_eq!(count, expected);
            assert!(!restart, "no restart before the threshold");
            failures = count;
        }
        let (count, restart) = record_probe(failures, false);
        assert_eq!(count, READY_PROBE_MAX_FAILURES);
        assert!(restart, "restart at the threshold");
    }

    #[test]
    fn alloc_loopback_port_returns_a_usable_port() {
        let port = alloc_loopback_port().expect("allocation succeeds");
        assert_ne!(port, 0);
    }
}

