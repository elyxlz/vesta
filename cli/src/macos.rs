use super::*;
use serde::Serialize;
use std::io::{self, Write};
use std::path::PathBuf;

const VFKIT_BIN: &str = "vfkit";
const VM_CPUS: u32 = 2;
const VM_MEMORY_MIB: u32 = 4096;
const VM_MAC: &str = "52:54:00:fe:57:a1";

#[derive(Serialize)]
struct StatusJson {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    authenticated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    name: Option<String>,
}

fn data_dir() -> PathBuf {
    dirs::data_dir()
        .unwrap_or_else(|| die("cannot determine data directory"))
        .join("vesta")
}

fn find_vfkit() -> PathBuf {
    let exe = std::env::current_exe().unwrap_or_else(|_| die("cannot determine executable path"));
    let exe_dir = exe
        .parent()
        .unwrap_or_else(|| die("cannot determine executable directory"));

    let candidates = [
        exe_dir.join(VFKIT_BIN),
        exe_dir.join("binaries").join(VFKIT_BIN),
        // Tauri .app bundle: Contents/MacOS/ (exe) -> Contents/Resources/ (resources)
        exe_dir.join("..").join("Resources").join(VFKIT_BIN),
    ];

    for c in &candidates {
        if c.exists() {
            return c.clone();
        }
    }

    die("vfkit not found next to vesta binary. reinstall vesta or download vfkit from https://github.com/crc-org/vfkit/releases");
}

fn ssh_key_path() -> PathBuf {
    data_dir().join("ssh_key")
}

fn pid_path() -> PathBuf {
    data_dir().join("vfkit.pid")
}

fn vm_ip_path() -> PathBuf {
    data_dir().join("vm_ip")
}

fn vm_disk_path() -> PathBuf {
    data_dir().join("vm-disk.raw")
}

fn vm_kernel_path() -> PathBuf {
    data_dir().join("vm-kernel")
}

fn vm_initrd_path() -> PathBuf {
    data_dir().join("vm-initrd")
}

fn vm_image_ready() -> bool {
    vm_disk_path().exists() && vm_kernel_path().exists() && vm_initrd_path().exists()
}

fn generate_ssh_key() {
    let key_path = ssh_key_path();
    if key_path.exists() {
        return;
    }
    std::fs::create_dir_all(key_path.parent().unwrap()).ok();
    let status = process::Command::new("ssh-keygen")
        .args([
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            key_path.to_str().unwrap(),
            "-q",
        ])
        .status()
        .unwrap_or_else(|_| die("failed to run ssh-keygen"));
    if !status.success() {
        die("ssh-keygen failed");
    }
}

fn read_pid() -> Option<u32> {
    let content = std::fs::read_to_string(pid_path()).ok()?;
    content.trim().parse().ok()
}

fn vm_running() -> bool {
    match read_pid() {
        Some(pid) => {
            process::Command::new("kill")
                .args(["-0", &pid.to_string()])
                .stdout(process::Stdio::null())
                .stderr(process::Stdio::null())
                .status()
                .map(|s| s.success())
                .unwrap_or(false)
        }
        None => false,
    }
}

fn discover_vm_ip_from_leases() -> Option<String> {
    let content = std::fs::read_to_string("/var/db/dhcpd_leases").ok()?;
    let mac_lower = VM_MAC.to_lowercase();

    let mut ip = None;
    let mut current_ip = None;

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("ip_address=") {
            current_ip = trimmed.strip_prefix("ip_address=").map(|s| s.to_string());
        }
        if trimmed.starts_with("hw_address=") {
            if let Some(hw) = trimmed.strip_prefix("hw_address=") {
                let hw_mac = hw.split(',').nth(1).unwrap_or("").to_lowercase();
                if hw_mac == mac_lower {
                    ip = current_ip.clone();
                }
            }
        }
    }

    ip
}

fn discover_vm_ip_from_arp() -> Option<String> {
    let output = process::Command::new("arp")
        .arg("-an")
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;

    let text = String::from_utf8_lossy(&output.stdout);
    let mac_lower = VM_MAC.to_lowercase();

    // arp -an output: ? (192.168.64.5) at 52:54:00:fe:57:a1 on bridge100 ...
    for line in text.lines() {
        if line.to_lowercase().contains(&mac_lower) {
            let start = line.find('(')? + 1;
            let end = line.find(')')?;
            return Some(line[start..end].to_string());
        }
    }
    None
}

fn discover_vm_ip() -> Option<String> {
    discover_vm_ip_from_leases().or_else(discover_vm_ip_from_arp)
}

fn get_vm_ip() -> String {
    if let Ok(ip) = std::fs::read_to_string(vm_ip_path()) {
        let ip = ip.trim().to_string();
        if !ip.is_empty() {
            return ip;
        }
    }
    if let Some(ip) = discover_vm_ip() {
        std::fs::write(vm_ip_path(), &ip).ok();
        return ip;
    }
    die("cannot determine VM IP address. try: vesta stop && vesta start");
}

fn resolve_vm_ip() -> Option<String> {
    std::fs::read_to_string(vm_ip_path())
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .or_else(discover_vm_ip)
}

fn ssh_reachable(ip: &str) -> bool {
    process::Command::new("ssh")
        .args([
            "-i",
            ssh_key_path().to_str().unwrap(),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ConnectTimeout=2",
            "-o",
            "BatchMode=yes",
            &format!("root@{}", ip),
            "true",
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn ssh_available() -> bool {
    match resolve_vm_ip() {
        Some(ip) => ssh_reachable(&ip),
        None => false,
    }
}

fn boot_vm() {
    if vm_running() {
        return;
    }

    stop_vm();

    if !vm_image_ready() {
        die("VM image not found. run: vesta setup");
    }

    let vfkit = find_vfkit();
    let disk = vm_disk_path();
    let kernel = vm_kernel_path();
    let initrd = vm_initrd_path();
    let pubkey_dir = data_dir().join("ssh-mount");

    std::fs::create_dir_all(&pubkey_dir).ok();
    let pubkey_content = std::fs::read_to_string(ssh_key_path().with_extension("pub"))
        .unwrap_or_else(|_| die("cannot read SSH public key"));
    std::fs::write(pubkey_dir.join("authorized_keys"), &pubkey_content).ok();

    let child = process::Command::new(&vfkit)
        .args([
            &format!("--cpus={}", VM_CPUS),
            &format!("--memory={}", VM_MEMORY_MIB),
            "--bootloader",
            &format!(
                "linux,kernel={},initrd={},cmdline=root=/dev/vda rw console=hvc0",
                kernel.display(),
                initrd.display()
            ),
            "--device",
            &format!("virtio-blk,path={}", disk.display()),
            "--device",
            &format!("virtio-net,nat,mac={}", VM_MAC),
            "--device",
            "virtio-rng",
            "--device",
            &format!(
                "virtio-fs,sharedDir={},mountTag=ssh-keys",
                pubkey_dir.display()
            ),
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn()
        .unwrap_or_else(|e| die(&format!("failed to start vfkit: {}", e)));

    std::fs::write(pid_path(), child.id().to_string()).ok();
}

fn wait_for_ssh_ok() -> bool {
    print!("waiting for VM...");
    io::stdout().flush().ok();
    for i in 0..60 {
        if let Some(ip) = if i > 3 { discover_vm_ip() } else { resolve_vm_ip() } {
            std::fs::write(vm_ip_path(), &ip).ok();
            if ssh_reachable(&ip) {
                println!(" ready");
                return true;
            }
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        print!(".");
        io::stdout().flush().ok();
    }
    println!();
    false
}

fn wait_for_ssh() {
    if !wait_for_ssh_ok() {
        die("VM did not become reachable via SSH within 60s");
    }
}

fn stop_vm() {
    if let Some(pid) = read_pid() {
        let _ = process::Command::new("kill")
            .args([&pid.to_string()])
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
    }
    // Kill any orphaned vfkit processes (e.g. from a crash)
    let _ = process::Command::new("pkill")
        .arg("vfkit")
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
    std::fs::remove_file(pid_path()).ok();
    std::fs::remove_file(vm_ip_path()).ok();
}

fn clean_vm_image() {
    std::fs::remove_file(vm_disk_path()).ok();
    std::fs::remove_file(vm_kernel_path()).ok();
    std::fs::remove_file(vm_initrd_path()).ok();
}

fn ensure_vm() {
    if !vm_image_ready() {
        download_vm_image();
    }
    generate_ssh_key();
    if !vm_running() {
        boot_vm();
        wait_for_ssh();
    } else if !ssh_available() {
        wait_for_ssh();
    }
}

fn ssh_base_args() -> Vec<String> {
    let ip = get_vm_ip();
    vec![
        "-i".into(),
        ssh_key_path().to_str().unwrap().to_string(),
        "-o".into(),
        "StrictHostKeyChecking=no".into(),
        "-o".into(),
        "UserKnownHostsFile=/dev/null".into(),
        "-o".into(),
        "LogLevel=ERROR".into(),
        format!("root@{}", ip),
    ]
}

fn ssh_exec(cmd_args: &[&str]) -> process::ExitStatus {
    let mut args = ssh_base_args();
    args.extend(cmd_args.iter().map(|s| s.to_string()));
    process::Command::new("ssh")
        .args(&args)
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|_| die("ssh failed"))
}

fn ssh_exec_tty(cmd_args: &[&str]) -> process::ExitStatus {
    let mut args = vec!["-t".to_string()];
    args.extend(ssh_base_args());
    args.extend(cmd_args.iter().map(|s| s.to_string()));
    process::Command::new("ssh")
        .args(&args)
        .stdin(process::Stdio::inherit())
        .stdout(process::Stdio::inherit())
        .stderr(process::Stdio::inherit())
        .status()
        .unwrap_or_else(|_| die("ssh failed"))
}

fn download_vm_image() {
    let dir = data_dir();
    std::fs::create_dir_all(&dir).ok();

    let arch = if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        "amd64"
    };

    let repo = "elyxlz/vesta";
    let asset = format!("vesta-vm-{}.tar.gz", arch);
    let tmp_path = dir.join(format!("{}.tmp", &asset));

    println!("downloading VM image ({})...", arch);

    let status = process::Command::new("curl")
        .args([
            "-fsSL",
            "-o",
            tmp_path.to_str().unwrap(),
            &format!(
                "https://github.com/{}/releases/latest/download/{}",
                repo, asset
            ),
        ])
        .status()
        .unwrap_or_else(|_| die("failed to download VM image"));

    if !status.success() {
        std::fs::remove_file(&tmp_path).ok();
        die("failed to download VM image. check your internet connection.");
    }

    println!("extracting VM image...");
    let status = process::Command::new("tar")
        .args(["-xzf", tmp_path.to_str().unwrap(), "-C", dir.to_str().unwrap()])
        .status()
        .unwrap_or_else(|_| die("failed to extract VM image"));

    std::fs::remove_file(&tmp_path).ok();

    if !status.success() {
        die("failed to extract VM image");
    }
}

pub fn run(command: Command) {
    match command {
        Command::Setup { build, .. } => {
            if !vm_image_ready() {
                download_vm_image();
            }
            generate_ssh_key();
            boot_vm();

            if !wait_for_ssh_ok() {
                println!("VM failed to start. re-downloading image...");
                stop_vm();
                clean_vm_image();
                download_vm_image();
                boot_vm();
                wait_for_ssh();
            }

            let pubkey = std::fs::read_to_string(ssh_key_path().with_extension("pub"))
                .unwrap_or_else(|_| die("cannot read SSH public key"));
            ssh_exec(&[
                "sh",
                "-c",
                &format!(
                    "mkdir -p /root/.ssh && printf '%s\\n' '{}' > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys",
                    pubkey.trim()
                ),
            ]);

            let mut args = vec!["vesta", "setup", "-y"];
            if build {
                args.push("--build");
            }
            ssh_exec_tty(&args);
        }

        Command::Attach => {
            ensure_vm();
            ssh_exec_tty(&["vesta", "attach"]);
        }

        Command::Auth { token } => {
            ensure_vm();
            match token {
                Some(t) => { ssh_exec(&["vesta", "auth", "--token", &t]); }
                None => { ssh_exec_tty(&["vesta", "auth"]); }
            }
        }

        Command::Shell => {
            ensure_vm();
            ssh_exec_tty(&["vesta", "shell"]);
        }

        Command::Logs => {
            ensure_vm();
            ssh_exec(&["vesta", "logs"]);
        }

        Command::Status { json } => {
            if !vm_running() {
                if json {
                    let s = StatusJson {
                        status: "not_found",
                        id: None,
                        authenticated: false,
                        name: None,
                    };
                    println!("{}", serde_json::to_string(&s).unwrap());
                } else {
                    println!("no agent. run: vesta setup");
                }
                return;
            }
            if json {
                ssh_exec(&["vesta", "status", "--json"]);
            } else {
                ssh_exec(&["vesta", "status"]);
            }
        }

        Command::Start => {
            ensure_vm();
            ssh_exec(&["vesta", "start"]);
        }

        Command::Stop => {
            ensure_vm();
            ssh_exec(&["vesta", "stop"]);
        }

        Command::Restart => {
            ensure_vm();
            ssh_exec(&["vesta", "restart"]);
        }

        Command::Create { build, name } => {
            ensure_vm();
            let mut args = vec!["vesta", "create"];
            if build { args.push("--build"); }
            if let Some(ref n) = name { args.push("--name"); args.push(n); }
            ssh_exec(&args);
        }

        Command::Backup => {
            ensure_vm();
            ssh_exec(&["vesta", "backup"]);
        }

        Command::Destroy { yes } => {
            ensure_vm();
            if yes {
                ssh_exec(&["vesta", "destroy", "--yes"]);
            } else {
                ssh_exec_tty(&["vesta", "destroy"]);
            }
        }

        Command::Rebuild => {
            ensure_vm();
            ssh_exec_tty(&["vesta", "rebuild"]);
        }
    }
}
