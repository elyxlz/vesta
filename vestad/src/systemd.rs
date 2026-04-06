use std::process::{self, Command};

const SERVICE_NAME: &str = "vestad";
const SERVICE_STARTUP_WAIT_MS: u64 = 2000;
const SERVICE_POLL_INTERVAL_MS: u64 = 100;

fn unit_file_path() -> Result<String, String> {
    let home = std::env::var("HOME").map_err(|_| "HOME not set".to_string())?;
    Ok(format!("{}/.config/systemd/user/vestad.service", home))
}

pub fn reinstall_service() -> Result<(), String> {
    std::fs::remove_file(&unit_file_path()?).ok();
    ensure_service_installed()
}

pub fn ensure_service_installed() -> Result<(), String> {
    let vestad_path = std::env::current_exe()
        .map_err(|e| format!("cannot determine binary path: {}", e))?
        .to_str()
        .ok_or("binary path is not valid UTF-8")?
        .to_string();

    let unit_path = unit_file_path()?;

    if let Ok(existing) = std::fs::read_to_string(&unit_path) {
        if existing.contains(&vestad_path) {
            return Ok(());
        }
        eprintln!("updating systemd service (binary path changed)...");
    } else {
        eprintln!("installing systemd user service...");
    }

    if let Some(parent) = std::path::Path::new(&unit_path).parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("failed to create {}: {}", parent.display(), e))?;
    }

    let unit_content = format!(
        r#"[Unit]
Description=Vesta API Server
After=docker.service

[Service]
ExecStart={vestad_path} serve --standalone
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"#
    );

    std::fs::write(&unit_path, unit_content)
        .map_err(|e| format!("failed to write systemd service: {}", e))?;

    run_systemctl(&["daemon-reload"])?;
    run_systemctl(&["enable", SERVICE_NAME])?;

    let user = std::env::var("USER").map_err(|_| "USER not set".to_string())?;
    let status = Command::new("loginctl")
        .args(["enable-linger", &user])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map_err(|e| format!("failed to run loginctl: {}", e))?;
    if !status.success() {
        eprintln!("warning: loginctl enable-linger failed — vestad may stop on logout");
    }

    Ok(())
}

pub fn is_active() -> bool {
    Command::new("systemctl")
        .args(["--user", "is-active", SERVICE_NAME])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

pub fn start() -> Result<(), String> {
    run_systemctl(&["start", SERVICE_NAME])
}

pub fn stop() -> Result<(), String> {
    run_systemctl(&["stop", SERVICE_NAME])
}

pub fn restart() -> Result<(), String> {
    run_systemctl(&["restart", SERVICE_NAME])
}

pub fn wait_for_start() -> Result<(), String> {
    let deadline = std::time::Instant::now()
        + std::time::Duration::from_millis(SERVICE_STARTUP_WAIT_MS);

    while std::time::Instant::now() < deadline {
        if is_active() {
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_millis(SERVICE_POLL_INTERVAL_MS));
    }

    if is_active() {
        Ok(())
    } else {
        Err("vestad failed to start — run 'vestad logs' for details".into())
    }
}

pub fn print_status() {
    let _ = Command::new("systemctl")
        .args(["--user", "status", SERVICE_NAME, "--no-pager"])
        .stdin(process::Stdio::null())
        .status();
}

pub fn exec_journal(lines: usize, follow: bool) -> ! {
    use std::os::unix::process::CommandExt;

    let lines_str = lines.to_string();
    let mut cmd = Command::new("journalctl");
    cmd.args(["--user", "-u", SERVICE_NAME, "-n", &lines_str, "--no-hostname", "-o", "cat"]);
    if follow {
        cmd.arg("-f");
    }

    let err = cmd.exec();
    eprintln!("failed to exec journalctl: {}", err);
    process::exit(1);
}

pub fn main_pid() -> Option<u32> {
    let output = Command::new("systemctl")
        .args(["--user", "show", SERVICE_NAME, "--property=MainPID", "--value"])
        .output()
        .ok()?;
    let pid_str = String::from_utf8_lossy(&output.stdout);
    let pid: u32 = pid_str.trim().parse().ok()?;
    if pid == 0 { None } else { Some(pid) }
}

fn run_systemctl(args: &[&str]) -> Result<(), String> {
    let mut full_args = vec!["--user"];
    full_args.extend_from_slice(args);

    let output = Command::new("systemctl")
        .args(&full_args)
        .stdout(process::Stdio::null())
        .output()
        .map_err(|e| format!("failed to run systemctl: {}", e))?;

    if output.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr.trim();
        if detail.is_empty() {
            Err(format!(
                "systemctl {} failed (exit {})",
                args.join(" "),
                output.status.code().unwrap_or(-1)
            ))
        } else {
            Err(format!(
                "systemctl {} failed: {}",
                args.join(" "),
                detail
            ))
        }
    }
}
