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

struct CloudflareEnv {
    api_token: String,
    account_id: String,
    zone_id: String,
}

fn cf_env() -> Result<CloudflareEnv, String> {
    let api_token = option_env!("CLOUDFLARE_API_TOKEN")
        .map(String::from)
        .or_else(|| std::env::var("CLOUDFLARE_API_TOKEN").ok())
        .ok_or("CLOUDFLARE_API_TOKEN not set (build-time or env)")?;
    let account_id = option_env!("CLOUDFLARE_ACCOUNT_ID")
        .map(String::from)
        .or_else(|| std::env::var("CLOUDFLARE_ACCOUNT_ID").ok())
        .ok_or("CLOUDFLARE_ACCOUNT_ID not set (build-time or env)")?;
    let zone_id = option_env!("CLOUDFLARE_ZONE_ID")
        .map(String::from)
        .or_else(|| std::env::var("CLOUDFLARE_ZONE_ID").ok())
        .ok_or("CLOUDFLARE_ZONE_ID not set (build-time or env)")?;
    Ok(CloudflareEnv { api_token, account_id, zone_id })
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

fn get_zone_domain(env: &CloudflareEnv) -> Result<String, String> {
    let url = format!("{}/zones/{}", CF_API_BASE, env.zone_id);
    let resp = cf_request("GET", &url, &env.api_token, None)?;
    resp["result"]["name"]
        .as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| "failed to get domain name from zone".to_string())
}

fn delete_tunnel_if_exists(env: &CloudflareEnv, tunnel_name: &str) {
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

fn delete_dns_record_if_exists(env: &CloudflareEnv, subdomain: &str) {
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

pub fn ensure_tunnel(config_dir: &Path) -> Result<TunnelConfig, String> {
    let preferred = generate_subdomain(0);

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
    let env = cf_env()?;
    let domain = get_zone_domain(&env)?;
    let hostname = format!("{}.{}", subdomain, domain);
    let tunnel_name = format!("vesta-{}", subdomain);

    tracing::info!(tunnel = %tunnel_name, "creating tunnel");

    delete_tunnel_if_exists(&env, &tunnel_name);

    let create_url = format!("{}/accounts/{}/cfd_tunnel", CF_API_BASE, env.account_id);
    let tunnel_secret: String = (0..32).map(|_| format!("{:02x}", rand::random::<u8>())).collect();
    let secret_b64 = base64_encode(&tunnel_secret);

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

    let env = cf_env()?;

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

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&local_bin, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| format!("chmod failed: {}", e))?;
    }

    tracing::info!(path = %local_bin.display(), "cloudflared downloaded");
    Ok(local_bin)
}

pub async fn start_tunnel(
    config_dir: &Path,
    port: u16,
) -> Result<(tokio::process::Child, String), String> {
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

    let child = tokio::process::Command::new(cloudflared)
        .args([
            "tunnel", "--config", cf_config_path.to_str().unwrap(),
            "run", "--token", &tc.tunnel_token,
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start cloudflared: {}", e))?;

    let url = format!("https://{}", tc.hostname);
    Ok((child, url))
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
}

fn base64_encode(input: &str) -> String {
    use std::io::Write;
    let mut output = std::process::Command::new("base64")
        .arg("-w0")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .expect("base64 command not found");

    output.stdin.take().unwrap().write_all(input.as_bytes()).unwrap();
    let out = output.wait_with_output().unwrap();
    String::from_utf8(out.stdout).unwrap().trim().to_string()
}
