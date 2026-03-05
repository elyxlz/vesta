use super::*;
use serde::Serialize;
use std::io::{self, BufRead, Write};

const CONTAINER_NAME: &str = "vesta";
const VESTA_IMAGE: &str = "ghcr.io/elyxlz/vesta:latest";
const LOCAL_IMAGE_TAG: &str = "vesta:local";
const MAX_DOCKERFILE_SEARCH_DEPTH: usize = 5;
const CREDENTIALS_PATH: &str = "/root/.claude/.credentials.json";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";
const AGENT_WS_PORT: u16 = 7865;

#[derive(PartialEq)]
enum ContainerStatus {
    Running,
    Stopped,
    NotFound,
    Dead,
}

#[derive(Serialize)]
struct StatusJson {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    authenticated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    agent_ready: bool,
    ws_port: u16,
}

fn docker(args: &[&str]) -> process::ExitStatus {
    process::Command::new("docker")
        .args(args)
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

fn container_status() -> ContainerStatus {
    match docker_output(&["inspect", "--format", "{{.State.Status}}", CONTAINER_NAME]) {
        Some(s) => match s.as_str() {
            "running" | "restarting" | "paused" => ContainerStatus::Running,
            "exited" | "created" => ContainerStatus::Stopped,
            "dead" | "removing" => ContainerStatus::Dead,
            _ => ContainerStatus::Stopped,
        },
        None => ContainerStatus::NotFound,
    }
}

fn container_file_exists(container_path: &str) -> bool {
    let src = format!("{}:{}", CONTAINER_NAME, container_path);
    docker_quiet(&["cp", &src, "-"])
}

fn read_container_file(container_path: &str) -> Option<String> {
    let tmp = std::env::temp_dir().join(format!("vesta_read_{}", std::process::id()));
    let src = format!("{}:{}", CONTAINER_NAME, container_path);
    if !docker_quiet(&["cp", &src, tmp.to_str().unwrap()]) {
        return None;
    }
    let content = std::fs::read_to_string(&tmp).ok();
    std::fs::remove_file(&tmp).ok();
    content.map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

fn is_authenticated() -> bool {
    container_file_exists(CREDENTIALS_PATH)
}

fn is_agent_ready() -> bool {
    docker_quiet(&[
        "exec", CONTAINER_NAME, "bash", "-c",
        &format!("echo > /dev/tcp/localhost/{}", AGENT_WS_PORT),
    ])
}

fn ensure_exists() {
    match container_status() {
        ContainerStatus::NotFound => die("agent not found. create one first with: vesta setup"),
        ContainerStatus::Dead => die("agent is in a broken state. run: vesta destroy --yes && vesta setup"),
        _ => {}
    }
}

fn ensure_running() {
    ensure_exists();
    if container_status() != ContainerStatus::Running {
        die("agent is not running");
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
            .stderr(process::Stdio::null())
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

fn create_container(image: &str) {
    let args = vec![
        "create", "--name", CONTAINER_NAME, "-it", "--privileged",
        "--restart", "unless-stopped", "--network", "host", image,
    ];
    if !docker_ok(&args) {
        die("failed to create container");
    }
}

fn try_open_browser(url: &str) {
    let _ = process::Command::new("xdg-open").arg(url)
        .stdout(process::Stdio::null()).stderr(process::Stdio::null()).spawn();
}

fn obtain_credentials(image: &str) -> String {
    eprintln!("authenticating claude...");
    eprintln!("sign in via the link below, then come back here.\n");

    let tmp_dir = std::env::temp_dir().join(format!("vesta_auth_{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir)
        .unwrap_or_else(|e| die(&format!("failed to create temp dir: {}", e)));

    let mount = format!("{}:/tmp/claude-creds", tmp_dir.display());
    let mut child = process::Command::new("docker")
        .args([
            "run", "--rm",
            "-v", &mount,
            "--entrypoint", "sh",
            image,
            "-c", "claude setup-token && cp /root/.claude/.credentials.json /tmp/claude-creds/",
        ])
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::piped())
        .spawn()
        .unwrap_or_else(|_| die("failed to run claude setup-token"));

    let opened = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let pass_through = |reader: Box<dyn io::Read + Send>, mut writer: Box<dyn io::Write + Send>, opened: std::sync::Arc<std::sync::atomic::AtomicBool>| {
        std::thread::spawn(move || {
            let reader = io::BufReader::new(reader);
            for line in reader.lines() {
                let Ok(line) = line else { break };
                let _ = writeln!(writer, "{}", line);
                if !opened.load(std::sync::atomic::Ordering::Relaxed) {
                    if let Some(url) = line.split_whitespace().find(|w| w.starts_with("https://")) {
                        opened.store(true, std::sync::atomic::Ordering::Relaxed);
                        try_open_browser(url);
                    }
                }
            }
        })
    };

    let stdout_thread = pass_through(
        Box::new(child.stdout.take().unwrap()),
        Box::new(io::stdout()),
        opened.clone(),
    );
    let stderr_thread = pass_through(
        Box::new(child.stderr.take().unwrap()),
        Box::new(io::stderr()),
        opened,
    );

    let status = child.wait()
        .unwrap_or_else(|_| die("failed to run claude setup-token"));
    let _ = stdout_thread.join();
    let _ = stderr_thread.join();

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
    let target = format!("{}:/root/.claude", container);
    let ok = docker_ok(&["cp", tmp_dir.to_str().unwrap(), &target]);
    std::fs::remove_dir_all(&tmp_dir).ok();
    if !ok {
        die("failed to copy credentials to container");
    }
    docker_cp_content(container, "{\"hasCompletedOnboarding\":true}", CLAUDE_JSON_PATH);
}

pub fn run(command: Command) {
    ensure_docker();

    match command {
        Command::Setup { build, yes, name } => {
            if container_status() != ContainerStatus::NotFound {
                if !yes && !confirm("agent already exists. destroy and recreate? [y/N] ") {
                    println!("aborted");
                    return;
                }
                eprintln!("replacing existing agent...");
                docker_ok(&["rm", "-f", CONTAINER_NAME]);
            }

            let image = resolve_image(build);
            let credentials = obtain_credentials(image);

            eprintln!("creating agent...");
            create_container(image);
            if let Some(n) = name {
                docker_cp_content(CONTAINER_NAME, &n, "/root/.vesta-name");
            }
            inject_credentials(CONTAINER_NAME, &credentials);

            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start container");
            }

            eprintln!("agent is ready.");
            eprintln!("attaching (ctrl-q to detach)...");
            docker_interactive(&["attach", "--detach-keys=ctrl-q", CONTAINER_NAME]);
        }

        Command::Create { build, name } => {
            if container_status() != ContainerStatus::NotFound {
                die("agent already exists. destroy it first.");
            }

            let image = resolve_image(build);

            eprintln!("creating agent...");
            create_container(image);
            if let Some(n) = name {
                docker_cp_content(CONTAINER_NAME, &n, "/root/.vesta-name");
            }
            eprintln!("created (run 'vesta auth' to authenticate, then 'vesta start')");
        }

        Command::Start => {
            ensure_exists();
            if container_status() == ContainerStatus::Running {
                eprintln!("already running");
                return;
            }
            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start");
            }
            eprintln!("started");
        }

        Command::Stop => {
            ensure_exists();
            if !docker_ok(&["stop", CONTAINER_NAME]) {
                die("failed to stop");
            }
            eprintln!("stopped");
        }

        Command::Restart => {
            ensure_exists();
            eprintln!("restarting...");
            if !docker_ok(&["restart", CONTAINER_NAME]) {
                die("failed to restart");
            }
            eprintln!("restarted");
        }

        Command::Attach => {
            ensure_running();
            let _ = process::Command::new("docker")
                .args([
                    "exec",
                    CONTAINER_NAME,
                    "tail",
                    "-n",
                    "200",
                    "/root/logs/vesta.log",
                ])
                .stdout(process::Stdio::inherit())
                .stderr(process::Stdio::null())
                .status();
            eprintln!("\nattaching (ctrl-q to detach)...");
            docker_interactive(&["attach", "--detach-keys=ctrl-q", CONTAINER_NAME]);
        }

        Command::Auth { token: credentials } => {
            ensure_exists();
            let image = docker_output(&["inspect", "--format", "{{.Config.Image}}", CONTAINER_NAME])
                .unwrap_or_else(|| VESTA_IMAGE.to_string());
            let credentials = credentials.unwrap_or_else(|| obtain_credentials(&image));
            inject_credentials(CONTAINER_NAME, &credentials);
            eprintln!("authenticated");
        }

        Command::Logs => {
            ensure_running();
            let status = process::Command::new("docker")
                .args([
                    "exec",
                    CONTAINER_NAME,
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

        Command::Shell => {
            ensure_running();
            docker_interactive(&["exec", "-it", "--detach-keys=ctrl-q", CONTAINER_NAME, "bash"]);
        }

        Command::Status { json } => {
            let cs = container_status();
            let (status_str, id) = match cs {
                ContainerStatus::NotFound => ("not_found", None),
                _ => {
                    let id = docker_output(&["inspect", "--format", "{{.Id}}", CONTAINER_NAME])
                        .map(|s| s.chars().take(12).collect::<String>());
                    let label = match cs {
                        ContainerStatus::Running => "running",
                        ContainerStatus::Dead => "dead",
                        _ => "stopped",
                    };
                    (label, id)
                }
            };
            let authed = cs != ContainerStatus::NotFound && is_authenticated();
            let name = if cs != ContainerStatus::NotFound {
                read_container_file("/root/.vesta-name")
            } else {
                None
            };
            let ready = cs == ContainerStatus::Running && is_agent_ready();
            if json {
                let s = StatusJson {
                    status: status_str, id, authenticated: authed, name,
                    agent_ready: ready, ws_port: AGENT_WS_PORT,
                };
                println!("{}", serde_json::to_string(&s).unwrap());
            } else if cs == ContainerStatus::NotFound {
                println!("no agent. run: vesta setup");
            } else {
                println!("status: {}", status_str);
                if let Some(id) = &id {
                    println!("id:     {}", id);
                }
                if let Some(name) = &name {
                    println!("name:   {}", name);
                }
                println!("auth:   {}", if authed { "yes" } else { "no" });
                if cs == ContainerStatus::Running {
                    println!("ready:  {}", if ready { "yes" } else { "no" });
                }
            }
        }

        Command::Backup => {
            ensure_exists();
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let tag = format!("vesta-backup:{}", ts);
            eprintln!("creating backup...");
            if !docker_ok(&["commit", CONTAINER_NAME, &tag]) {
                die("backup failed");
            }
            eprintln!("backup created: {}", tag);
        }

        Command::Destroy { yes } => {
            ensure_exists();
            if !yes && !confirm("destroy agent (all state lost)? [y/N] ") {
                println!("aborted");
                return;
            }
            if !docker_ok(&["rm", "-f", CONTAINER_NAME]) {
                die("failed to destroy");
            }
            eprintln!("destroyed");
        }

        Command::Name { name } => {
            ensure_exists();
            docker_cp_content(CONTAINER_NAME, &name, "/root/.vesta-name");
            eprintln!("name set: {}", name);
        }

        Command::Rebuild => {
            ensure_exists();
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let backup_tag = format!("vesta-rebuild:{}", ts);

            eprintln!("creating backup...");
            if !docker_ok(&["commit", CONTAINER_NAME, &backup_tag]) {
                die("backup failed");
            }

            eprintln!("destroying...");
            docker_ok(&["rm", "-f", CONTAINER_NAME]);

            eprintln!("recreating from backup...");
            create_container(&backup_tag);

            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start");
            }
            eprintln!("rebuilt and running");
        }
    }
}
