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
    let agent = TestAgent::create(&c, &unique_agent("layout")).unwrap();
    let cid = container_id(&agent.name);

    c.wait_until_alive(&agent.name, 10).ok(); // will error without auth, that's fine

    // Root-level directories created by entrypoint / image COPY. Git state
    // (/root/.git, branch, sparse-checkout, .gitignore) is no longer asserted
    // here: it is initialized by the agent on first start via
    // upstream-sync/SETUP.md, which requires auth — outside this test's scope.
    for dir in ["/root/.claude", "/root/agent"] {
        wait_for_path(&cid, 'd', dir);
    }

    // .claude/skills is a directory of per-skill symlinks flattening both
    // /root/agent/skills/ and /root/agent/core/skills/.
    wait_for_path(&cid, 'd', "/root/.claude/skills");
    for skill in ["personality", "app-chat", "microsoft"] {
        let path = format!("/root/.claude/skills/{skill}");
        exec_in_container(&cid, &format!("test -L {path}"))
            .unwrap_or_else(|_| panic!("{path} should be a symlink"));
    }

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
    for file in ["/root/agent/MEMORY.md", "/root/agent/pyproject.toml"] {
        wait_for_path(&cid, 'f', file);
    }

    // Nothing at repo root that shouldn't be there. `.git` and `.gitignore` are
    // listed because the agent creates them later via upstream-sync/SETUP.md.
    let root_entries = exec_in_container(&cid, "ls -1 /root").unwrap();
    for entry in root_entries.lines() {
        assert!(
            matches!(entry, "agent" | ".claude" | ".git" | ".gitignore" | ".bashrc" | ".local" | ".cache" | ".config"),
            "unexpected entry at /root: {entry}"
        );
    }
}
