use vesta_tests::{TestAgent, SERVER, exec_in_container, unique_agent};

fn container_id(agent_name: &str) -> String {
    let status = SERVER.client().agent_status(agent_name).unwrap();
    status.id.unwrap_or_else(|| panic!("agent {agent_name} has no container id"))
}

const ENTRYPOINT_POLL_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(60);
const ENTRYPOINT_POLL_INTERVAL: std::time::Duration = std::time::Duration::from_millis(500);

/// Poll a `test -<flag> <path>` check until it succeeds or the timeout elapses.
/// CI runners are slow under contention — a single post-sleep check races with
/// the entrypoint's filesystem setup.
fn wait_for_path(cid: &str, flag: char, path: &str) {
    let deadline = std::time::Instant::now() + ENTRYPOINT_POLL_TIMEOUT;
    let script = format!("test -{flag} {path}");
    loop {
        if exec_in_container(cid, &script).is_ok() {
            return;
        }
        if std::time::Instant::now() >= deadline {
            panic!(
                "expected {} {path} to exist within {}s",
                if flag == 'd' { "directory" } else { "file" },
                ENTRYPOINT_POLL_TIMEOUT.as_secs()
            );
        }
        std::thread::sleep(ENTRYPOINT_POLL_INTERVAL);
    }
}

#[test]
fn fresh_agent_has_expected_directory_structure() {
    let c = SERVER.client();
    let agent = TestAgent::create_built(&c, &unique_agent("layout")).unwrap();
    let cid = container_id(&agent.name);

    c.wait_ready(&agent.name, 10).ok(); // may not become ready without auth, that's fine

    // Root-level directories created by Dockerfile + entrypoint
    for dir in ["/root/.git", "/root/.claude", "/root/agent"] {
        wait_for_path(&cid, 'd', dir);
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
        wait_for_path(&cid, 'd', dir);
    }

    // Key files exist
    for file in ["/root/agent/MEMORY.md", "/root/agent/pyproject.toml", "/root/.gitignore"] {
        wait_for_path(&cid, 'f', file);
    }

    // Git state: repo root is /root, on the agent's branch
    let toplevel = exec_in_container(&cid, "git -C /root rev-parse --show-toplevel").unwrap();
    assert_eq!(toplevel, "/root", "git repo root should be /root");

    let branch = exec_in_container(&cid, "git -C /root branch --show-current").unwrap();
    assert_eq!(branch, agent.name, "should be on agent's branch");

    // Sparse checkout includes agent (cone mode: "agent/subdir", non-cone mode: "/agent/")
    let sparse = exec_in_container(&cid, "git -C /root sparse-checkout list").unwrap();
    assert!(
        sparse.lines().any(|l| {
            let t = l.trim();
            t.starts_with("agent/") || t == "/agent/" || t == "agent/"
        }),
        "sparse-checkout should include agent/ paths, got: {sparse}"
    );

    // Nothing at repo root that shouldn't be there
    let root_entries = exec_in_container(&cid, "ls -1 /root").unwrap();
    for entry in root_entries.lines() {
        assert!(
            matches!(entry, "agent" | ".claude" | ".git" | ".gitignore" | ".bashrc" | ".local" | ".cache" | ".config"),
            "unexpected entry at /root: {entry}"
        );
    }
}
