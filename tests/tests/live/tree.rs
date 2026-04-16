use vesta_tests::exec_in_container;

use super::common::setup_live_agent;

/// Create a live agent with an old-style ~/vesta/ layout and a pre-existing
/// first_start_done marker. This simulates a rebuild where vestad normalized
/// the filesystem but the agent still needs to run its migration prompt
/// (which fires on non-first-start restarts). Since wait_ready only returns
/// after the migration prompt is fully processed, the migration must be
/// complete by the time we run assertions.
#[test]
fn first_start_migrates_old_layout() {
    let Some((_agent, container)) = setup_live_agent(
        "test-e2e-migrate",
        false,
        false,
        Some(seed_old_layout),
    ) else {
        return;
    };

    // wait_ready returned — first_start_setup has been fully processed.
    // Verify the migration achieved its mandatory goals.

    // Root-level structure
    for dir in ["/root/.git", "/root/.claude", "/root/agent"] {
        exec_in_container(&container, &format!("test -d {dir}"))
            .unwrap_or_else(|_| panic!("expected directory {dir} after migration"));
    }

    // Agent subdirectories
    for dir in [
        "/root/agent/data",
        "/root/agent/logs",
        "/root/agent/notifications",
        "/root/agent/prompts",
        "/root/agent/skills",
    ] {
        exec_in_container(&container, &format!("test -d {dir}"))
            .unwrap_or_else(|_| panic!("expected directory {dir} after migration"));
    }

    // Old content must have been moved into ~/agent/
    exec_in_container(&container, "test -f /root/agent/prompts/custom.md")
        .expect("custom prompt should be migrated to ~/agent/prompts/");

    // ~/vesta/ must be gone — the prompt says "remove ~/vesta/ entirely"
    assert!(
        exec_in_container(&container, "test -d /root/vesta").is_err(),
        "~/vesta should not exist after migration"
    );

    // Git state
    let toplevel = exec_in_container(&container, "git -C /root rev-parse --show-toplevel").unwrap();
    assert_eq!(toplevel, "/root");

    let branch = exec_in_container(&container, "git -C /root branch --show-current").unwrap();
    assert!(!branch.is_empty(), "should be on a branch");

    // .claude/skills symlink
    exec_in_container(&container, "test -L /root/.claude/skills")
        .expect(".claude/skills should be a symlink after migration");
}

/// Seed the container with an old-style layout and mark first_start as done
/// so the agent takes the restart path (which runs the migration prompt).
fn seed_old_layout(container: &str) {
    exec_in_container(container, r#"
        mkdir -p ~/vesta/agent/prompts ~/vesta/agent/skills ~/vesta/data ~/vesta/notifications
        echo 'old prompt' > ~/vesta/agent/prompts/custom.md
        echo 'old data' > ~/vesta/data/custom.txt
        mkdir -p ~/vesta/random-dir
        echo 'junk' > ~/vesta/random-dir/file.txt
        mkdir -p ~/agent/data
        echo '1' > ~/agent/data/first_start_done
    "#).expect("seed old layout");
}
