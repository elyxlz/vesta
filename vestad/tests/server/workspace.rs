use vesta_tests::{agent_container_name, exec_in_container, mark_first_start_done, unique_agent, TestAgent, SERVER};

/// The production sync path, end to end: the box curls its own vestad for the workspace
/// bundle and attaches. No synthetic remote anywhere.
#[test]
fn agent_attaches_to_the_workspace_through_the_bundle_endpoint() {
    let client = SERVER.client();
    let agent = TestAgent::create_with_manage_agent_code(&client, &unique_agent("ws-attach")).unwrap();
    mark_first_start_done(&agent.name).unwrap();
    client.restart_agent(&agent.name).unwrap();
    client.wait_until_running(&agent.name, 180).expect("agent up");
    let container = agent_container_name(&agent.name);

    let attach = exec_in_container(
        &container,
        ". /run/vestad-env && bash ~/agent/core/skills/workspace-sync/scripts/attach.sh",
    )
    .expect("attach succeeds through the live bundle endpoint");
    assert!(attach.contains("attached:"), "attach output: {attach}");

    let status = exec_in_container(&container, "cd ~ && git status --porcelain").expect("status");
    assert_eq!(status.trim(), "", "fresh attach must leave a clean tree, got: {status}");

    let tags = exec_in_container(&container, "cd ~ && git tag -l 'agent-v*'").expect("tags");
    assert!(!tags.trim().is_empty(), "an agent-v tag must be fetched from the bundle");
}
