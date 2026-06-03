use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::sync::{LazyLock, Mutex, MutexGuard};

use vesta_tests::{SERVER, TestAgent, docker_cmd, exec_in_container};

type SharedAgent = Option<(TestAgent<'static>, String)>;

/// Shared live agent: ONE real first-start for the whole live suite. First-start is by far
/// the most expensive part of every live test (a multi-minute real-Claude setup conversation),
/// and the tests only need an agent that is awake, settled, and processing notifications.
/// Tests lock this agent and run serially against it, isolating themselves with unique
/// file paths.
///
/// Like SHARED_RO_AGENT in the server suite, the static never drops; the container is cleaned
/// up on the next run (TestAgent::create destroys leftovers by name).
static SHARED_LIVE_AGENT: LazyLock<Mutex<SharedAgent>> = LazyLock::new(|| Mutex::new(setup_shared_live_agent()));

/// Lock the shared live agent for the duration of a test. Returns None (test skips) when
/// Claude credentials are unavailable. Holding the guard serializes tests: notifications,
/// and especially interrupts, are global to the agent's conversation, so concurrent tests
/// would corrupt each other.
pub fn lock_shared_live_agent() -> Option<(MutexGuard<'static, SharedAgent>, String)> {
    let guard = SHARED_LIVE_AGENT.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let container = guard.as_ref()?.1.clone();
    Some((guard, container))
}

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

/// Generous bound on a full first-start conversation with real Claude before the agent
/// first goes idle. First-start is several minutes; this only has to not be hit in practice.
const FIRST_START_SETTLE_TIMEOUT: Duration = Duration::from_secs(600);
const READY_MARKER: &str = "/root/agent/e2e-test/ready.txt";

/// Block until the agent has fully finished first-start and is idle, using the product's own
/// idle signal rather than a timer.
///
/// `wait_until_alive` only waits for `mark_setup_done` (step 6 of ~14), after which the agent
/// keeps going (greeting, timezone, channel setup, a self-restart at the end). The monitor
/// loop holds PASSIVE notifications until it observes `event_bus.state == "idle"`, so a passive
/// task is processed only once the agent is genuinely done and ready for test traffic. We drop
/// one passive "write a marker file" task and wait for the file: its appearance IS the agent
/// reporting itself idle.
fn wait_for_first_start_settled(container: &str) -> Result<(), String> {
    write_notification(
        container,
        &format!("Create the file \"{READY_MARKER}\" containing only the word: READY"),
        false, // passive: the monitor loop delivers this only once the agent is idle
    )?;
    wait_for_file_contains(container, READY_MARKER, "READY", FIRST_START_SETTLE_TIMEOUT).map(|_| ())
}

fn setup_shared_live_agent() -> Option<(TestAgent<'static>, String)> {
    let Some(credentials_path) = host_credentials_path() else {
        eprintln!("skipping live e2e: ~/.claude/.credentials.json not found");
        return None;
    };

    let credentials = fs::read_to_string(&credentials_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", credentials_path.display()));

    // Follow the real user creation path: build the image, then discover
    // the container via the API (not by hardcoding the naming convention).
    let client = Box::leak(Box::new(SERVER.client()));
    let agent = TestAgent::create(client, "test-e2e-shared").unwrap();

    let status = client.agent_status(&agent.name).unwrap();
    let container = status.id.unwrap_or_else(|| panic!("agent {} has no container id", agent.name));

    wait_for_container_running(&container, Duration::from_secs(60)).expect("container running");

    // Use sonnet for e2e tests — cheaper and faster than the default opus
    exec_in_container(&container, "echo 'export AGENT_MODEL=sonnet' >> ~/.bashrc")
        .expect("set AGENT_MODEL=sonnet");

    exec_in_container(&container, &format!("mkdir -p {E2E_FILES_DIR}")).expect("create e2e dir");
    exec_in_container(
        &container,
        &format!("cat > {MEMORY_PATH} <<'EOF'\n{TEST_MEMORY}\nEOF"),
    )
    .expect("write test memory");

    client.inject_token(&agent.name, &credentials).expect("inject real credentials");
    // Always restart after injection so the agent boots with BOTH the credentials and
    // the AGENT_MODEL=sonnet override from ~/.bashrc. Without the restart, the
    // already-running agent picks up the credentials but keeps the default (opus)
    // model for the whole first-start conversation.
    client.restart_agent(&agent.name).expect("restart agent to apply model + credentials");
    client.wait_until_alive(&agent.name, 600).expect("wait until alive");

    // First-start keeps going after the agent reports alive; wait (via the agent's own idle
    // signal) until it has fully settled before any test sends notifications.
    wait_for_first_start_settled(&container).expect("agent settled after first-start");
    Some((agent, container))
}
