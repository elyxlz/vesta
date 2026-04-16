use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use std::sync::atomic::{AtomicU32, Ordering};
use vesta_tests::{SERVER, TestAgent};

static LIVE_STAGGER: AtomicU32 = AtomicU32::new(0);

const MEMORY_PATH: &str = "/root/agent/MEMORY.md";
const NOTIFICATIONS_DIR: &str = "/root/agent/notifications";
const E2E_FILES_DIR: &str = "/root/agent/e2e-test";
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

fn docker(args: &[&str]) -> Result<String, String> {
    let output = Command::new("docker")
        .args(args)
        .output()
        .map_err(|e| format!("docker {:?}: {e}", args))?;
    if !output.status.success() {
        return Err(format!(
            "docker {:?} failed: {}",
            args,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn exec_in_container(container: &str, script: &str) -> Result<String, String> {
    docker(&["exec", container, "bash", "-lc", script])
}

fn exec_ok(container: &str, script: &str) -> bool {
    Command::new("docker")
        .args(["exec", container, "bash", "-lc", script])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn agent_container_name(agent_name: &str) -> String {
    let user = std::env::var("USER").unwrap_or_else(|_| "unknown".to_string());
    format!("vesta-{}-{}", user, agent_name)
}

fn host_credentials_path() -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    let path = PathBuf::from(home).join(".claude/.credentials.json");
    path.exists().then_some(path)
}

fn write_notification(container: &str, message: &str, interrupt: bool) -> Result<(), String> {
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
    docker(&["cp", tmp.path().to_str().unwrap_or_default(), &format!("{container}:{container_path}")])?;
    Ok(())
}

fn wait_for_file_contains(container: &str, path: &str, needle: &str, timeout: Duration) -> Result<String, String> {
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
        if let Ok(state) = docker(&["inspect", container, "--format", "{{.State.Running}}"]) {
            if state.trim() == "true" {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_secs(1));
    }
    Err(format!("timed out waiting for {container} to be running"))
}

fn setup_live_agent(name: &str, write_test_memory: bool, ensure_e2e_dir: bool) -> Option<(TestAgent<'static>, String)> {
    if std::env::var("CI").is_ok() {
        eprintln!("skipping live e2e test on CI");
        return None;
    }

    let Some(credentials_path) = host_credentials_path() else {
        eprintln!("skipping agent e2e: ~/.claude/.credentials.json not found");
        return None;
    };

    let credentials = fs::read_to_string(&credentials_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", credentials_path.display()));

    // Stagger agent startups by 5s each to avoid contention when tests run concurrently
    let slot = LIVE_STAGGER.fetch_add(1, Ordering::SeqCst);
    thread::sleep(Duration::from_secs(slot as u64 * 5));

    let client = Box::leak(Box::new(SERVER.client()));
    let agent = TestAgent::create(client, name).unwrap();
    let container = agent_container_name(&agent.name);

    wait_for_container_running(&container, Duration::from_secs(30)).expect("container running");
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

    client.inject_token(&agent.name, &credentials).expect("inject real credentials");
    client.restart_agent(&agent.name).expect("restart agent");
    client.wait_ready(&agent.name, 300).expect("wait ready");
    Some((agent, container))
}

#[test]
fn agent_notification_e2e_creates_file_via_vestad() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-create", true, true) else {
        return;
    };

    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let created = format!("{E2E_FILES_DIR}/single-{uid}.txt");
    let expected = format!("E2E content {uid}");

    write_notification(
        &container,
        &format!("Create the file \"{created}\" containing only:\n{expected}"),
        true,
    )
    .expect("write create notification");

    let created_content = wait_for_file_contains(&container, &created, &expected, Duration::from_secs(180))
        .expect("wait for created file");
    assert!(created_content.contains(&expected));
}

#[test]
fn agent_notification_e2e_modifies_file_via_vestad() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-modify", true, true) else {
        return;
    };

    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let modified = format!("{E2E_FILES_DIR}/modify-{uid}.txt");

    exec_in_container(&container, &format!("printf '%s\n' 'original content' > {modified}"))
        .expect("seed file");
    write_notification(
        &container,
        &format!("Append the text \"--- APPENDED ---\" to the file \"{modified}\""),
        true,
    )
    .expect("write modify notification");

    let modified_content = wait_for_file_contains(&container, &modified, "APPENDED", Duration::from_secs(180))
        .expect("wait for modified file");
    assert!(modified_content.contains("original content"));
    assert!(modified_content.contains("APPENDED"));
}

#[test]
fn agent_notification_e2e_reports_root_tree_via_vestad() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-tree", true, true) else {
        return;
    };

    // Verify expected directory structure directly via filesystem
    for path in [
        "/root/.git",
        "/root/.claude",
        "/root/.claude/skills",
        "/root/agent",
        "/root/agent/data",
        "/root/agent/logs",
        "/root/agent/notifications",
        "/root/agent/dreamer",
        "/root/agent/prompts",
        "/root/agent/skills",
        "/root/agent/e2e-test",
    ] {
        exec_in_container(&container, &format!("test -d {path}"))
            .unwrap_or_else(|_| panic!("expected directory {path} to exist"));
    }

    // Verify the agent can follow instructions by creating a file via notification
    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let report = format!("{E2E_FILES_DIR}/report-{uid}.txt");

    write_notification(
        &container,
        &format!(
            "Use the upstream-sync setup guide at agent/skills/upstream-sync/SETUP.md to bring the workspace into the correct modern layout.\n\
\n\
Assume the old starting tree looked like this before migration:\n\
/root\n\
|-- go\n\
|   `-- pkg\n\
`-- vesta\n\
    |-- MEMORY.md\n\
    |-- random-dir\n\
    |-- src\n\
    |   `-- vesta\n\
    `-- data\n\
\n\
Now create the file \"{report}\" containing only a tree-style file listing of the current /root after migration. The resulting tree should reflect the modern layout under /root/agent and /root/.claude.\n\
\n\
Use the same tree formatting style as the example above.\n\
\n\
Return only after writing the file."
        ),
        true,
    )
    .expect("write report notification");

    wait_for_file_contains(&container, &report, "/root", Duration::from_secs(180))
        .expect("wait for report file");
}

#[test]
fn agent_notification_e2e_reports_fresh_install_tree_via_vestad() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-fresh", false, false) else {
        return;
    };

    // Verify expected directory structure directly via filesystem
    for path in [
        "/root/.git",
        "/root/.claude",
        "/root/.claude/skills",
        "/root/agent",
        "/root/agent/MEMORY.md",
        "/root/agent/data",
        "/root/agent/logs",
        "/root/agent/notifications",
        "/root/agent/dreamer",
        "/root/agent/prompts",
        "/root/agent/skills",
    ] {
        exec_in_container(&container, &format!("test -e {path}"))
            .unwrap_or_else(|_| panic!("expected {path} to exist"));
    }
}
