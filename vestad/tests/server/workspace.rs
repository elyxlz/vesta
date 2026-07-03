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

    // Enforces the MOUNT_DESTS invariant (see docker.rs): anything mounted under
    // /root/agent/ that isn't in the workspace snapshot must be kept out of git status
    // (out-of-cone for a dir, or gitignored in agent/.gitignore for a file). An untracked
    // path here means a new mount was added without doing that.
    let status = exec_in_container(&container, "cd ~ && git status --porcelain").expect("status");
    assert_eq!(
        status.trim(),
        "",
        "fresh attach left a dirty tree: {status}\n\
         A vestad-mounted path under /root/agent/ isn't handled. If it's a new mount, add it to \
         the sparse cone (dir) or agent/.gitignore (file) -- see the MOUNT_DESTS invariant in docker.rs.",
    );

    let tags = exec_in_container(&container, "cd ~ && git tag -l 'agent-v*'").expect("tags");
    assert!(!tags.trim().is_empty(), "an agent-v tag must be fetched from the bundle");
}
