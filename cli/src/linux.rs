use super::*;
use serde::Serialize;
use std::io::{self, Write};

const VESTA_IMAGE: &str = "ghcr.io/elyxlz/vesta:latest";
const LOCAL_IMAGE_TAG: &str = "vesta:local";
const MAX_DOCKERFILE_SEARCH_DEPTH: usize = 5;
const CREDENTIALS_PATH: &str = "/root/.claude/.credentials.json";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";
const BASE_WS_PORT: u16 = 7865;
const NAME_MAX_LEN: usize = 32;

#[derive(PartialEq)]
enum ContainerStatus {
    Running,
    Stopped,
    NotFound,
    Dead,
}

#[derive(Serialize)]
struct StatusJson {
    name: String,
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    authenticated: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    agent_ready: bool,
    ws_port: u16,
    alive: bool,
    friendly_status: &'static str,
}

#[derive(Serialize)]
struct ListEntry {
    name: String,
    status: &'static str,
    authenticated: bool,
    agent_ready: bool,
    ws_port: u16,
    alive: bool,
    friendly_status: &'static str,
}

fn container_name(name: &str) -> String {
    format!("vesta-{}", name)
}

fn normalize_name(raw: &str) -> String {
    let s: String = raw.trim().to_lowercase()
        .replace(|c: char| c.is_whitespace() || c == '_', "-")
        .chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '-').collect();
    let s = s.trim_matches('-').to_string();
    let mut result = String::new();
    let mut prev_hyphen = false;
    for c in s.chars() {
        if c == '-' {
            if !prev_hyphen { result.push(c); }
            prev_hyphen = true;
        } else {
            result.push(c);
            prev_hyphen = false;
        }
    }
    if result.len() > NAME_MAX_LEN {
        result.truncate(NAME_MAX_LEN);
        result = result.trim_end_matches('-').to_string();
    }
    result
}

fn try_validate_name(name: &str) -> Result<(), &'static str> {
    if name.is_empty() || name.len() > NAME_MAX_LEN {
        return Err("agent name must be 1-32 characters");
    }
    let valid = if name.len() == 1 {
        name.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
    } else {
        let chars: Vec<char> = name.chars().collect();
        let first_last_ok = (chars[0].is_ascii_lowercase() || chars[0].is_ascii_digit())
            && (chars[chars.len() - 1].is_ascii_lowercase() || chars[chars.len() - 1].is_ascii_digit());
        let middle_ok = chars.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '-');
        first_last_ok && middle_ok
    };
    if !valid {
        return Err("agent name must match [a-z0-9][a-z0-9-]*[a-z0-9]");
    }
    Ok(())
}

fn validate_name(name: &str) {
    if let Err(msg) = try_validate_name(name) {
        die(msg);
    }
}

fn prompt_name() -> String {
    eprint!("agent name: ");
    io::stderr().flush().ok();
    let mut input = String::new();
    io::stdin().read_line(&mut input).ok();
    let name = normalize_name(&input);
    if name.is_empty() {
        die("agent name is required");
    }
    name
}

fn docker(args: &[&str]) -> process::ExitStatus {
    process::Command::new("docker")
        .args(args)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|_| die("failed to run docker"))
}

fn docker_ok(args: &[&str]) -> bool {
    docker(args).success()
}

fn docker_output(args: &[&str]) -> Option<String> {
    let output = process::Command::new("docker")
        .args(args)
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn docker_quiet(args: &[&str]) -> bool {
    process::Command::new("docker")
        .args(args)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn docker_interactive(args: &[&str]) {
    let status = process::Command::new("docker")
        .args(args)
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|e| die(&format!("docker failed: {}", e)));
    if !status.success() {
        process::exit(status.code().unwrap_or(1));
    }
}

fn ensure_docker() {
    if !docker_quiet(&["--version"]) {
        die("docker is not installed.\ninstall: https://docs.docker.com/get-docker/");
    }
    for _ in 0..10 {
        if docker_quiet(&["info"]) {
            return;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
    die("docker daemon is not running. start the docker service and try again.");
}

fn container_status(cname: &str) -> ContainerStatus {
    match docker_output(&["inspect", "--format", "{{.State.Status}}", cname]) {
        Some(s) => match s.as_str() {
            "running" | "restarting" | "paused" => ContainerStatus::Running,
            "exited" | "created" => ContainerStatus::Stopped,
            "dead" | "removing" => ContainerStatus::Dead,
            _ => ContainerStatus::Stopped,
        },
        None => ContainerStatus::NotFound,
    }
}

fn read_container_file(cname: &str, container_path: &str) -> Option<String> {
    let tmp = std::env::temp_dir().join(format!("vesta_read_{}_{}", std::process::id(), cname));
    let src = format!("{}:{}", cname, container_path);
    if !docker_quiet(&["cp", &src, tmp.to_str().unwrap()]) {
        return None;
    }
    let content = std::fs::read_to_string(&tmp).ok();
    std::fs::remove_file(&tmp).ok();
    content.map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

fn is_authenticated(cname: &str) -> bool {
    let Some(content) = read_container_file(cname, CREDENTIALS_PATH) else {
        return false;
    };
    let Ok(creds) = serde_json::from_str::<serde_json::Value>(&content) else {
        return false;
    };
    let Some(expires_at) = creds["claudeAiOauth"]["expiresAt"].as_u64() else {
        return false;
    };
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    expires_at > now_ms
}

fn is_agent_ready(cname: &str, port: u16) -> bool {
    docker_quiet(&[
        "exec", cname, "bash", "-c",
        &format!("echo > /dev/tcp/localhost/{}", port),
    ])
}

fn ensure_exists(cname: &str) {
    match container_status(cname) {
        ContainerStatus::NotFound => die(&format!("agent '{}' not found. create one first with: vesta setup", cname)),
        ContainerStatus::Dead => die(&format!("agent '{}' is in a broken state. run: vesta destroy <name> --yes && vesta setup", cname)),
        _ => {}
    }
}

fn ensure_running(cname: &str) {
    ensure_exists(cname);
    if container_status(cname) != ContainerStatus::Running {
        die(&format!("agent '{}' is not running", cname));
    }
}

fn confirm(prompt: &str) -> bool {
    eprint!("{}", prompt);
    io::stderr().flush().ok();
    let mut input = String::new();
    io::stdin().read_line(&mut input).ok();
    input.trim() == "y"
}

fn find_dockerfile() -> std::path::PathBuf {
    let cwd =
        std::env::current_dir().unwrap_or_else(|_| die("cannot determine working directory"));
    if cwd.join("Dockerfile").exists() {
        return cwd;
    }

    let exe =
        std::env::current_exe().unwrap_or_else(|_| die("cannot determine executable path"));
    let mut dir = exe.parent().map(std::path::Path::to_path_buf);
    let mut depth = 0;
    while let Some(d) = dir {
        if depth >= MAX_DOCKERFILE_SEARCH_DEPTH {
            break;
        }
        if d.join("Dockerfile").exists() {
            return d;
        }
        dir = d.parent().map(std::path::Path::to_path_buf);
        depth += 1;
    }
    die("Dockerfile not found. run vesta setup --build from the repo root.");
}

fn resolve_image(build: bool) -> &'static str {
    if build {
        let context = find_dockerfile();
        eprintln!("building image from {}...", context.display());
        let status = process::Command::new("docker")
            .args(["build", "-t", LOCAL_IMAGE_TAG, "."])
            .current_dir(&context)
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::inherit())
            .status()
            .unwrap_or_else(|e| die(&format!("docker build failed: {}", e)));
        if !status.success() {
            die("image build failed");
        }
        LOCAL_IMAGE_TAG
    } else {
        eprintln!("pulling image...");
        if !docker_quiet(&["pull", VESTA_IMAGE]) {
            die("failed to pull image. check your internet connection.");
        }
        VESTA_IMAGE
    }
}

fn allocate_port() -> u16 {
    let used: Vec<u16> = list_managed_containers()
        .iter()
        .map(|cname| get_container_port(cname))
        .collect();
    let mut port = BASE_WS_PORT;
    while used.contains(&port) {
        port += 1;
    }
    port
}

fn get_container_port(cname: &str) -> u16 {
    docker_output(&[
        "inspect", "--format", "{{index .Config.Labels \"vesta.ws_port\"}}", cname,
    ])
    .and_then(|s| s.parse().ok())
    .unwrap_or(BASE_WS_PORT)
}

fn list_managed_containers() -> Vec<String> {
    docker_output(&[
        "ps", "-a",
        "--filter", "label=vesta.managed=true",
        "--format", "{{.Names}}",
    ])
    .unwrap_or_default()
    .lines()
    .filter(|l| !l.trim().is_empty())
    .map(|l| l.trim().to_string())
    .collect()
}

fn create_container(cname: &str, image: &str, port: u16) {
    let ws_port_env = format!("WS_PORT={}", port);
    let port_label = format!("vesta.ws_port={}", port);
    let args = vec![
        "create", "--name", cname, "-it", "--privileged",
        "--restart", "unless-stopped", "--network", "host",
        "--label", "vesta.managed=true",
        "--label", &port_label,
        "-e", &ws_port_env,
        image,
    ];
    if !docker_ok(&args) {
        die("failed to create container");
    }
}

const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
const OAUTH_TOKEN_URL: &str = "https://console.anthropic.com/v1/oauth/token";
const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

fn base64url(b64: &str) -> String {
    b64.replace('+', "-").replace('/', "_").replace('=', "")
}

fn generate_pkce() -> (String, String) {
    let raw = process::Command::new("openssl")
        .args(["rand", "-base64", "32"])
        .output()
        .unwrap_or_else(|_| die("openssl not found — install openssl"));
    let verifier = base64url(String::from_utf8_lossy(&raw.stdout).trim());

    let sha_cmd = format!(
        "printf '%s' '{}' | openssl dgst -sha256 -binary | openssl base64 -A",
        verifier
    );
    let raw = process::Command::new("sh")
        .args(["-c", &sha_cmd])
        .output()
        .unwrap_or_else(|_| die("failed to compute code challenge"));
    let challenge = base64url(String::from_utf8_lossy(&raw.stdout).trim());

    (verifier, challenge)
}

fn generate_state() -> String {
    let raw = process::Command::new("openssl")
        .args(["rand", "-base64", "32"])
        .output()
        .unwrap_or_else(|_| die("openssl not found"));
    base64url(String::from_utf8_lossy(&raw.stdout).trim())
}

fn obtain_credentials(_image: &str) -> String {
    eprintln!("authenticating claude...");

    let (code_verifier, code_challenge) = generate_pkce();
    let state = generate_state();

    let auth_url = format!(
        "{}?code=true&client_id={}&redirect_uri={}&response_type=code&scope={}&code_challenge={}&code_challenge_method=S256&state={}",
        OAUTH_AUTHORIZE_URL,
        OAUTH_CLIENT_ID,
        urlencod(OAUTH_REDIRECT_URI),
        urlencod("user:inference user:profile"),
        code_challenge,
        state,
    );

    eprintln!("auth-url: {}", auth_url);
    try_open_browser(&auth_url);

    eprintln!("auth-code-needed");
    let mut input = String::new();
    io::stdin().read_line(&mut input).unwrap_or_else(|_| die("failed to read auth code"));
    let input = input.trim();
    if input.is_empty() {
        die("no auth code provided");
    }

    // The pasted code includes #state suffix — extract code and state
    let (auth_code, pasted_state) = match input.split_once('#') {
        Some((code, st)) => (code, st),
        None => (input, state.as_str()),
    };

    // Exchange authorization code for tokens
    let body = format!(
        r#"{{"grant_type":"authorization_code","code":"{}","client_id":"{}","redirect_uri":"{}","code_verifier":"{}","state":"{}"}}"#,
        auth_code, OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI, code_verifier, pasted_state,
    );

    let response = process::Command::new("curl")
        .args([
            "-s", "-X", "POST", OAUTH_TOKEN_URL,
            "-H", "Content-Type: application/json",
            "-d", &body,
        ])
        .output()
        .unwrap_or_else(|_| die("curl not found — install curl"));

    let response_str = String::from_utf8_lossy(&response.stdout);
    let token_data: serde_json::Value = serde_json::from_str(&response_str)
        .unwrap_or_else(|_| {
            eprintln!("auth-code-invalid");
            die(&format!("token exchange failed: {}", response_str));
        });

    if let Some(error) = token_data.get("error") {
        eprintln!("auth-code-invalid");
        die(&format!("auth failed: {} — {}", error, token_data.get("error_description").unwrap_or(error)));
    }

    let access_token = token_data["access_token"].as_str()
        .unwrap_or_else(|| die("no access_token in response"));
    let refresh_token = token_data.get("refresh_token").and_then(|v| v.as_str());
    let expires_in = token_data["expires_in"].as_u64().unwrap_or(28800);

    let expires_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() + (expires_in as u128) * 1000;

    // Construct credentials.json in the format Claude Code expects
    let mut creds = serde_json::json!({
        "claudeAiOauth": {
            "accessToken": access_token,
            "expiresAt": expires_at as u64,
        }
    });
    if let Some(rt) = refresh_token {
        creds["claudeAiOauth"]["refreshToken"] = serde_json::json!(rt);
    }
    if let Some(scopes) = token_data.get("scope").and_then(|v| v.as_str()) {
        let scope_list: Vec<&str> = scopes.split_whitespace().collect();
        creds["claudeAiOauth"]["scopes"] = serde_json::json!(scope_list);
    }

    creds.to_string()
}

fn urlencod(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 3);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                out.push('%');
                out.push(char::from(b"0123456789ABCDEF"[(b >> 4) as usize]));
                out.push(char::from(b"0123456789ABCDEF"[(b & 0xf) as usize]));
            }
        }
    }
    out
}

fn docker_cp_content(container: &str, content: &str, dest: &str) {
    let tmp = std::env::temp_dir().join(format!("vesta_{}", std::process::id()));
    std::fs::write(&tmp, content)
        .unwrap_or_else(|e| die(&format!("failed to write temp file: {}", e)));
    let target = format!("{}:{}", container, dest);
    let ok = docker_ok(&["cp", tmp.to_str().unwrap(), &target]);
    std::fs::remove_file(&tmp).ok();
    if !ok {
        die(&format!("failed to copy to {}", dest));
    }
}

fn inject_credentials(container: &str, credentials: &str) {
    let tmp_dir = std::env::temp_dir().join(format!("vesta_claude_{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir)
        .unwrap_or_else(|e| die(&format!("failed to create temp dir: {}", e)));
    std::fs::write(tmp_dir.join(".credentials.json"), credentials)
        .unwrap_or_else(|e| die(&format!("failed to write temp credentials: {}", e)));
    let src = format!("{}/.", tmp_dir.to_str().unwrap());
    let target = format!("{}:/root/.claude/", container);
    let ok = docker_ok(&["cp", &src, &target]);
    std::fs::remove_dir_all(&tmp_dir).ok();
    if !ok {
        die("failed to copy credentials to container");
    }
    docker_cp_content(container, "{\"hasCompletedOnboarding\":true}", CLAUDE_JSON_PATH);
}

fn maybe_migrate_legacy() {
    if docker_output(&["inspect", "--format", "{{.State.Status}}", "vesta"]).is_none() {
        return;
    }

    let managed = list_managed_containers();
    if !managed.is_empty() {
        return;
    }

    let cs = container_status("vesta");
    if cs == ContainerStatus::Dead {
        eprintln!("removing dead legacy container 'vesta'...");
        docker_ok(&["rm", "-f", "vesta"]);
        return;
    }

    eprintln!("migrating legacy container 'vesta'...");

    let was_running = cs == ContainerStatus::Running;

    let name = read_container_file("vesta", "/root/.vesta-name").unwrap_or_else(|| "default".to_string());
    validate_name(&name);
    let cname = container_name(&name);

    let migrate_tag = "vesta-migrate:temp";
    if !docker_ok(&[
        "commit",
        "--change", "LABEL vesta.managed=true",
        "--change", &format!("LABEL vesta.ws_port={}", BASE_WS_PORT),
        "vesta", migrate_tag,
    ]) {
        die("failed to commit legacy container for migration");
    }

    docker_ok(&["rm", "-f", "vesta"]);

    create_container(&cname, migrate_tag, BASE_WS_PORT);

    if was_running {
        docker_ok(&["start", &cname]);
    }

    docker_ok(&["rmi", migrate_tag]);
    eprintln!("migrated legacy container to '{}'", cname);
}

fn name_from_cname(cname: &str) -> String {
    cname.strip_prefix("vesta-").unwrap_or(cname).to_string()
}

fn status_label(cs: &ContainerStatus) -> &'static str {
    match cs {
        ContainerStatus::Running => "running",
        ContainerStatus::Dead => "dead",
        ContainerStatus::NotFound => "not_found",
        ContainerStatus::Stopped => "stopped",
    }
}

fn friendly_status(status: &ContainerStatus, authenticated: bool, agent_ready: bool) -> &'static str {
    match status {
        ContainerStatus::Running if !authenticated => "not signed in",
        ContainerStatus::Running if agent_ready => "alive",
        ContainerStatus::Running => "starting...",
        ContainerStatus::Dead => "broken",
        ContainerStatus::Stopped => "stopped",
        ContainerStatus::NotFound => "not found",
    }
}

pub fn run(command: Command) {
    ensure_docker();
    maybe_migrate_legacy();

    match command {
        Command::Setup { build, yes, name } => {
            let name = name.map(|n| normalize_name(&n)).unwrap_or_else(prompt_name);
            validate_name(&name);
            let cname = container_name(&name);

            if container_status(&cname) != ContainerStatus::NotFound {
                if !yes && !confirm(&format!("agent '{}' already exists. destroy and recreate? [y/N] ", name)) {
                    println!("aborted");
                    return;
                }
                eprintln!("replacing existing agent...");
                docker_ok(&["rm", "-f", &cname]);
            }

            let image = resolve_image(build);
            let credentials = obtain_credentials(image);
            let port = allocate_port();

            eprintln!("creating agent '{}'...", name);
            create_container(&cname, image, port);
            docker_cp_content(&cname, &name, "/root/.vesta-name");
            inject_credentials(&cname, &credentials);

            if !docker_ok(&["start", &cname]) {
                die("failed to start container");
            }

            eprintln!("agent '{}' is ready.", name);
            eprintln!("attaching (ctrl-q to detach)...");
            docker_interactive(&["attach", "--detach-keys=ctrl-q", &cname]);
        }

        Command::Create { build, name } => {
            let name = name.map(|n| normalize_name(&n)).unwrap_or_else(prompt_name);
            validate_name(&name);
            let cname = container_name(&name);

            if container_status(&cname) != ContainerStatus::NotFound {
                die(&format!("agent '{}' already exists. destroy it first.", name));
            }

            let image = resolve_image(build);
            let port = allocate_port();

            eprintln!("creating agent '{}'...", name);
            create_container(&cname, image, port);
            docker_cp_content(&cname, &name, "/root/.vesta-name");
            eprintln!("created (run 'vesta auth {}' to authenticate, then 'vesta start {}')", name, name);
        }

        Command::Start { name } => {
            match name {
                Some(name) => {
                    validate_name(&name);
                    let cname = container_name(&name);
                    ensure_exists(&cname);
                    if container_status(&cname) == ContainerStatus::Running {
                        eprintln!("{}: already running", name);
                        return;
                    }
                    if !docker_ok(&["start", &cname]) {
                        die(&format!("failed to start '{}'", name));
                    }
                    eprintln!("{}: started", name);
                }
                None => {
                    let containers = list_managed_containers();
                    if containers.is_empty() {
                        eprintln!("no agents found. create one with: vesta setup");
                        return;
                    }
                    let mut started = 0;
                    for cname in &containers {
                        if container_status(cname) != ContainerStatus::Running {
                            if docker_ok(&["start", cname]) {
                                eprintln!("{}: started", name_from_cname(cname));
                                started += 1;
                            } else {
                                eprintln!("{}: failed to start", name_from_cname(cname));
                            }
                        }
                    }
                    if started == 0 {
                        eprintln!("all agents already running");
                    }
                }
            }
        }

        Command::Stop { name } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_exists(&cname);
            if !docker_ok(&["stop", &cname]) {
                die("failed to stop");
            }
            eprintln!("{}: stopped", name);
        }

        Command::Restart { name } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_exists(&cname);
            eprintln!("{}: restarting...", name);
            if !docker_ok(&["restart", &cname]) {
                die("failed to restart");
            }
            eprintln!("{}: restarted", name);
        }

        Command::Attach { name } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_running(&cname);
            let _ = process::Command::new("docker")
                .args([
                    "exec",
                    &cname,
                    "tail",
                    "-n",
                    "200",
                    "/root/logs/vesta.log",
                ])
                .stdout(process::Stdio::inherit())
                .stderr(process::Stdio::inherit())
                .status();
            eprintln!("\nattaching (ctrl-q to detach)...");
            docker_interactive(&["attach", "--detach-keys=ctrl-q", &cname]);
        }

        Command::Auth { name, token: credentials } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_exists(&cname);
            let image = docker_output(&["inspect", "--format", "{{.Config.Image}}", &cname])
                .unwrap_or_else(|| VESTA_IMAGE.to_string());
            let credentials = credentials.unwrap_or_else(|| obtain_credentials(&image));
            inject_credentials(&cname, &credentials);
            eprintln!("{}: authenticated", name);
        }

        Command::Logs { name } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_running(&cname);
            let status = process::Command::new("docker")
                .args([
                    "exec",
                    &cname,
                    "tail",
                    "-n",
                    "500",
                    "-f",
                    "/root/logs/vesta.log",
                ])
                .stdin(process::Stdio::inherit())
                .stdout(process::Stdio::inherit())
                .stderr(process::Stdio::inherit())
                .status()
                .unwrap_or_else(|_| die("failed to stream logs"));
            if !status.success() {
                process::exit(status.code().unwrap_or(1));
            }
        }

        Command::Shell { name } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_running(&cname);
            docker_interactive(&["exec", "-it", "--detach-keys=ctrl-q", &cname, "bash"]);
        }

        Command::Status { name, json } => {
            validate_name(&name);
            let cname = container_name(&name);
            let cs = container_status(&cname);
            let port = if cs != ContainerStatus::NotFound { get_container_port(&cname) } else { BASE_WS_PORT };
            let (status_str, id) = match cs {
                ContainerStatus::NotFound => ("not_found", None),
                _ => {
                    let id = docker_output(&["inspect", "--format", "{{.Id}}", &cname])
                        .map(|s| s.chars().take(12).collect::<String>());
                    (status_label(&cs), id)
                }
            };
            let authed = cs != ContainerStatus::NotFound && is_authenticated(&cname);
            let ready = cs == ContainerStatus::Running && is_agent_ready(&cname, port);
            let alive = cs == ContainerStatus::Running && authed;
            let friendly = friendly_status(&cs, authed, ready);
            if json {
                let s = StatusJson {
                    name: name.clone(),
                    status: status_str, id, authenticated: authed,
                    agent_ready: ready, ws_port: port,
                    alive, friendly_status: friendly,
                };
                println!("{}", serde_json::to_string(&s).unwrap());
            } else if cs == ContainerStatus::NotFound {
                println!("agent '{}' not found. run: vesta setup", name);
            } else {
                println!("name:   {}", name);
                println!("status: {}", status_str);
                if let Some(id) = &id {
                    println!("id:     {}", id);
                }
                println!("auth:   {}", if authed { "yes" } else { "no" });
                println!("port:   {}", port);
                if cs == ContainerStatus::Running {
                    println!("ready:  {}", if ready { "yes" } else { "no" });
                }
                match cs {
                    ContainerStatus::NotFound => {}
                    ContainerStatus::Stopped | ContainerStatus::Dead => {
                        eprintln!("\nhint: run 'vesta start {}' to start your agent", name);
                    }
                    ContainerStatus::Running if !authed => {
                        eprintln!("\nhint: run 'vesta auth {}' to sign in", name);
                    }
                    ContainerStatus::Running => {
                        eprintln!("\nhint: open http://localhost:{} in your browser", port);
                    }
                }
            }
        }

        Command::List { json } => {
            let containers = list_managed_containers();
            if containers.is_empty() && !json {
                println!("no agents. run: vesta setup");
            } else {
                let entries: Vec<ListEntry> = containers.iter().map(|cname| {
                    let cs = container_status(cname);
                    let port = get_container_port(cname);
                    let authed = cs != ContainerStatus::NotFound && is_authenticated(cname);
                    let ready = cs == ContainerStatus::Running && is_agent_ready(cname, port);
                    let alive = cs == ContainerStatus::Running && authed;
                    let friendly = friendly_status(&cs, authed, ready);
                    ListEntry {
                        name: name_from_cname(cname),
                        status: status_label(&cs),
                        authenticated: authed,
                        agent_ready: ready,
                        ws_port: port,
                        alive,
                        friendly_status: friendly,
                    }
                }).collect();
                if json {
                    println!("{}", serde_json::to_string(&entries).unwrap());
                } else {
                    for e in &entries {
                        let ready_str = if e.status == "running" {
                            if e.agent_ready { " (ready)" } else { " (not ready)" }
                        } else {
                            ""
                        };
                        let auth_str = if e.authenticated { "" } else { " [no auth]" };
                        println!("  {} — {}{}{}  (port {})", e.name, e.status, ready_str, auth_str, e.ws_port);
                    }
                }
            }
        }

        Command::Backup { name, output } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_exists(&cname);

            let was_running = container_status(&cname) == ContainerStatus::Running;
            if was_running {
                eprintln!("stopping agent for backup...");
                docker_ok(&["stop", &cname]);
            }

            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let backup_tag = format!("vesta-backup:{}_{}", name, ts);

            eprintln!("creating backup...");
            let commit_label = format!("LABEL vesta.agent_name={}", name);
            if !docker_ok(&["commit", "--change", &commit_label, &cname, &backup_tag]) {
                if was_running {
                    docker_ok(&["start", &cname]);
                }
                die("backup commit failed");
            }

            eprintln!("exporting to {}...", output.display());

            let mut docker_save = process::Command::new("docker")
                .args(["save", &backup_tag])
                .stdout(process::Stdio::piped())
                .stderr(process::Stdio::inherit())
                .spawn()
                .unwrap_or_else(|_| die("failed to run docker save"));

            let file = std::fs::File::create(&output)
                .unwrap_or_else(|e| die(&format!("failed to create {}: {}", output.display(), e)));

            let mut gzip = process::Command::new("gzip")
                .stdin(docker_save.stdout.take().unwrap())
                .stdout(file)
                .stderr(process::Stdio::inherit())
                .spawn()
                .unwrap_or_else(|_| die("failed to run gzip"));

            let docker_status = docker_save.wait().unwrap_or_else(|_| die("docker save failed"));
            let gzip_status = gzip.wait().unwrap_or_else(|_| die("gzip failed"));

            if !docker_status.success() || !gzip_status.success() {
                std::fs::remove_file(&output).ok();
                docker_ok(&["rmi", &backup_tag]);
                if was_running {
                    docker_ok(&["start", &cname]);
                }
                die("backup export failed");
            }

            docker_ok(&["rmi", &backup_tag]);

            if was_running {
                docker_ok(&["start", &cname]);
                eprintln!("agent restarted");
            }
            eprintln!("backup saved to {}", output.display());
        }

        Command::Restore { input, name: name_override, replace } => {
            eprintln!("loading backup from {}...", input.display());

            let file = std::fs::File::open(&input)
                .unwrap_or_else(|e| die(&format!("failed to open {}: {}", input.display(), e)));

            let mut gunzip = process::Command::new("gunzip")
                .arg("-c")
                .stdin(file)
                .stdout(process::Stdio::piped())
                .stderr(process::Stdio::inherit())
                .spawn()
                .unwrap_or_else(|_| die("failed to run gunzip"));

            let load_output = process::Command::new("docker")
                .args(["load"])
                .stdin(gunzip.stdout.take().unwrap())
                .stdout(process::Stdio::piped())
                .stderr(process::Stdio::inherit())
                .output()
                .unwrap_or_else(|_| die("failed to run docker load"));

            let gunzip_status = gunzip.wait().unwrap_or_else(|_| die("gunzip failed"));
            if !gunzip_status.success() || !load_output.status.success() {
                die("failed to load backup");
            }

            let load_stdout = String::from_utf8_lossy(&load_output.stdout);
            let loaded_image = load_stdout
                .lines()
                .find_map(|l| l.strip_prefix("Loaded image: "))
                .unwrap_or_else(|| die("could not determine loaded image from docker load output"))
                .trim()
                .to_string();

            let name_from_backup = docker_output(&[
                "inspect", "--format", "{{index .Config.Labels \"vesta.agent_name\"}}", &loaded_image,
            ]);

            let name = name_override.unwrap_or_else(|| {
                name_from_backup.clone()
                    .filter(|n| !n.is_empty() && n != "<no value>")
                    .unwrap_or_else(|| die("backup has no agent name label. use --name to specify one."))
            });
            validate_name(&name);
            let cname = container_name(&name);

            if container_status(&cname) != ContainerStatus::NotFound {
                if !replace {
                    docker_ok(&["rmi", &loaded_image]);
                    die(&format!("agent '{}' already exists. use --replace to overwrite, or --name to pick a different name.", name));
                }
                eprintln!("replacing existing agent '{}'...", name);
                docker_ok(&["rm", "-f", &cname]);
            }

            let port = allocate_port();
            create_container(&cname, &loaded_image, port);

            docker_cp_content(&cname, &name, "/root/.vesta-name");

            docker_ok(&["rmi", &loaded_image]);

            eprintln!("agent '{}' restored (port {}). run 'vesta start {}' to start it.", name, port, name);
        }

        Command::Destroy { name, yes } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_exists(&cname);
            if !yes && !confirm(&format!("destroy agent '{}' (all state lost)? [y/N] ", name)) {
                println!("aborted");
                return;
            }
            if container_status(&cname) == ContainerStatus::Running {
                docker_ok(&["stop", &cname]);
            }
            if !docker_ok(&["rm", "-f", &cname]) {
                die("failed to destroy");
            }
            eprintln!("{}: destroyed", name);
        }

        Command::PlatformCheck => {
            let s = serde_json::json!({
                "ready": true,
                "platform": "linux",
                "wsl_installed": true,
                "virtualization_enabled": true,
                "distro_registered": true,
                "distro_healthy": true,
                "services_ready": true,
                "needs_reboot": false,
                "message": ""
            });
            println!("{}", s);
        }

        Command::PlatformSetup => {
            let s = serde_json::json!({
                "ready": true,
                "platform": "linux",
                "wsl_installed": true,
                "virtualization_enabled": true,
                "distro_registered": true,
                "distro_healthy": true,
                "services_ready": true,
                "needs_reboot": false,
                "message": ""
            });
            println!("{}", s);
        }

        Command::Rebuild { name } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_exists(&cname);
            let port = get_container_port(&cname);
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let backup_tag = format!("vesta-rebuild:{}_{}", name, ts);

            eprintln!("creating backup...");
            if !docker_ok(&["commit", &cname, &backup_tag]) {
                die("backup failed");
            }

            eprintln!("destroying...");
            docker_ok(&["rm", "-f", &cname]);

            eprintln!("recreating from backup...");
            create_container(&cname, &backup_tag, port);
            docker_cp_content(&cname, &name, "/root/.vesta-name");

            if !docker_ok(&["start", &cname]) {
                die("failed to start");
            }
            docker_ok(&["rmi", &backup_tag]);
            eprintln!("{}: rebuilt and running", name);
        }

        Command::WaitReady { name, timeout } => {
            validate_name(&name);
            let cname = container_name(&name);
            ensure_running(&cname);
            let port = get_container_port(&cname);
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout);
            while std::time::Instant::now() < deadline {
                if is_agent_ready(&cname, port) {
                    eprintln!("{}: ready", name);
                    return;
                }
                std::thread::sleep(std::time::Duration::from_secs(1));
            }
            die(&format!("{}: not ready after {}s", name, timeout));
        }

        Command::Update => {
            let target = match std::env::consts::ARCH {
                "x86_64" => "x86_64-unknown-linux-gnu",
                "aarch64" => "aarch64-unknown-linux-gnu",
                other => die(&format!("unsupported architecture: {}", other)),
            };
            if let Some(tmp_dir) = cli_self_update(target, false, "vesta") {
                let _ = std::fs::remove_dir_all(&tmp_dir);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_simple() {
        assert_eq!(normalize_name("MyAgent"), "myagent");
    }

    #[test]
    fn normalize_spaces_and_underscores() {
        assert_eq!(normalize_name("My Agent_Name"), "my-agent-name");
    }

    #[test]
    fn normalize_special_chars() {
        assert_eq!(normalize_name("hello!@#world"), "helloworld");
    }

    #[test]
    fn normalize_leading_trailing_hyphens() {
        assert_eq!(normalize_name("--test--"), "test");
    }

    #[test]
    fn normalize_multiple_hyphens() {
        assert_eq!(normalize_name("a---b"), "a-b");
    }

    #[test]
    fn normalize_whitespace() {
        assert_eq!(normalize_name("  hello  "), "hello");
    }

    #[test]
    fn normalize_empty() {
        assert_eq!(normalize_name(""), "");
    }

    #[test]
    fn normalize_all_special() {
        assert_eq!(normalize_name("!!!"), "");
    }

    #[test]
    fn normalize_truncates_long_name() {
        let long = "a".repeat(50);
        let result = normalize_name(&long);
        assert_eq!(result.len(), NAME_MAX_LEN);
    }

    #[test]
    fn normalize_truncate_strips_trailing_hyphen() {
        let input = format!("{}--b", "a".repeat(31));
        let result = normalize_name(&input);
        assert!(!result.ends_with('-'));
        assert!(result.len() <= NAME_MAX_LEN);
    }

    #[test]
    fn validate_ok() {
        assert!(try_validate_name("hello").is_ok());
        assert!(try_validate_name("a").is_ok());
        assert!(try_validate_name("test-agent").is_ok());
        assert!(try_validate_name("a1").is_ok());
        assert!(try_validate_name("123").is_ok());
    }

    #[test]
    fn validate_rejects_empty() {
        assert!(try_validate_name("").is_err());
    }

    #[test]
    fn validate_rejects_uppercase() {
        assert!(try_validate_name("Hello").is_err());
    }

    #[test]
    fn validate_rejects_leading_hyphen() {
        assert!(try_validate_name("-hello").is_err());
    }

    #[test]
    fn validate_rejects_trailing_hyphen() {
        assert!(try_validate_name("hello-").is_err());
    }

    #[test]
    fn validate_rejects_too_long() {
        let long = "a".repeat(NAME_MAX_LEN + 1);
        assert!(try_validate_name(&long).is_err());
    }

    #[test]
    fn validate_rejects_special_chars() {
        assert!(try_validate_name("hello world").is_err());
        assert!(try_validate_name("hello_world").is_err());
    }

    #[test]
    fn container_name_roundtrip() {
        assert_eq!(name_from_cname(&container_name("test")), "test");
        assert_eq!(name_from_cname(&container_name("my-agent")), "my-agent");
    }

    #[test]
    fn name_from_cname_no_prefix() {
        assert_eq!(name_from_cname("random"), "random");
    }

    #[test]
    fn urlencod_basic() {
        assert_eq!(urlencod("hello world"), "hello%20world");
        assert_eq!(urlencod("https://example.com/path"), "https%3A%2F%2Fexample.com%2Fpath");
        assert_eq!(urlencod("a-b_c.d~e"), "a-b_c.d~e");
    }
}
