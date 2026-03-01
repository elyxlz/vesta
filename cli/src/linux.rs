use super::*;
use serde::Serialize;
use std::io::{self, Write};

const CONTAINER_NAME: &str = "vesta";
const VESTA_IMAGE: &str = "ghcr.io/elyxlz/vesta:latest";
const LOCAL_IMAGE_TAG: &str = "vesta:local";
const MAX_DOCKERFILE_SEARCH_DEPTH: usize = 5;
const CREDENTIALS_PATH: &str = "/root/.claude/.credentials.json";
const CLAUDE_JSON_PATH: &str = "/root/.claude.json";

#[derive(PartialEq)]
enum ContainerStatus {
    Running,
    Stopped,
    NotFound,
}

#[derive(Serialize)]
struct StatusJson {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    authenticated: bool,
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
    die("docker daemon is not running.\nstart it: sudo systemctl start docker");
}

fn container_status() -> ContainerStatus {
    match docker_output(&["inspect", "--format", "{{.State.Status}}", CONTAINER_NAME]) {
        Some(s) => match s.as_str() {
            "running" => ContainerStatus::Running,
            _ => ContainerStatus::Stopped,
        },
        None => ContainerStatus::NotFound,
    }
}

fn is_authenticated() -> bool {
    docker_quiet(&["exec", CONTAINER_NAME, "test", "-f", CREDENTIALS_PATH])
}

fn ensure_exists() {
    if container_status() == ContainerStatus::NotFound {
        die("agent not found. run: vesta setup");
    }
}

fn ensure_running() {
    ensure_exists();
    if container_status() != ContainerStatus::Running {
        die("agent is not running. run: vesta start");
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
        println!("building image from {}...", context.display());
        let status = process::Command::new("docker")
            .args(["build", "-t", LOCAL_IMAGE_TAG, "."])
            .current_dir(&context)
            .status()
            .unwrap_or_else(|e| die(&format!("docker build failed: {}", e)));
        if !status.success() {
            die("image build failed");
        }
        LOCAL_IMAGE_TAG
    } else {
        println!("pulling image...");
        if !docker_ok(&["pull", VESTA_IMAGE]) {
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

fn obtain_credentials() -> String {
    println!("authenticating claude...");
    println!("a browser window will open. sign in, then come back here.\n");

    let status = process::Command::new("claude")
        .args(["setup-token"])
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|_| die("failed to run 'claude setup-token'.\ninstall claude code: npm install -g @anthropic-ai/claude-code"));

    if !status.success() {
        die("claude setup-token failed");
    }

    let creds_path = dirs::home_dir()
        .unwrap_or_else(|| die("cannot determine home directory"))
        .join(".claude")
        .join(".credentials.json");

    std::fs::read_to_string(&creds_path)
        .unwrap_or_else(|_| die("could not read ~/.claude/.credentials.json after setup-token"))
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
        Command::Setup { build, yes } => {
            if container_status() != ContainerStatus::NotFound {
                if !yes && !confirm("agent already exists. destroy and recreate? [y/N] ") {
                    println!("aborted");
                    return;
                }
                println!("replacing existing agent...");
                docker_ok(&["rm", "-f", CONTAINER_NAME]);
            }

            let image = resolve_image(build);

            let credentials = obtain_credentials();

            println!("creating agent...");
            create_container(image);
            inject_credentials(CONTAINER_NAME, &credentials);

            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start container");
            }

            println!("agent is ready.");
            println!("attaching (ctrl-q to detach)...");
            docker_interactive(&["attach", "--detach-keys=ctrl-q", CONTAINER_NAME]);
        }

        Command::Create { build } => {
            if container_status() != ContainerStatus::NotFound {
                die("agent already exists. run: vesta destroy first");
            }

            let image = resolve_image(build);

            println!("creating agent...");
            create_container(image);
            println!("created (run 'vesta auth' to authenticate, then 'vesta start')");
        }

        Command::Start => {
            ensure_exists();
            if container_status() == ContainerStatus::Running {
                println!("already running");
                return;
            }
            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start");
            }
            println!("started");
        }

        Command::Stop => {
            ensure_exists();
            if !docker_ok(&["stop", CONTAINER_NAME]) {
                die("failed to stop");
            }
            println!("stopped");
        }

        Command::Restart => {
            ensure_exists();
            println!("restarting...");
            if !docker_ok(&["restart", CONTAINER_NAME]) {
                die("failed to restart");
            }
            println!("restarted");
        }

        Command::Attach => {
            ensure_running();
            let _ = process::Command::new("docker")
                .args([
                    "exec",
                    CONTAINER_NAME,
                    "tail",
                    "-n",
                    "50",
                    "/root/logs/vesta.log",
                ])
                .stdout(process::Stdio::inherit())
                .stderr(process::Stdio::null())
                .status();
            println!("\nattaching (ctrl-q to detach)...");
            docker_interactive(&["attach", "--detach-keys=ctrl-q", CONTAINER_NAME]);
        }

        Command::Auth { token: credentials } => {
            ensure_exists();
            let credentials = credentials.unwrap_or_else(|| obtain_credentials());
            inject_credentials(CONTAINER_NAME, &credentials);
            if container_status() == ContainerStatus::Running {
                docker_ok(&["restart", CONTAINER_NAME]);
            } else if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start container");
            }
            println!("authenticated");
        }

        Command::Logs => {
            ensure_running();
            let status = process::Command::new("docker")
                .args([
                    "exec",
                    CONTAINER_NAME,
                    "tail",
                    "-n",
                    "100",
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
            let (status_str, id, running) = match docker_output(&[
                "inspect", "--format", "{{.State.Status}} {{.Id}}", CONTAINER_NAME,
            ]) {
                Some(raw) => {
                    let mut parts = raw.splitn(2, ' ');
                    let s = parts.next().unwrap_or("");
                    let id = parts.next().unwrap_or("").chars().take(12).collect::<String>();
                    let running = s == "running";
                    let label = if running { "running" } else { "stopped" };
                    (label, Some(id), running)
                }
                None => ("not_found", None, false),
            };
            let authed = running && is_authenticated();
            if json {
                let s = StatusJson { status: status_str, id, authenticated: authed };
                println!("{}", serde_json::to_string(&s).unwrap());
            } else if status_str == "not_found" {
                println!("no agent. run: vesta setup");
            } else {
                println!("status: {}", status_str);
                if let Some(id) = &id {
                    println!("id:     {}", id);
                }
                println!("auth:   {}", if authed { "yes" } else { "no" });
            }
        }

        Command::Backup => {
            ensure_exists();
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let tag = format!("vesta-backup:{}", ts);
            println!("creating backup...");
            if !docker_ok(&["commit", CONTAINER_NAME, &tag]) {
                die("backup failed");
            }
            println!("backup created: {}", tag);
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
            println!("destroyed");
        }

        Command::Rebuild => {
            ensure_exists();
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let backup_tag = format!("vesta-rebuild:{}", ts);

            println!("creating backup...");
            if !docker_ok(&["commit", CONTAINER_NAME, &backup_tag]) {
                die("backup failed");
            }

            println!("destroying...");
            docker_ok(&["rm", "-f", CONTAINER_NAME]);

            println!("recreating from backup...");
            create_container(&backup_tag);

            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start");
            }
            println!("rebuilt and running");
        }
    }
}
