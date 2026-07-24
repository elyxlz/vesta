use vesta_tests::{
    agent_container_name, docker_cmd, mark_first_start_done, unique_agent, TestAgent, SERVER,
};

/// Core is always a read-only bind mount (`agent/core`), never a writable image copy: the box
/// checks out only skills + MEMORY.md, and the engine is mounted so agent self-updates never
/// touch it. MEMORY.md stays writable.
fn assert_agent_core_is_readonly_mount(container: &str) -> Result<(), String> {
    let script = r#"set -e
for p in /root/agent/core /root/agent/core/pyproject.toml /root/agent/core/uv.lock; do
  if [ ! -e "$p" ]; then echo "missing $p"; exit 1; fi
  if [ -w "$p" ]; then echo "expected read-only mount: $p"; exit 1; fi
done
if [ ! -w /root/agent/MEMORY.md ]; then echo "MEMORY.md should remain writable"; exit 1; fi
"#;
    docker_cmd(&["exec", container, "bash", "-lc", script])?;
    Ok(())
}

#[test]
fn core_is_always_a_readonly_mount() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("core-mount")).unwrap();
    mark_first_start_done(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    // This test asserts container mount permissions, not auth — a running agent
    // (no credentials, so it settles at not_authenticated) is all it needs.
    c.wait_until_running(&agent.name, 180)
        .expect("agent should come up with core-code mounts");
    let container = agent_container_name(&agent.name);
    assert_agent_core_is_readonly_mount(&container).expect("core paths should be read-only mounts");
}
