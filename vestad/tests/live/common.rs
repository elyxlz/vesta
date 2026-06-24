use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::sync::{LazyLock, Mutex, MutexGuard};

use vesta_tests::{SERVER, TestAgent, docker_cmd, dump_agent_diagnostics, exec_in_container};

type SharedAgent = Option<(TestAgent<'static>, String)>;

/// The live suite runs against a POOL of two shared agents rather than one, so independent tests
/// run in parallel. Each agent pays its own one-time first-start (the expensive multi-minute
/// real-Claude setup), but the two first-starts run concurrently, so the pool's setup wall-clock
/// stays ~= a single first-start while the test bodies overlap.
///
/// Tests are partitioned by agent and must NOT mix pools mid-test: notifications and interrupts
/// are global to an agent's conversation, so two tests sharing one agent would corrupt each
/// other. Each pool's Mutex serializes its own tests. The dreamer (which restarts and compacts
/// its agent) gets pool B to itself; everything else shares pool A. The suite must run with
/// enough `--test-threads` that both pools have a runner at once (see check.sh `live`).
///
/// Like SHARED_RO_AGENT in the server suite, the statics never drop; containers are cleaned up
/// on the next run (TestAgent::create destroys leftovers by name).
static LIVE_AGENT_A: LazyLock<Mutex<SharedAgent>> = LazyLock::new(|| Mutex::new(setup_live_agent("test-e2e-a")));
static LIVE_AGENT_B: LazyLock<Mutex<SharedAgent>> = LazyLock::new(|| Mutex::new(setup_live_agent("test-e2e-b")));

fn lock_pool(pool: &'static LazyLock<Mutex<SharedAgent>>) -> Option<(MutexGuard<'static, SharedAgent>, String)> {
    let guard = pool.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let container = guard.as_ref()?.1.clone();
    Some((guard, container))
}

/// Lock pool A (general tests: file ops, mcp tools, interrupt). Returns None (test skips) when
/// Claude credentials are unavailable.
pub fn lock_live_agent_a() -> Option<(MutexGuard<'static, SharedAgent>, String)> {
    lock_pool(&LIVE_AGENT_A)
}

/// Lock pool B (the dreamer's dedicated agent — it restarts and compacts, so it runs alone).
pub fn lock_live_agent_b() -> Option<(MutexGuard<'static, SharedAgent>, String)> {
    lock_pool(&LIVE_AGENT_B)
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

pub fn host_credentials_path() -> Option<PathBuf> {
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

pub fn wait_for_container_running(container: &str, timeout: Duration) -> Result<(), String> {
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
const FIRST_START_ALIVE_POLL: Duration = Duration::from_secs(2);

/// Agent-log markers meaning the injected credentials are being rejected by the API (a dead or
/// expired CLAUDE_CREDENTIALS). When this happens the agent idles in `setting_up` until the full
/// timeout, so first-start setup bails fast and prints the agent's own diagnostics on sight of one
/// rather than hanging for ten minutes on a generic timeout.
const FIRST_START_AUTH_FAILURE_MARKERS: &[&str] = &["Invalid authentication credentials", "Please run /login"];

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

/// Block until the agent reports `alive`, failing fast with diagnostics on an auth error.
///
/// `wait_until_alive` would block for the full timeout if the injected credentials are
/// rejected. Poll the agent's own log alongside its status and bail the moment an auth
/// error appears (a dead/expired CLAUDE_CREDENTIALS is the usual cause).
pub fn wait_until_alive_or_die(client: &vesta_tests::client::Client, name: &str, container: &str) {
    let alive_deadline = std::time::Instant::now() + FIRST_START_SETTLE_TIMEOUT;
    loop {
        if std::time::Instant::now() >= alive_deadline {
            dump_agent_diagnostics(name);
            panic!("timeout waiting for agent to go alive");
        }
        if client.agent_status(name).map(|s| s.status).unwrap_or_default() == "alive" {
            return;
        }
        let agent_log = exec_in_container(container, "cat /root/agent/logs/vesta.log 2>/dev/null || true").unwrap_or_default();
        if FIRST_START_AUTH_FAILURE_MARKERS.iter().any(|marker| agent_log.contains(marker)) {
            dump_agent_diagnostics(name);
            panic!("agent hit an auth error — CLAUDE_CREDENTIALS is invalid/expired; re-seed the secret (agent diagnostics above)");
        }
        thread::sleep(FIRST_START_ALIVE_POLL);
    }
}

/// Provision a freshly-created agent for live e2e (sonnet model, test memory, real
/// credentials) and block until it has fully settled after first-start. Shared by the live
/// agent pool and the upgrade e2e test, both of which need a real, idle agent. Panics with
/// diagnostics on failure, matching the pool's fail-fast behavior. Callers must have already
/// confirmed credentials exist (via `host_credentials_path`).
pub fn provision_and_settle(client: &vesta_tests::client::Client, name: &str, container: &str) {
    let credentials_path = host_credentials_path().expect("credentials present (caller checked)");
    let credentials = fs::read_to_string(&credentials_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", credentials_path.display()));

    wait_for_container_running(container, Duration::from_secs(60)).expect("container running");

    // Use sonnet for e2e tests — cheaper and faster than the default opus
    exec_in_container(container, "echo 'export AGENT_MODEL=sonnet' >> ~/.bashrc")
        .expect("set AGENT_MODEL=sonnet");

    exec_in_container(container, &format!("mkdir -p {E2E_FILES_DIR}")).expect("create e2e dir");
    exec_in_container(container, &format!("cat > {MEMORY_PATH} <<'EOF'\n{TEST_MEMORY}\nEOF"))
        .expect("write test memory");

    client.inject_token(name, &credentials).expect("inject real credentials");
    // Always restart after injection so the agent boots with BOTH the credentials and
    // the AGENT_MODEL=sonnet override from ~/.bashrc. Without the restart, the
    // already-running agent picks up the credentials but keeps the default (opus)
    // model for the whole first-start conversation.
    client.restart_agent(name).expect("restart agent to apply model + credentials");

    wait_until_alive_or_die(client, name, container);

    // First-start keeps going after the agent reports alive; wait (via the agent's own idle
    // signal) until it has fully settled before any test sends notifications.
    if let Err(e) = wait_for_first_start_settled(container) {
        dump_agent_diagnostics(name);
        panic!("agent did not settle after first-start: {e}");
    }
}

fn setup_live_agent(name: &str) -> Option<(TestAgent<'static>, String)> {
    if host_credentials_path().is_none() {
        eprintln!("skipping live e2e: ~/.claude/.credentials.json not found");
        return None;
    }

    // Follow the real user creation path: build the image, then discover
    // the container via the API (not by hardcoding the naming convention).
    let client = Box::leak(Box::new(SERVER.client()));
    // Retry create over transient infra hiccups (a cold image build that times out, a momentary
    // docker daemon stall). This runs inside the pool's LazyLock init, so an unwrap on a transient
    // would poison the LazyLock and cascade every test in the pool — retrying first keeps one flake
    // from failing the whole suite.
    let mut attempt = 0;
    let agent = loop {
        attempt += 1;
        match TestAgent::create(client, name) {
            Ok(agent) => break agent,
            Err(e) if attempt < 3 => {
                eprintln!("live setup: create attempt {attempt} for {name} failed ({e}); retrying");
                thread::sleep(Duration::from_secs(5));
            }
            Err(e) => panic!("create live agent {name} after {attempt} attempts: {e}"),
        }
    };

    let status = client.agent_status(&agent.name).unwrap();
    let container = status.id.unwrap_or_else(|| panic!("agent {} has no container id", agent.name));

    provision_and_settle(client, &agent.name, &container);
    Some((agent, container))
}
