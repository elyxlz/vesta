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

fn tunnel_config_path(config_dir: &Path) -> PathBuf {
    config_dir.join("tunnel.json")
}

pub fn get_tunnel_config(config_dir: &Path) -> Option<TunnelConfig> {
    let path = tunnel_config_path(config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    serde_json::from_str(&data).ok()
}

pub fn generate_subdomain() -> String {
    let hostname = gethostname().to_lowercase().replace(|c: char| !c.is_alphanumeric(), "-");
    let hostname = hostname.trim_matches('-');
    let short = if hostname.len() > 20 { &hostname[..20] } else { hostname };
    let suffix: String = (0..4).map(|_| format!("{:x}", rand::random::<u8>() & 0xf)).collect();
    format!("{}-{}", short, suffix)
}

fn gethostname() -> String {
    let output = std::process::Command::new("hostname")
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default();
    if output.is_empty() { "vesta".to_string() } else { output }
}

pub fn ensure_tunnel(config_dir: &Path) -> Result<TunnelConfig, String> {
    if let Some(tc) = get_tunnel_config(config_dir) {
        return Ok(tc);
    }
    let subdomain = generate_subdomain();
    eprintln!("auto-creating tunnel with subdomain: {}", subdomain);
    setup_tunnel(config_dir, &subdomain)
}

pub fn setup_tunnel(config_dir: &Path, subdomain: &str) -> Result<TunnelConfig, String> {
    let env = cf_env()?;
    let domain = get_zone_domain(&env)?;
    let hostname = format!("{}.{}", subdomain, domain);
    let tunnel_name = format!("vesta-{}", subdomain);

    eprintln!("creating tunnel {}...", tunnel_name);

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

    eprintln!("creating DNS record {} -> {}...", hostname, tunnel_id);

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

    eprintln!("tunnel ready: https://{}", hostname);
    Ok(config)
}

pub fn destroy_tunnel(config_dir: &Path) -> Result<(), String> {
    let config = get_tunnel_config(config_dir)
        .ok_or("no tunnel configured")?;

    let env = cf_env()?;

    if let Some(record_id) = &config.dns_record_id {
        eprintln!("deleting DNS record...");
        let dns_url = format!("{}/zones/{}/dns_records/{}", CF_API_BASE, env.zone_id, record_id);
        cf_request("DELETE", &dns_url, &env.api_token, None).ok();
    }

    eprintln!("deleting tunnel {}...", config.tunnel_id);
    let tunnel_url = format!(
        "{}/accounts/{}/cfd_tunnel/{}",
        CF_API_BASE, env.account_id, config.tunnel_id
    );
    cf_request("DELETE", &tunnel_url, &env.api_token, None)
        .map_err(|e| format!("failed to delete tunnel: {}", e))?;

    std::fs::remove_file(tunnel_config_path(config_dir)).ok();
    eprintln!("tunnel destroyed");
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
    eprintln!("downloading cloudflared from {}...", url);

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

    eprintln!("cloudflared downloaded to {}", local_bin.display());
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
