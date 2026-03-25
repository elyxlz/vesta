use crate::ServerConfig;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process;

const VFKIT_BIN: &str = "vfkit";
const VM_CPUS: u32 = 2;
const VM_MEMORY_MIB: u32 = 8192;
const VM_MAC: &str = "52:54:00:fe:57:a1";
const VSOCK_PORT: u32 = 2222;
const LAUNCH_AGENT_LABEL: &str = "com.vesta.autostart";

fn data_dir() -> Result<PathBuf, String> {
    Ok(dirs::data_dir()
        .ok_or("cannot determine data directory")?
        .join("vesta"))
}

fn find_vfkit() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|_| "cannot determine executable path".to_string())?;
    let exe_dir = exe
        .parent()
        .ok_or("cannot determine executable directory")?;
    let candidates = [
        exe_dir.join(VFKIT_BIN),
        exe_dir.join("binaries").join(VFKIT_BIN),
        exe_dir.join("..").join("Resources").join(VFKIT_BIN),
        exe_dir
            .join("..")
            .join("Resources")
            .join("resources")
            .join(VFKIT_BIN),
    ];
    for c in &candidates {
        if c.exists() {
            return Ok(c.clone());
        }
    }
    Err("vfkit not found next to vesta binary".into())
}

fn ssh_key_path() -> Result<PathBuf, String> {
    Ok(data_dir()?.join("ssh_key"))
}

fn pid_path() -> Result<PathBuf, String> {
    Ok(data_dir()?.join("vfkit.pid"))
}

fn vsock_socket_path() -> PathBuf {
    std::env::temp_dir().join("vesta-vsock.sock")
}

fn vm_disk_path() -> Result<PathBuf, String> {
    Ok(data_dir()?.join("vm-disk.raw"))
}

fn vm_kernel_path() -> Result<PathBuf, String> {
    Ok(data_dir()?.join("vm-kernel"))
}

fn vm_initrd_path() -> Result<PathBuf, String> {
    Ok(data_dir()?.join("vm-initrd"))
}

fn launch_agent_path() -> Result<PathBuf, String> {
    Ok(dirs::home_dir()
        .ok_or("cannot determine home directory")?
        .join("Library")
        .join("LaunchAgents")
        .join(format!("{}.plist", LAUNCH_AGENT_LABEL)))
}

fn vm_image_ready() -> bool {
    let Ok(disk) = vm_disk_path() else { return false };
    let Ok(kernel) = vm_kernel_path() else { return false };
    let Ok(initrd) = vm_initrd_path() else { return false };
    disk.exists() && kernel.exists() && initrd.exists()
}

fn generate_ssh_key() -> Result<(), String> {
    let key_path = ssh_key_path()?;
    if key_path.exists() {
        return Ok(());
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
        .map_err(|_| "failed to run ssh-keygen".to_string())?;
    if !status.success() {
        return Err("ssh-keygen failed".into());
    }
    Ok(())
}

fn read_pid() -> Option<u32> {
    let content = std::fs::read_to_string(pid_path().ok()?).ok()?;
    content.trim().parse().ok()
}

fn vm_running() -> bool {
    match read_pid() {
        Some(pid) => process::Command::new("kill")
            .args(["-0", &pid.to_string()])
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false),
        None => false,
    }
}

fn ssh_base_args() -> Result<Vec<String>, String> {
    let socket = vsock_socket_path();
    Ok(vec![
        "-i".into(),
        ssh_key_path()?.to_str().unwrap().to_string(),
        "-o".into(),
        "StrictHostKeyChecking=no".into(),
        "-o".into(),
        "UserKnownHostsFile=/dev/null".into(),
        "-o".into(),
        "LogLevel=ERROR".into(),
        "-o".into(),
        format!("ProxyCommand=nc -U '{}'", socket.display()),
        "root@localhost".into(),
    ])
}

fn ssh_reachable() -> bool {
    if !vsock_socket_path().exists() {
        return false;
    }
    let Ok(mut args) = ssh_base_args() else { return false };
    args.extend([
        "-o".into(),
        "ConnectTimeout=2".into(),
        "-o".into(),
        "BatchMode=yes".into(),
        "true".into(),
    ]);
    process::Command::new("ssh")
        .args(&args)
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn clean_stale_state() {
    if let Some(pid) = read_pid() {
        let _ = process::Command::new("kill")
            .arg(pid.to_string())
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
    }
    if let Ok(p) = pid_path() {
        std::fs::remove_file(p).ok();
    }
    std::fs::remove_file(vsock_socket_path()).ok();
}

fn boot_vm() -> Result<(), String> {
    if vm_running() {
        return Ok(());
    }

    clean_stale_state();

    if !vm_image_ready() {
        return Err("VM image not found. try reinstalling vesta.".into());
    }

    let vfkit = find_vfkit()?;
    let disk = vm_disk_path()?;
    let kernel = vm_kernel_path()?;
    let initrd = vm_initrd_path()?;
    let pubkey_dir = data_dir()?.join("ssh-mount");
    let vsock_sock = vsock_socket_path();

    std::fs::remove_file(&vsock_sock).ok();
    std::fs::create_dir_all(&pubkey_dir).ok();
    let pubkey_content = std::fs::read_to_string(ssh_key_path()?.with_extension("pub"))
        .map_err(|_| "cannot read SSH public key".to_string())?;
    std::fs::write(pubkey_dir.join("authorized_keys"), pubkey_content).ok();

    #[allow(clippy::zombie_processes)]
    let child = process::Command::new(&vfkit)
        .args([
            &format!("--cpus={}", VM_CPUS),
            &format!("--memory={}", VM_MEMORY_MIB),
            "--bootloader",
            &format!(
                "linux,kernel={},initrd={},cmdline=root=/dev/vda rootfstype=ext4 rw console=hvc0 init=/entrypoint.sh",
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
            "--device",
            &format!(
                "virtio-vsock,port={},socketURL={},connect",
                VSOCK_PORT,
                vsock_sock.display()
            ),
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to start vfkit: {}", e))?;

    let pid_p = pid_path()?;
    std::fs::write(pid_p, child.id().to_string()).ok();
    Ok(())
}

fn wait_for_ssh_ok() -> bool {
    print!("waiting for VM...");
    io::stdout().flush().ok();
    for _ in 0..60 {
        if ssh_reachable() {
            println!(" ready");
            return true;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        print!(".");
        io::stdout().flush().ok();
    }
    println!();
    false
}

fn wait_for_ssh() -> Result<(), String> {
    if !wait_for_ssh_ok() {
        return Err("VM did not become reachable within 60s".into());
    }
    Ok(())
}

fn stop_vm() {
    let pid = read_pid();
    if let Ok(mut args) = ssh_base_args() {
        args.extend([
            "-o".into(),
            "ConnectTimeout=2".into(),
            "-o".into(),
            "BatchMode=yes".into(),
            "sh".into(),
            "-c".into(),
            "sync && poweroff".into(),
        ]);
        let _ = process::Command::new("ssh")
            .args(&args)
            .stdin(process::Stdio::null())
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
    }

    if let Some(pid) = pid {
        let pid_str = pid.to_string();
        for _ in 0..20 {
            let alive = process::Command::new("kill")
                .args(["-0", &pid_str])
                .stdout(process::Stdio::null())
                .stderr(process::Stdio::null())
                .status()
                .map(|s| s.success())
                .unwrap_or(false);
            if !alive {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
        let _ = process::Command::new("kill")
            .arg(&pid_str)
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
    }

    if let Ok(p) = pid_path() {
        std::fs::remove_file(p).ok();
    }
    std::fs::remove_file(vsock_socket_path()).ok();
}

fn clean_vm_image() {
    if let Ok(p) = vm_disk_path() { std::fs::remove_file(p).ok(); }
    if let Ok(p) = vm_kernel_path() { std::fs::remove_file(p).ok(); }
    if let Ok(p) = vm_initrd_path() { std::fs::remove_file(p).ok(); }
}

fn download_vm_image() -> Result<(), String> {
    let dir = data_dir()?;
    std::fs::create_dir_all(&dir).ok();

    let arch = if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        "amd64"
    };

    let repo = "elyxlz/vesta";
    let asset = format!("vesta-vm-{}.tar.zst", arch);
    let tmp_path = dir.join(format!("{}.tmp", &asset));

    eprintln!("downloading VM image ({})...", arch);

    let output = process::Command::new("curl")
        .args([
            "-fSL",
            "-o",
            tmp_path.to_str().unwrap(),
            &format!(
                "https://github.com/{}/releases/latest/download/{}",
                repo, asset
            ),
        ])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::piped())
        .output()
        .map_err(|_| "failed to download VM image".to_string())?;

    if !output.status.success() {
        std::fs::remove_file(&tmp_path).ok();
        return Err("failed to download VM image".into());
    }

    eprintln!("extracting VM image...");
    let zst_file =
        std::fs::File::open(&tmp_path).map_err(|_| "failed to open downloaded image".to_string())?;
    let decoder =
        zstd::Decoder::new(zst_file).map_err(|_| "failed to decompress VM image".to_string())?;
    let mut archive = tar::Archive::new(decoder);
    if archive.unpack(&dir).is_err() {
        std::fs::remove_file(&tmp_path).ok();
        clean_vm_image();
        return Err("failed to extract VM image".into());
    }

    std::fs::remove_file(&tmp_path).ok();
    Ok(())
}

fn ssh_run_output(cmd_args: &[&str]) -> Option<String> {
    let mut args = ssh_base_args().ok()?;
    args.extend(["-o".into(), "ConnectTimeout=5".into(), "-o".into(), "BatchMode=yes".into()]);
    args.extend(cmd_args.iter().map(|s| s.to_string()));
    let output = process::Command::new("ssh")
        .args(&args)
        .stdout(process::Stdio::piped())
        .stderr(process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn ensure_vm() -> Result<(), String> {
    if !vm_image_ready() {
        download_vm_image()?;
    }
    generate_ssh_key()?;
    if !vm_running() {
        boot_vm()?;
        wait_for_ssh()?;
    } else if !ssh_reachable() {
        wait_for_ssh()?;
    }
    Ok(())
}

// --- Public API ---

pub fn boot() -> Result<(), String> {
    ensure_vm()
}

pub fn shutdown() {
    stop_vm();
}

pub fn install_autostart() -> Result<(), String> {
    let exe = std::env::current_exe()
        .map_err(|_| "cannot determine executable path".to_string())?;

    let plist_path = launch_agent_path()?;
    let log_dir = plist_path
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("Logs");

    let plist_content = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
        <string>boot</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/vesta-autostart.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/vesta-autostart.log</string>
</dict>
</plist>
"#,
        label = LAUNCH_AGENT_LABEL,
        exe = exe.display(),
        log_dir = log_dir.display(),
    );

    std::fs::write(&plist_path, plist_content)
        .map_err(|e| format!("failed to write LaunchAgent plist: {}", e))?;

    let _ = process::Command::new("launchctl")
        .args(["load", &plist_path.to_string_lossy()])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .status();
    Ok(())
}

pub fn remove_autostart() {
    if let Ok(plist_path) = launch_agent_path() {
        let _ = process::Command::new("launchctl")
            .args(["unload", &plist_path.to_string_lossy()])
            .stdout(process::Stdio::null())
            .stderr(process::Stdio::null())
            .status();
        std::fs::remove_file(&plist_path).ok();
    }
}

pub fn server_url() -> String {
    if vm_running() && ssh_reachable() {
        if let Some(ip) = ssh_run_output(&["hostname", "-I"]) {
            let ip = ip.split_whitespace().next().unwrap_or("localhost");
            return format!("https://{}:{}", ip, crate::DEFAULT_API_PORT);
        }
    }
    crate::default_server_url()
}

pub fn extract_credentials() -> Option<ServerConfig> {
    ensure_vm().ok()?;
    let api_key = ssh_run_output(&["cat", "/root/.config/vesta/api-key"])?;
    let fingerprint = ssh_run_output(&["cat", "/root/.config/vesta/tls/fingerprint"]);
    let cert_pem = ssh_run_output(&["cat", "/root/.config/vesta/tls/cert.pem"]);

    if api_key.trim().is_empty() {
        return None;
    }

    Some(ServerConfig {
        url: server_url(),
        api_key: api_key.trim().to_string(),
        cert_fingerprint: fingerprint.map(|s| s.trim().to_string()),
        cert_pem,
    })
}

pub fn setup(_name: Option<&str>, _build: bool, _yes: bool) -> Result<(), String> {
    if !vm_image_ready() {
        download_vm_image()?;
    }
    generate_ssh_key()?;
    boot_vm()?;

    if !wait_for_ssh_ok() {
        println!("VM failed to start. re-downloading image...");
        stop_vm();
        clean_vm_image();
        download_vm_image()?;
        boot_vm()?;
        wait_for_ssh()?;
    }
    Ok(())
}
