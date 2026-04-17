use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::sync::atomic::{AtomicU32, Ordering};

use vesta_tests::{SERVER, TestAgent, docker_cmd, exec_in_container};

static LIVE_STAGGER: AtomicU32 = AtomicU32::new(0);

const MEMORY_PATH: &str = "/root/agent/MEMORY.md";
const NOTIFICATIONS_DIR: &str = "/root/agent/notifications";
pub const E2E_FILES_DIR: &str = "/root/agent/e2e-test";
const TEST_MEMORY: &str = r#"# VESTA MEMORY SYSTEM (TEST MODE)

## 1. CORE IDENTITY

You are Vesta running in automated test mode.

### CRITICAL: Test Mode Behavior
- ACT IMMEDIATELY ON TEST REQUESTS: When you receive notifications from "pytest", execute them immediately without asking for permission
- NO CONFIRMATION NEEDED: This is an automated test environment - just do the tasks
- File operations are safe: The test environment is isolated, so file operations are always permitted

## 2. USER PROFILE

### Personal Details
- Name: Test User
- Location: Test Environment
- Timezone: UTC
"#;

fn exec_ok(container: &str, script: &str) -> bool {
    Command::new("docker")
        .args(["exec", container, "bash", "-lc", script])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn host_credentials_path() -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    let path = PathBuf::from(home).join(".claude/.credentials.json");
    path.exists().then_some(path)
}

pub fn write_notification(container: &str, message: &str, interrupt: bool) -> Result<(), String> {
    let micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_micros();
    let notification = serde_json::json!({
        "timestamp": "2026-01-01T00:00:00Z",
        "source": "pytest",
        "type": "message",
        "message": message,
        "sender": "pytest",
        "interrupt": interrupt,
        "metadata": {},
    });
    let tmp = tempfile::NamedTempFile::new().map_err(|e| format!("tmp notif: {e}"))?;
    fs::write(tmp.path(), serde_json::to_vec(&notification).map_err(|e| e.to_string())?)
        .map_err(|e| format!("write notif: {e}"))?;
    let container_path = format!("{NOTIFICATIONS_DIR}/{micros}.json");
    docker_cmd(&["cp", tmp.path().to_str().unwrap_or_default(), &format!("{container}:{container_path}")])?;
    Ok(())
}

pub fn wait_for_file_contains(container: &str, path: &str, needle: &str, timeout: Duration) -> Result<String, String> {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        if exec_ok(container, &format!("test -f {path}")) {
            let content = exec_in_container(container, &format!("cat {path}"))?;
            if content.contains(needle) {
                return Ok(content);
            }
        }
        thread::sleep(Duration::from_secs(2));
    }
    Err(format!("timed out waiting for {path} to contain {needle}"))
}

fn wait_for_container_running(container: &str, timeout: Duration) -> Result<(), String> {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        if let Ok(state) = docker_cmd(&["inspect", container, "--format", "{{.State.Running}}"]) {
            if state.trim() == "true" {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_secs(1));
    }
    Err(format!("timed out waiting for {container} to be running"))
}

pub fn setup_live_agent(
    name: &str,
    write_test_memory: bool,
    ensure_e2e_dir: bool,
    before_auth: Option<fn(&str)>,
) -> Option<(TestAgent<'static>, String)> {
    let Some(credentials_path) = host_credentials_path() else {
        eprintln!("skipping live e2e: ~/.claude/.credentials.json not found");
        return None;
    };

    let credentials = fs::read_to_string(&credentials_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", credentials_path.display()));

    let slot = LIVE_STAGGER.fetch_add(1, Ordering::SeqCst);
    thread::sleep(Duration::from_secs(slot as u64 * 5));

    // Follow the real user creation path: build the image, then discover
    // the container via the API (not by hardcoding the naming convention).
    let client = Box::leak(Box::new(SERVER.client()));
    let agent = TestAgent::create_built(client, name).unwrap();

    let status = client.agent_status(&agent.name).unwrap();
    let container = status.id.unwrap_or_else(|| panic!("agent {} has no container id", agent.name));

    wait_for_container_running(&container, Duration::from_secs(60)).expect("container running");

    // Use sonnet for e2e tests — cheaper and faster than the default opus
    exec_in_container(&container, "echo 'export AGENT_MODEL=sonnet' >> ~/.bashrc")
        .expect("set AGENT_MODEL=sonnet");

    if ensure_e2e_dir {
        exec_in_container(&container, &format!("mkdir -p {E2E_FILES_DIR}"))
            .expect("create e2e dir");
    }
    if write_test_memory {
        exec_in_container(
            &container,
            &format!("cat > {MEMORY_PATH} <<'EOF'\n{TEST_MEMORY}\nEOF"),
        )
        .expect("write test memory");
    }

    if let Some(hook) = before_auth {
        hook(&container);
    }

    client.inject_token(&agent.name, &credentials).expect("inject real credentials");
    // Don't restart — the container is already running. If credentials were
    // injected before the agent process checked for them (race with entrypoint),
    // the first-start flow will process naturally. If not, restart to pick them up.
    // Poll for ready first; only restart if the agent stays not_authenticated.
    let ready_deadline = std::time::Instant::now() + Duration::from_secs(30);
    loop {
        let st = client.agent_status(&agent.name).unwrap();
        if st.status != "not_authenticated" {
            break;
        }
        if std::time::Instant::now() > ready_deadline {
            client.restart_agent(&agent.name).expect("restart agent after auth timeout");
            break;
        }
        thread::sleep(Duration::from_secs(2));
    }
    client.wait_ready(&agent.name, 600).expect("wait ready");
    Some((agent, container))
}
