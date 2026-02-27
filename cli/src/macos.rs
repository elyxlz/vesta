use super::*;
use serde::Serialize;
use std::io::{self, Write};
use std::path::PathBuf;

const VFKIT_BIN: &str = "vfkit";
const AGENT_PORT: u16 = 7865;
const VM_CPUS: u32 = 2;
const VM_MEMORY_MIB: u32 = 4096;
const VM_MAC: &str = "52:54:00:ve:57:a1";

#[derive(Serialize)]
struct StatusJson {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
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

fn discover_vm_ip() -> Option<String> {
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
                // Format is "1,xx:xx:xx:xx:xx:xx"
                let hw_mac = hw.split(',').nth(1).unwrap_or("").to_lowercase();
                if hw_mac == mac_lower {
                    ip = current_ip.clone();
                }
            }
        }
    }

    ip
}

fn get_vm_ip() -> String {
    if let Some(ip) = std::fs::read_to_string(vm_ip_path()).ok() {
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

fn ssh_available() -> bool {
    let ip = match discover_vm_ip().or_else(|| std::fs::read_to_string(vm_ip_path()).ok().map(|s| s.trim().to_string())) {
        Some(ip) if !ip.is_empty() => ip,
        _ => return false,
    };

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

fn boot_vm() {
    if vm_running() {
        return;
    }

    if pid_path().exists() {
        std::fs::remove_file(pid_path()).ok();
    }
    std::fs::remove_file(vm_ip_path()).ok();

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

fn wait_for_ssh() {
    print!("waiting for VM...");
    io::stdout().flush().ok();
    for i in 0..60 {
        // VM needs time to get DHCP lease, check after a few seconds
        if i > 3 {
            if let Some(ip) = discover_vm_ip() {
                std::fs::write(vm_ip_path(), &ip).ok();
            }
        }
        if ssh_available() {
            println!(" ready");
            return;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        print!(".");
        io::stdout().flush().ok();
    }
    println!();
    die("VM did not become reachable via SSH within 60s");
}

fn start_port_tunnel() {
    let ip = get_vm_ip();
    process::Command::new("ssh")
        .args([
            "-fNT",
            "-i",
            ssh_key_path().to_str().unwrap(),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            &format!("{}:localhost:{}", AGENT_PORT, AGENT_PORT),
            &format!("root@{}", ip),
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .ok();
}

fn ensure_vm() {
    if !vm_running() {
        boot_vm();
        wait_for_ssh();
        start_port_tunnel();
    } else if !ssh_available() {
        wait_for_ssh();
        start_port_tunnel();
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

fn stop_vm() {
    if let Some(pid) = read_pid() {
        process::Command::new("kill")
            .arg(pid.to_string())
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status()
            .ok();

        for _ in 0..10 {
            if !vm_running() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_secs(1));
        }

        if vm_running() {
            process::Command::new("kill")
                .args(["-9", &pid.to_string()])
                .stdout(process::Stdio::null())
                .stderr(process::Stdio::null())
                .status()
                .ok();
        }
    }
    std::fs::remove_file(pid_path()).ok();
    std::fs::remove_file(vm_ip_path()).ok();
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

    println!("downloading VM image ({})...", arch);

    let status = process::Command::new("curl")
        .args([
            "-fsSL",
            "-o",
            dir.join(&asset).to_str().unwrap(),
            &format!(
                "https://github.com/{}/releases/latest/download/{}",
                repo, asset
            ),
        ])
        .status()
        .unwrap_or_else(|_| die("failed to download VM image"));

    if !status.success() {
        die("failed to download VM image. check your internet connection.");
    }

    println!("extracting VM image...");
    let status = process::Command::new("tar")
        .args(["-xzf", dir.join(&asset).to_str().unwrap(), "-C", dir.to_str().unwrap()])
        .status()
        .unwrap_or_else(|_| die("failed to extract VM image"));

    if !status.success() {
        die("failed to extract VM image");
    }

    std::fs::remove_file(dir.join(&asset)).ok();
}

pub async fn run(command: Command) {
    match command {
        Command::Setup { build } => {
            if !vm_image_ready() {
                download_vm_image();
            }
            generate_ssh_key();
            boot_vm();
            wait_for_ssh();

            let pubkey = std::fs::read_to_string(ssh_key_path().with_extension("pub"))
                .unwrap_or_else(|_| die("cannot read SSH public key"));
            ssh_exec(&[
                "sh",
                "-c",
                &format!(
                    "mkdir -p /root/.ssh && echo '{}' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys",
                    pubkey.trim()
                ),
            ]);

            start_port_tunnel();

            if build {
                ssh_exec_tty(&["vesta", "setup", "--build"]);
            } else {
                ssh_exec_tty(&["vesta", "setup"]);
            }
        }

        Command::Attach => {
            ensure_vm();
            ssh_exec_tty(&["vesta", "attach"]);
        }

        Command::Auth => {
            ensure_vm();
            ssh_exec_tty(&["vesta", "auth"]);
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

        Command::Create { build } => {
            ensure_vm();
            if build {
                ssh_exec(&["vesta", "create", "--build"]);
            } else {
                ssh_exec(&["vesta", "create"]);
            }
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
