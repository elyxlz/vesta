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
}

#[derive(Serialize)]
struct ListEntry {
    name: String,
    status: &'static str,
    authenticated: bool,
    agent_ready: bool,
    ws_port: u16,
}

fn container_name(name: &str) -> String {
    format!("vesta-{}", name)
}

fn validate_name(name: &str) {
    if name.is_empty() || name.len() > NAME_MAX_LEN {
        die(&format!("agent name must be 1-{} characters", NAME_MAX_LEN));
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
        die("agent name must match [a-z0-9][a-z0-9-]*[a-z0-9] (lowercase, digits, hyphens; must start/end with alphanumeric)");
    }
}

fn prompt_name() -> String {
    eprint!("agent name: ");
    io::stderr().flush().ok();
    let mut input = String::new();
    io::stdin().read_line(&mut input).ok();
    let name = input.trim().to_string();
    if name.is_empty() {
        die("agent name is required");
    }
    validate_name(&name);
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

fn container_file_exists(cname: &str, container_path: &str) -> bool {
    let src = format!("{}:{}", cname, container_path);
    docker_quiet(&["cp", &src, "-"])
}

fn read_container_file(cname: &str, container_path: &str) -> Option<String> {
    let tmp = std::env::temp_dir().join(format!("vesta_read_{}", std::process::id()));
    let src = format!("{}:{}", cname, container_path);
    if !docker_quiet(&["cp", &src, tmp.to_str().unwrap()]) {
        return None;
    }
    let content = std::fs::read_to_string(&tmp).ok();
    std::fs::remove_file(&tmp).ok();
    content.map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

fn is_authenticated(cname: &str) -> bool {
    container_file_exists(cname, CREDENTIALS_PATH)
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

fn obtain_credentials(image: &str) -> String {
    eprintln!("authenticating claude...");
    eprintln!("sign in via the link below, then come back here.\n");

    let tmp_dir = std::env::temp_dir().join(format!("vesta_auth_{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir)
        .unwrap_or_else(|e| die(&format!("failed to create temp dir: {}", e)));

    let mount = format!("{}:/tmp/claude-creds", tmp_dir.display());
    let child = process::Command::new("docker")
        .args([
            "run", "--rm",
            "-v", &mount,
            "--entrypoint", "sh",
            image,
            "-c", "export PATH=/root/.local/bin:$PATH && claude setup-token && cp /root/.claude/.credentials.json /tmp/claude-creds/",
        ])
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::piped())
        .spawn()
        .unwrap_or_else(|_| die("failed to run claude setup-token"));

    let status = run_passthrough(child);

    if !status.success() {
        std::fs::remove_dir_all(&tmp_dir).ok();
        die("claude setup-token failed");
    }

    let creds = std::fs::read_to_string(tmp_dir.join(".credentials.json"))
        .unwrap_or_else(|_| {
            std::fs::remove_dir_all(&tmp_dir).ok();
            die("could not read credentials after setup-token")
        });
    std::fs::remove_dir_all(&tmp_dir).ok();
    creds
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

    eprintln!("migrating legacy container 'vesta'...");

    let was_running = container_status("vesta") == ContainerStatus::Running;

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

pub fn run(command: Command) {
    ensure_docker();
    maybe_migrate_legacy();

    match command {
        Command::Setup { build, yes, name } => {
            let name = name.unwrap_or_else(prompt_name);
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
            let name = name.unwrap_or_else(prompt_name);
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
            if json {
                let s = StatusJson {
                    name: name.clone(),
                    status: status_str, id, authenticated: authed,
                    agent_ready: ready, ws_port: port,
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
                    ListEntry {
                        name: name_from_cname(cname),
                        status: status_label(&cs),
                        authenticated: authed,
                        agent_ready: ready,
                        ws_port: port,
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
    }
}
