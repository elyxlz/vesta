use vesta_tests::{TestAgent, SERVER, exec_in_container};

fn container_id(agent_name: &str) -> String {
    let status = SERVER.client().agent_status(agent_name).unwrap();
    status.id.unwrap_or_else(|| panic!("agent {agent_name} has no container id"))
}

#[test]
fn fresh_agent_has_expected_directory_structure() {
    let c = SERVER.client();
    let agent = TestAgent::create_built(&c, "test-layout-fresh").unwrap();
    let cid = container_id(&agent.name);

    // Wait for entrypoint to finish setting up the filesystem
    c.wait_ready(&agent.name, 10).ok(); // may not become ready without auth, that's fine
    std::thread::sleep(std::time::Duration::from_secs(5));

    // Root-level directories created by Dockerfile + entrypoint
    for dir in ["/root/.git", "/root/.claude", "/root/agent"] {
        exec_in_container(&cid, &format!("test -d {dir}"))
            .unwrap_or_else(|_| panic!("expected directory {dir} to exist"));
    }

    // .claude/skills symlink points to agent skills
    exec_in_container(&cid, "test -L /root/.claude/skills")
        .expect(".claude/skills should be a symlink");
    let target = exec_in_container(&cid, "readlink /root/.claude/skills").unwrap();
    assert!(target.contains("agent/skills"), "skills symlink should point to agent/skills, got: {target}");

    // Agent subdirectories
    for dir in [
        "/root/agent/data",
        "/root/agent/logs",
        "/root/agent/notifications",
        "/root/agent/dreamer",
        "/root/agent/prompts",
        "/root/agent/skills",
        "/root/agent/core",
    ] {
        exec_in_container(&cid, &format!("test -d {dir}"))
            .unwrap_or_else(|_| panic!("expected directory {dir} to exist"));
    }

    // Key files exist
    for file in ["/root/agent/MEMORY.md", "/root/agent/pyproject.toml", "/root/.gitignore"] {
        exec_in_container(&cid, &format!("test -f {file}"))
            .unwrap_or_else(|_| panic!("expected file {file} to exist"));
    }

    // Git state: repo root is /root, on the agent's branch
    let toplevel = exec_in_container(&cid, "git -C /root rev-parse --show-toplevel").unwrap();
    assert_eq!(toplevel, "/root", "git repo root should be /root");

    let branch = exec_in_container(&cid, "git -C /root branch --show-current").unwrap();
    assert_eq!(branch, agent.name, "should be on agent's branch");

    // Sparse checkout includes agent subdirectories
    let sparse = exec_in_container(&cid, "git -C /root sparse-checkout list").unwrap();
    assert!(sparse.lines().any(|l| l.trim().starts_with("agent/")), "sparse-checkout should include agent/ paths, got: {sparse}");

    // Nothing at repo root that shouldn't be there
    let root_entries = exec_in_container(&cid, "ls -1 /root").unwrap();
    for entry in root_entries.lines() {
        assert!(
            matches!(entry, "agent" | ".claude" | ".git" | ".gitignore" | ".bashrc" | ".local" | ".cache" | ".config"),
            "unexpected entry at /root: {entry}"
        );
    }
}
