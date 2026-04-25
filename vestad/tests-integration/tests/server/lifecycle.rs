use vesta_tests::{TestAgent, SERVER, inject_fake_token, is_up, unique_agent};

#[test]
fn create_and_list() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("create-list")).unwrap();
    let list = c.list_agents().unwrap();
    assert!(list.iter().any(|a| a.name == agent.name));
}

#[test]
fn create_duplicate_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("dup")).unwrap();
    let result = c.create_agent(&agent.name);
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
    let agent = TestAgent::create(&c, &unique_agent("autostart")).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
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
    c.wait_ready(&agent.name, 60).unwrap();

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
