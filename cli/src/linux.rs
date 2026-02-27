use super::*;
use serde::Serialize;
use std::io::{self, Write};

const CONTAINER_NAME: &str = "vesta";
const VESTA_IMAGE: &str = "ghcr.io/elyxlz/vesta:latest";
const LOCAL_IMAGE_TAG: &str = "vesta:local";
const AGENT_PORT: u16 = 7865;

#[derive(Serialize)]
struct StatusJson {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
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

fn ensure_docker() {
    if !docker_quiet(&["--version"]) {
        die("docker is not installed.\ninstall: https://docs.docker.com/get-docker/");
    }
    if !docker_quiet(&["info"]) {
        die("docker daemon is not running.\nstart it: sudo systemctl start docker");
    }
}

fn container_status() -> &'static str {
    match docker_output(&["inspect", "--format", "{{.State.Status}}", CONTAINER_NAME]) {
        Some(s) => match s.as_str() {
            "running" => "running",
            "exited" | "created" | "dead" | "paused" => "stopped",
            _ => "unknown",
        },
        None => "not_found",
    }
}

fn container_id() -> Option<String> {
    docker_output(&["inspect", "--format", "{{.Id}}", CONTAINER_NAME])
        .map(|id| id.chars().take(12).collect())
}

fn ensure_exists() {
    if container_status() == "not_found" {
        die("agent not found. run: vesta setup");
    }
}

fn ensure_running() {
    ensure_exists();
    if container_status() != "running" {
        die("agent is not running. run: vesta start");
    }
}

fn find_dockerfile() -> std::path::PathBuf {
    let exe =
        std::env::current_exe().unwrap_or_else(|_| die("cannot determine executable path"));
    let mut dir = exe.parent().map(std::path::Path::to_path_buf);
    while let Some(d) = dir {
        if d.join("Dockerfile").exists() {
            return d;
        }
        dir = d.parent().map(std::path::Path::to_path_buf);
    }
    let cwd =
        std::env::current_dir().unwrap_or_else(|_| die("cannot determine working directory"));
    if cwd.join("Dockerfile").exists() {
        return cwd;
    }
    die("Dockerfile not found. run vesta setup --build from the repo root.");
}

fn copy_auth_from_container(container: &str) -> Option<std::path::PathBuf> {
    let tmp = std::env::temp_dir().join("vesta-auth-backup");
    std::fs::create_dir_all(&tmp).ok()?;

    let creds = tmp.join("credentials.json");
    let claude_json = tmp.join("claude.json");

    let ok1 = docker_quiet(&[
        "cp",
        &format!("{}:/root/.claude/.credentials.json", container),
        creds.to_str().unwrap(),
    ]);
    let ok2 = docker_quiet(&[
        "cp",
        &format!("{}:/root/.claude.json", container),
        claude_json.to_str().unwrap(),
    ]);

    if ok1 || ok2 {
        Some(tmp)
    } else {
        std::fs::remove_dir_all(&tmp).ok();
        None
    }
}

fn restore_auth_to_container(container: &str, auth_dir: &std::path::Path) {
    let creds = auth_dir.join("credentials.json");
    let claude_json = auth_dir.join("claude.json");

    if creds.exists() {
        let claude_dir = auth_dir.join(".claude");
        std::fs::create_dir_all(&claude_dir).ok();
        std::fs::rename(&creds, claude_dir.join(".credentials.json")).ok();
        docker_quiet(&[
            "cp",
            claude_dir.to_str().unwrap(),
            &format!("{}:/root/.claude", container),
        ]);
    }
    if claude_json.exists() {
        docker_quiet(&[
            "cp",
            claude_json.to_str().unwrap(),
            &format!("{}:/root/.claude.json", container),
        ]);
    }

    std::fs::remove_dir_all(auth_dir).ok();
}

fn docker_exec(args: &[&str]) {
    let status = process::Command::new("docker")
        .args(args)
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|e| die(&format!("docker exec failed: {}", e)));
    if !status.success() {
        process::exit(status.code().unwrap_or(1));
    }
}

pub fn run(command: Command) {
    ensure_docker();

    match command {
        Command::Setup { build } => {
            let mut saved_auth = if container_status() != "not_found" {
                eprint!("agent already exists. destroy and recreate? [y/N] ");
                io::stdout().flush().ok();
                let mut confirm = String::new();
                io::stdin().read_line(&mut confirm).ok();
                if confirm.trim() != "y" {
                    println!("aborted");
                    return;
                }
                println!("saving auth...");
                let auth = copy_auth_from_container(CONTAINER_NAME);
                docker_ok(&["rm", "-f", CONTAINER_NAME]);
                auth
            } else {
                None
            };

            let image = if build {
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
            };

            println!("creating agent...");
            if !docker_ok(&[
                "create",
                "--name",
                CONTAINER_NAME,
                "-it",
                "--privileged",
                "-p",
                &format!("{}:{}", AGENT_PORT, AGENT_PORT),
                "--restart",
                "unless-stopped",
                image,
            ]) {
                die("failed to create container");
            }

            if saved_auth.is_none() {
                println!("authenticating claude (copy the url and open in your browser)...");
                let auth_container = "vesta-auth";
                docker_quiet(&["rm", "-f", auth_container]);
                docker_exec(&["run", "-it", "--name", auth_container, "--entrypoint", "claude", image]);
                let fresh_auth = copy_auth_from_container(auth_container);
                docker_quiet(&["rm", "-f", auth_container]);
                if fresh_auth.is_none() {
                    die("auth failed — no credentials found");
                }
                saved_auth = fresh_auth;
            }

            if let Some(auth_dir) = saved_auth {
                println!("restoring auth...");
                restore_auth_to_container(CONTAINER_NAME, &auth_dir);
            }

            println!("starting...");
            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start container");
            }

            println!("attaching (ctrl-q to detach)...");
            docker_exec(&["attach", "--detach-keys=ctrl-q", CONTAINER_NAME]);
        }

        Command::Create { build } => {
            if container_status() != "not_found" {
                die("agent already exists. run: vesta destroy first");
            }

            let image = if build {
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
            };

            println!("creating agent...");
            if !docker_ok(&[
                "create",
                "--name",
                CONTAINER_NAME,
                "-it",
                "--privileged",
                "-p",
                &format!("{}:{}", AGENT_PORT, AGENT_PORT),
                "--restart",
                "unless-stopped",
                image,
            ]) {
                die("failed to create container");
            }
            println!("created");
        }

        Command::Start => {
            ensure_exists();
            if container_status() == "running" {
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
            docker_exec(&["attach", "--detach-keys=ctrl-q", CONTAINER_NAME]);
        }

        Command::Auth => {
            ensure_running();
            println!("authenticating claude (copy the url and open in your browser)...");
            docker_exec(&["exec", "-it", CONTAINER_NAME, "claude"]);
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
            docker_exec(&["exec", "-it", "--detach-keys=ctrl-q", CONTAINER_NAME, "bash"]);
        }

        Command::Status { json } => {
            let status = container_status();
            if json {
                let s = StatusJson {
                    status,
                    id: container_id(),
                };
                println!("{}", serde_json::to_string(&s).unwrap());
            } else if status == "not_found" {
                println!("no agent. run: vesta setup");
            } else {
                println!("status: {}", status);
                if let Some(id) = container_id() {
                    println!("id:     {}", id);
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
            println!("creating backup...");
            if !docker_ok(&["commit", CONTAINER_NAME, &tag]) {
                die("backup failed");
            }
            println!("backup created: {}", tag);
        }

        Command::Destroy { yes } => {
            ensure_exists();
            if !yes {
                eprint!("destroy agent (all state lost)? [y/N] ");
                io::stdout().flush().ok();
                let mut confirm = String::new();
                io::stdin().read_line(&mut confirm).ok();
                if confirm.trim() != "y" {
                    println!("aborted");
                    return;
                }
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
            if !docker_ok(&[
                "create",
                "--name",
                CONTAINER_NAME,
                "-it",
                "--privileged",
                "-p",
                &format!("{}:{}", AGENT_PORT, AGENT_PORT),
                "--restart",
                "unless-stopped",
                &backup_tag,
            ]) {
                die("failed to recreate");
            }

            if !docker_ok(&["start", CONTAINER_NAME]) {
                die("failed to start");
            }
            println!("rebuilt and running");
        }
    }
}
