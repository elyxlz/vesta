use vesta_tests::{TestAgent, SERVER, inject_fake_token, agent_container_name, docker_cmd, unique_agent};

fn assert_agent_core_paths_permissions(container: &str, expect_readonly_mounts: bool) -> Result<(), String> {
    let script = if expect_readonly_mounts {
        r#"set -e
for p in /root/agent/core /root/agent/pyproject.toml /root/agent/uv.lock; do
  if [ ! -e "$p" ]; then echo "missing $p"; exit 1; fi
  if [ -w "$p" ]; then echo "expected read-only mount: $p"; exit 1; fi
done
if [ ! -w /root/agent/MEMORY.md ]; then echo "MEMORY.md should remain writable"; exit 1; fi
"#
    } else {
        r#"set -e
for p in /root/agent/core /root/agent/pyproject.toml /root/agent/uv.lock; do
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
    inject_fake_token(&c, &agent.name);
    c.wait_until_alive(&agent.name, 180).expect("agent should become ready with core-code mounts");
    let container = agent_container_name(&agent.name);
    assert_agent_core_paths_permissions(&container, true).expect("core paths should be read-only mounts");
}

#[test]
fn manage_agent_code_false_reaches_ready() {
    let c = SERVER.client();
    let agent = TestAgent::create_without_manage_agent_code(&c, &unique_agent("no-manage-code")).unwrap();
    inject_fake_token(&c, &agent.name);
    c.wait_until_alive(&agent.name, 180).expect("agent should become ready without core-code mounts");
    let container = agent_container_name(&agent.name);
    assert_agent_core_paths_permissions(&container, false).expect("core paths should be writable from image");
}

#[test]
fn rebuild_preserves_auth() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("rebuild")).unwrap();
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).unwrap();

    c.rebuild_agent(&agent.name).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert_ne!(st.status, "not_authenticated");
    assert_ne!(st.status, "not_found");
}
