use std::fs;
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::sync::{LazyLock, Mutex, MutexGuard};

use vesta_tests::{SERVER, TestAgent, docker_cmd, dump_agent_diagnostics, exec_in_container, parse_release_tag};

type SharedAgent = Option<(TestAgent<'static>, String)>;

/// The live suite runs against a POOL of two shared agents rather than one, so independent tests
/// run in parallel. Each agent pays its own one-time first-start (the expensive multi-minute
/// real-model setup), but the two first-starts run concurrently, so the pool's setup wall-clock
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
/// OPENROUTER_KEY is unset.
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

/// Default OpenRouter model for the live suite — cheap and fast. Override with LIVE_TEST_MODEL.
const DEFAULT_LIVE_MODEL: &str = "deepseek/deepseek-v4-flash";

/// The OpenRouter model the live agents run with, from LIVE_TEST_MODEL or the default above.
pub fn live_model() -> String {
    std::env::var("LIVE_TEST_MODEL")
        .ok()
        .filter(|model| !model.is_empty())
        .unwrap_or_else(|| DEFAULT_LIVE_MODEL.to_string())
}

/// The OpenRouter API key the live suite authenticates with, from OPENROUTER_KEY. None (tests skip)
/// when it is unset, mirroring the old missing-credentials skip.
pub fn openrouter_key() -> Option<String> {
    std::env::var("OPENROUTER_KEY").ok().filter(|key| !key.is_empty())
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

/// Agent-log markers meaning the injected key is being rejected by the provider (a bad or
/// out-of-credit OPENROUTER_KEY — the agent flips to not_authenticated on a terminal 401/402).
/// When this happens the agent idles in `setting_up` until the full timeout, so first-start setup
/// bails fast and prints the agent's own diagnostics on sight of one rather than hanging for ten
/// minutes on a generic timeout.
const FIRST_START_AUTH_FAILURE_MARKERS: &[&str] = &["Provider auth lost (terminal upstream 401/402)"];

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
/// `wait_until_alive` would block for the full timeout if the injected key is
/// rejected. Poll the agent's own log alongside its status and bail the moment an auth
/// error appears (a bad/out-of-credit OPENROUTER_KEY is the usual cause).
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
            panic!("agent hit an auth error — OPENROUTER_KEY is invalid or out of credit; re-seed the secret (agent diagnostics above)");
        }
        thread::sleep(FIRST_START_ALIVE_POLL);
    }
}

/// First release whose provider sign-in is the current `PUT /provider` + `{kind,model,key}`
/// contract; every earlier release serves `POST /provider` + `{openrouter_key, openrouter_model}`.
/// LEGACY(remove-when: `previous_released_tag` >= 0.1.161 — i.e. once 0.1.160 is no longer an
/// upgrade-from target, which holds after the 0.1.161 release): delete this, `LegacyPrePut`, and
/// `for_daemon_tag`, leaving the upgrade test on `ProviderApi::Current`.
const PROVIDER_PUT_CONTRACT_SINCE: [u64; 3] = [0, 1, 161];

/// Which provider sign-in contract `provision_and_settle` uses. The live pool always talks to the
/// current daemon; the upgrade e2e provisions against the previous released daemon, whose sign-in
/// may predate the current contract — so it derives the variant from that daemon's version rather
/// than hardcoding one, keeping the test correct for any upgrade-from version.
#[derive(Clone, Copy)]
pub enum ProviderApi {
    Current,
    /// LEGACY(remove-when: see `PROVIDER_PUT_CONTRACT_SINCE`): pre-0.1.161 sign-in shape.
    LegacyPrePut,
}

impl ProviderApi {
    /// The sign-in contract a daemon released as `tag` speaks. Unparseable/newer tags default to
    /// the current contract.
    pub fn for_daemon_tag(tag: &str) -> ProviderApi {
        match parse_release_tag(tag) {
            Some(parts) if parts.as_slice() < &PROVIDER_PUT_CONTRACT_SINCE[..] => ProviderApi::LegacyPrePut,
            _ => ProviderApi::Current,
        }
    }
}

/// Provision a freshly-created agent for live e2e (OpenRouter provider on `live_model()`, test
/// memory, real key) and block until it has fully settled after first-start. Shared by the live
/// agent pool and the upgrade e2e test, both of which need a real, idle agent. Panics with
/// diagnostics on failure, matching the pool's fail-fast behavior. Callers must have already
/// confirmed the key exists (via `openrouter_key`).
pub fn provision_and_settle(client: &vesta_tests::client::Client, name: &str, container: &str, api: ProviderApi) {
    let key = openrouter_key().expect("OPENROUTER_KEY present (caller checked)");
    let model = live_model();

    wait_for_container_running(container, Duration::from_secs(60)).expect("container running");

    exec_in_container(container, &format!("mkdir -p {E2E_FILES_DIR}")).expect("create e2e dir");
    exec_in_container(container, &format!("cat > {MEMORY_PATH} <<'EOF'\n{TEST_MEMORY}\nEOF"))
        .expect("write test memory");

    match api {
        ProviderApi::Current => client.sign_in_openrouter(name, &key, &model),
        ProviderApi::LegacyPrePut => client.sign_in_openrouter_legacy_pre_put(name, &key, &model),
    }
    .expect("sign in with OpenRouter");
    // Restart after sign-in so the agent boots with the OpenRouter provider applied: vestad applies
    // a provider write only on the next boot, so first-start then runs entirely on the chosen model.
    client.restart_agent(name).expect("restart agent to apply provider");

    wait_until_alive_or_die(client, name, container);

    // First-start keeps going after the agent reports alive; wait (via the agent's own idle
    // signal) until it has fully settled before any test sends notifications.
    if let Err(e) = wait_for_first_start_settled(container) {
        dump_agent_diagnostics(name);
        panic!("agent did not settle after first-start: {e}");
    }
}

fn setup_live_agent(name: &str) -> Option<(TestAgent<'static>, String)> {
    if openrouter_key().is_none() {
        eprintln!("skipping live e2e: OPENROUTER_KEY not set");
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

    provision_and_settle(client, &agent.name, &container, ProviderApi::Current);
    Some((agent, container))
}
