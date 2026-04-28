use std::thread::sleep;
use std::time::{Duration, Instant};

use vesta_tests::{
    TestAgent, SERVER, SHARED_RO_AGENT, agent_container_name, docker_cmd, exec_in_container,
    inject_fake_token, is_up, unique_agent,
};

const RESTART_POLL_INTERVAL: Duration = Duration::from_millis(500);

#[test]
fn create_and_list() {
    let c = SERVER.client();
    let list = c.list_agents().unwrap();
    let name: &str = &SHARED_RO_AGENT;
    assert!(list.iter().any(|a| a.name == name));
}

#[test]
fn create_duplicate_fails() {
    let c = SERVER.client();
    let result = c.create_agent(&SHARED_RO_AGENT);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.contains("already exists"), "unexpected error: {err}");
}

#[test]
fn status_not_found() {
    let c = SERVER.client();
    let status = c.agent_status("nonexistent-agent-xyz").unwrap();
    assert_eq!(status.status, "not_found");
}

#[test]
fn start_stop_restart() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("start-stop")).unwrap();

    c.start_agent(&agent.name).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert!(is_up(&st.status), "expected up, got {}", st.status);

    c.stop_agent(&agent.name).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert!(!is_up(&st.status), "expected stopped, got {}", st.status);

    c.start_agent(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    let st = c.agent_status(&agent.name).unwrap();
    assert!(is_up(&st.status), "expected up after restart, got {}", st.status);
}

#[test]
fn destroy_removes_agent() {
    let c = SERVER.client();
    let name = c.create_agent(&unique_agent("destroy")).unwrap();
    c.destroy_agent(&name).unwrap();
    let st = c.agent_status(&name).unwrap();
    assert_eq!(st.status, "not_found");
}

#[test]
fn destroy_stops_running_agent() {
    let c = SERVER.client();
    let name = c.create_agent(&unique_agent("destroy-run")).unwrap();
    inject_fake_token(&c, &name);
    c.start_agent(&name).unwrap();
    assert!(is_up(&c.agent_status(&name).unwrap().status));

    c.destroy_agent(&name).unwrap();
    assert_eq!(c.agent_status(&name).unwrap().status, "not_found");
}

#[test]
fn start_nonexistent_fails() {
    assert!(SERVER.client().start_agent("does-not-exist").is_err());
}

#[test]
fn stop_nonexistent_fails() {
    assert!(SERVER.client().stop_agent("does-not-exist").is_err());
}

#[test]
fn create_auto_starts() {
    let c = SERVER.client();
    let st = c.agent_status(&SHARED_RO_AGENT).unwrap();
    assert!(is_up(&st.status), "expected up after create, got {}", st.status);
}

#[test]
fn creation_flow() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("flow")).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "not_authenticated");

    inject_fake_token(&c, &agent.name);
    assert_ne!(c.agent_status(&agent.name).unwrap().status, "not_authenticated");

    c.restart_agent(&agent.name).unwrap();
    c.wait_until_alive(&agent.name, 60).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_eq!(st.status, "alive");
}

#[test]
fn start_all_starts_authenticated_agents() {
    let c = SERVER.client();
    let a1 = TestAgent::create(&c, &unique_agent("startall")).unwrap();
    let a2 = TestAgent::create(&c, &unique_agent("startall")).unwrap();
    inject_fake_token(&c, &a1.name);
    inject_fake_token(&c, &a2.name);

    c.start_all().unwrap();

    assert!(is_up(&c.agent_status(&a1.name).unwrap().status));
    assert!(is_up(&c.agent_status(&a2.name).unwrap().status));
}

#[test]
fn start_nonexistent_error_message() {
    let err = SERVER.client().start_agent("no-such-agent").unwrap_err();
    assert!(err.contains("not found") || err.contains("not_found"), "error should mention not found: {err}");
}

#[test]
fn destroy_nonexistent_error_message() {
    let err = SERVER.client().destroy_agent("no-such-agent").unwrap_err();
    assert!(err.contains("not found") || err.contains("not_found"), "error should mention not found: {err}");
}

/// Verifies the container-restart contract behind the agent's `restart_vesta`
/// MCP tool. The tool calls `os.kill(os.getpid(), SIGTERM)` from inside the
/// agent's python process; the python interpreter exits, taking its `uv run`
/// parent (PID 1) with it, and Docker's `unless-stopped` restart policy
/// brings the container back up. Sending SIGTERM to PID 1 directly hits the
/// same exit path without needing the live Claude API. Asserts both that
/// status returns to "up" and that `RestartCount` advanced, which is proof
/// of an actual restart rather than continuous uptime.
#[test]
fn restart_via_agent_sigterm_recovers() {
    const ENTRYPOINT_READY_TIMEOUT_SECS: u64 = 60;
    const RESTART_TIMEOUT_SECS: u64 = 60;

    let client = SERVER.client();
    let agent = TestAgent::create(&client, &unique_agent("sigterm-restart")).unwrap();

    let initial_status = client.agent_status(&agent.name).unwrap();
    assert!(is_up(&initial_status.status), "expected up after create, got {}", initial_status.status);

    let container = agent_container_name(&agent.name);

    wait_for_entrypoint_ready(&container, Duration::from_secs(ENTRYPOINT_READY_TIMEOUT_SECS))
        .expect("agent entrypoint did not reach 'uv run'");

    let initial_restart_count = inspect_restart_count(&container).expect("read initial restart count");

    exec_in_container(&container, "kill -TERM 1").expect("send SIGTERM to PID 1");

    let deadline = Instant::now() + Duration::from_secs(RESTART_TIMEOUT_SECS);
    let (final_status, final_restart_count) = loop {
        let status = client.agent_status(&agent.name).unwrap().status;
        let restart_count = inspect_restart_count(&container).unwrap_or(initial_restart_count);
        if restart_count > initial_restart_count && is_up(&status) {
            break (status, restart_count);
        }
        if Instant::now() >= deadline {
            panic!(
                "container did not restart within {}s (status={}, restart_count {} -> {})",
                RESTART_TIMEOUT_SECS, status, initial_restart_count, restart_count,
            );
        }
        sleep(RESTART_POLL_INTERVAL);
    };

    assert!(is_up(&final_status), "expected up after restart, got {}", final_status);
    assert!(
        final_restart_count > initial_restart_count,
        "expected RestartCount to advance ({} -> {})",
        initial_restart_count,
        final_restart_count,
    );
}

fn inspect_restart_count(container: &str) -> Result<u64, String> {
    let out = docker_cmd(&["inspect", "--format", "{{.RestartCount}}", container])?;
    out.trim()
        .parse::<u64>()
        .map_err(|e| format!("parse RestartCount {out:?}: {e}"))
}

/// Wait until PID 1 inside the container is `uv run ...`, signalling that
/// the bootstrap shell has finished setup and exec'd into the agent. Until
/// then PID 1 is still `sh -c "<bootstrap script>"` and killing it would
/// race with the bootstrap rather than test the steady-state restart
/// contract.
fn wait_for_entrypoint_ready(container: &str, timeout: Duration) -> Result<(), String> {
    const READ_PID1_CMDLINE: &str = r#"tr '\0' ' ' < /proc/1/cmdline"#;
    let deadline = Instant::now() + timeout;
    loop {
        if let Ok(out) = exec_in_container(container, READ_PID1_CMDLINE) {
            if out.trim_start().starts_with("uv run") {
                return Ok(());
            }
        }
        if Instant::now() >= deadline {
            return Err(format!("PID 1 was not `uv run ...` within {}s", timeout.as_secs()));
        }
        sleep(RESTART_POLL_INTERVAL);
    }
}
