use vesta_tests::{
    agent_container_name, docker_cmd, mark_first_start_done, unique_agent, TestAgent, SERVER,
};

fn assert_agent_core_paths_permissions(
    container: &str,
    expect_readonly_mounts: bool,
) -> Result<(), String> {
    let script = if expect_readonly_mounts {
        r#"set -e
for p in /root/agent/core /root/agent/core/pyproject.toml /root/agent/core/uv.lock; do
  if [ ! -e "$p" ]; then echo "missing $p"; exit 1; fi
  if [ -w "$p" ]; then echo "expected read-only mount: $p"; exit 1; fi
done
if [ ! -w /root/agent/MEMORY.md ]; then echo "MEMORY.md should remain writable"; exit 1; fi
"#
    } else {
        r#"set -e
for p in /root/agent/core /root/agent/core/pyproject.toml /root/agent/core/uv.lock; do
  if [ ! -e "$p" ]; then echo "missing $p"; exit 1; fi
  if [ ! -w "$p" ]; then echo "expected writable (image copy): $p"; exit 1; fi
done
"#
    };
    docker_cmd(&["exec", container, "bash", "-lc", script])?;
    Ok(())
}

#[test]
fn manage_agent_code_true_reaches_ready() {
    let c = SERVER.client();
    let agent = TestAgent::create_with_manage_agent_code(&c, &unique_agent("manage-code")).unwrap();
    mark_first_start_done(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    // This test asserts container mount permissions, not auth — a running agent
    // (no credentials, so it settles at not_authenticated) is all it needs.
    c.wait_until_running(&agent.name, 180)
        .expect("agent should come up with core-code mounts");
    let container = agent_container_name(&agent.name);
    assert_agent_core_paths_permissions(&container, true)
        .expect("core paths should be read-only mounts");
}

#[test]
fn manage_agent_code_false_reaches_ready() {
    let c = SERVER.client();
    let agent =
        TestAgent::create_without_manage_agent_code(&c, &unique_agent("no-manage-code")).unwrap();
    mark_first_start_done(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    // This test asserts container mount permissions, not auth — a running agent
    // (no credentials, so it settles at not_authenticated) is all it needs.
    c.wait_until_running(&agent.name, 180)
        .expect("agent should come up without core-code mounts");
    let container = agent_container_name(&agent.name);
    assert_agent_core_paths_permissions(&container, false)
        .expect("core paths should be writable from image");
}
