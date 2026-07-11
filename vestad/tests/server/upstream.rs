use vesta_tests::{agent_container_name, exec_in_container, mark_first_start_done, unique_agent, TestAgent, SERVER};

/// The production sync path, end to end: the box fetches from the bind-mounted upstream
/// repo (/run/vesta-upstream) and attaches. No synthetic remote anywhere.
#[test]
fn agent_attaches_to_the_upstream_through_the_mounted_repo() {
    let client = SERVER.client();
    let agent = TestAgent::create_with_manage_agent_code(&client, &unique_agent("up-attach")).unwrap();
    mark_first_start_done(&agent.name).unwrap();
    client.restart_agent(&agent.name).unwrap();
    client.wait_until_running(&agent.name, 180).expect("agent up");
    let container = agent_container_name(&agent.name);

    let attach = exec_in_container(
        &container,
        ". /run/vestad-env && bash ~/agent/core/skills/upstream-sync/scripts/attach.sh",
    )
    .expect("attach succeeds through the mounted upstream repo");
    assert!(attach.contains("attached:"), "attach output: {attach}");

    // Enforces the MOUNT_DESTS invariant (see docker.rs): anything mounted under
    // /root/agent/ that isn't in the upstream snapshot must be kept out of git status
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
    assert!(!tags.trim().is_empty(), "an agent-v tag must be fetched from the mounted repo");

    // LEGACY(remove-when: no agent predating the release that ships the upstream rename
    // remains and the 2026-07 workspace migrations are fleet-applied): a pre-rename box's
    // checked-out fetch-workspace.sh still curls the bundle endpoint for its one
    // convergence sync; it must keep serving a fetchable bundle carrying agent-workspace.
    let legacy = exec_in_container(
        &container,
        ". /run/vestad-env && curl -fsSk -H \"X-Agent-Token: $AGENT_TOKEN\" \
         \"https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/workspace.bundle\" -o /tmp/legacy.bundle \
         && git -C ~ fetch --no-tags /tmp/legacy.bundle \
         '+refs/heads/agent-workspace:refs/remotes/origin/agent-workspace' \
         && git -C ~ rev-parse refs/remotes/origin/agent-workspace",
    )
    .expect("legacy bundle endpoint still serves a fetchable bundle");
    assert!(!legacy.trim().is_empty(), "legacy branch must resolve after bundle fetch: {legacy}");
}
