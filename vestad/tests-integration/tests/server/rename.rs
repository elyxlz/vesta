use vesta_tests::{
    SERVER, TestAgent, agent_container_name, docker_cmd, exec_in_container, inject_fake_token,
    is_up, unique_agent,
};

fn agents_dir() -> std::path::PathBuf {
    SERVER.home_path().join(".config/vesta/vestad/agents")
}

#[test]
fn rename_basic() {
    let c = SERVER.client();
    let mut agent = TestAgent::create(&c, &unique_agent("rename-basic")).unwrap();
    let old_name = agent.name.clone();
    let new_name = unique_agent("rename-target");

    let returned = c.rename_agent(&old_name, &new_name).unwrap();
    assert_eq!(returned, new_name);

    assert_eq!(c.agent_status(&old_name).unwrap().status, "not_found");
    assert!(is_up(&c.agent_status(&new_name).unwrap().status));

    let list = c.list_agents().unwrap();
    assert!(list.iter().any(|a| a.name == new_name));
    assert!(!list.iter().any(|a| a.name == old_name));

    let old_env = agents_dir().join(format!("{old_name}.env"));
    let new_env = agents_dir().join(format!("{new_name}.env"));
    assert!(!old_env.exists(), "old env file should be deleted: {}", old_env.display());
    assert!(new_env.exists(), "new env file should exist: {}", new_env.display());
    let env_contents = std::fs::read_to_string(&new_env).unwrap();
    assert!(
        env_contents.contains(&format!("AGENT_NAME={new_name}")),
        "AGENT_NAME not updated in {}: {env_contents}",
        new_env.display()
    );

    agent.name = new_name; // let Drop clean up the renamed container
}

#[test]
fn rename_preserves_in_container_state() {
    let c = SERVER.client();
    let mut agent = TestAgent::create(&c, &unique_agent("rename-state")).unwrap();
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).unwrap();

    let old_container = agent_container_name(&agent.name);
    exec_in_container(&old_container, "echo hello-from-old > /root/marker.txt").unwrap();

    let new_name = unique_agent("rename-state-target");
    c.rename_agent(&agent.name, &new_name).unwrap();

    let new_container = agent_container_name(&new_name);
    let marker = exec_in_container(&new_container, "cat /root/marker.txt").unwrap();
    assert_eq!(marker.trim(), "hello-from-old");

    agent.name = new_name;
}

#[test]
fn rename_updates_container_label() {
    let c = SERVER.client();
    let mut agent = TestAgent::create(&c, &unique_agent("rename-label")).unwrap();
    let new_name = unique_agent("rename-label-target");

    c.rename_agent(&agent.name, &new_name).unwrap();

    let new_container = agent_container_name(&new_name);
    let label = docker_cmd(&[
        "inspect",
        "--format",
        "{{ index .Config.Labels \"vesta.agent_name\" }}",
        &new_container,
    ])
    .unwrap();
    assert_eq!(label.trim(), new_name);

    agent.name = new_name;
}

#[test]
fn rename_to_same_name_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("rename-same")).unwrap();
    let err = c.rename_agent(&agent.name, &agent.name).unwrap_err();
    assert!(err.contains("differ"), "expected 'differ' in error: {err}");
}

#[test]
fn rename_to_existing_fails() {
    let c = SERVER.client();
    let a = TestAgent::create(&c, &unique_agent("rename-conflict-a")).unwrap();
    let b = TestAgent::create(&c, &unique_agent("rename-conflict-b")).unwrap();

    let err = c.rename_agent(&a.name, &b.name).unwrap_err();
    assert!(
        err.contains("already exists"),
        "expected conflict error: {err}"
    );

    // Both should still exist unchanged
    assert!(is_up(&c.agent_status(&a.name).unwrap().status));
    assert!(is_up(&c.agent_status(&b.name).unwrap().status));
}

#[test]
fn rename_nonexistent_fails() {
    let c = SERVER.client();
    let err = c
        .rename_agent("does-not-exist-xyz", "should-not-be-created")
        .unwrap_err();
    assert!(
        err.contains("not found") || err.contains("not_found"),
        "expected not-found error: {err}"
    );
    assert_eq!(
        c.agent_status("should-not-be-created").unwrap().status,
        "not_found"
    );
}

#[test]
fn rename_invalid_new_name_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("rename-invalid")).unwrap();

    // normalize_name strips invalid chars; "!!!" reduces to "" which 400s
    let err = c.rename_agent(&agent.name, "!!!").unwrap_err();
    assert!(
        err.contains("invalid"),
        "expected invalid-name error: {err}"
    );
    assert!(is_up(&c.agent_status(&agent.name).unwrap().status));
}
