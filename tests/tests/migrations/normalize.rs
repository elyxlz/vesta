use vesta_tests::{docker_cmd, exec_in_container};

const TEST_IMAGE: &str = "debian:bookworm-slim";

fn create_helper_container(name: &str) -> String {
    let _ = docker_cmd(&["rm", "-f", name]);
    docker_cmd(&[
        "run", "-d", "--name", name, TEST_IMAGE, "sleep", "300",
    ])
    .expect("create helper container");
    name.to_string()
}

fn cleanup(name: &str) {
    let _ = docker_cmd(&["rm", "-f", name]);
}

/// Seed a realistic old layout: full repo at ~/vesta/ with agent/ inside,
/// plus repo-level files that should NOT end up in ~/agent/.
fn seed_realistic_old_layout(container: &str) {
    exec_in_container(
        container,
        r#"
        apt-get update -qq && apt-get install -y -qq git >/dev/null 2>&1

        # Old layout: full repo at ~/vesta/
        mkdir -p ~/vesta/agent/prompts ~/vesta/agent/skills/tasks ~/vesta/agent/data
        mkdir -p ~/vesta/agent/logs ~/vesta/agent/notifications ~/vesta/agent/dreamer
        echo 'custom restart' > ~/vesta/agent/prompts/restart.md
        echo 'my memory' > ~/vesta/agent/MEMORY.md
        echo 'session-123' > ~/vesta/agent/data/session_id

        # Repo-level files that should NOT be moved into ~/agent/
        echo '[package]' > ~/vesta/Cargo.toml
        echo 'lock' > ~/vesta/Cargo.lock
        echo 'FROM debian' > ~/vesta/Dockerfile
        echo '# Vesta' > ~/vesta/README.md
        echo 'MIT' > ~/vesta/LICENSE
        echo '#!/bin/bash' > ~/vesta/release.sh
        mkdir -p ~/vesta/cli ~/vesta/vestad ~/vesta/app

        # Old layout also had data/logs at ~/vesta/ root level
        mkdir -p ~/vesta/data ~/vesta/notifications
        echo 'old-data' > ~/vesta/data/events.txt

        # Initialize git repo (the marker the script checks)
        git -C ~/vesta init -q
        git -C ~/vesta config user.email test@test.com
        git -C ~/vesta config user.name test
        git -C ~/vesta add -A
        git -C ~/vesta commit -q -m init
    "#,
    )
    .expect("seed old layout");
}

/// Run the normalization script from vestad/src/migrations.rs.
/// We inline a copy here to test the actual logic.
fn run_normalize_script(container: &str) {
    // This must match LEGACY_LAYOUT_NORMALIZE_SCRIPT in vestad/src/migrations.rs
    exec_in_container(
        container,
        r#"set -euo pipefail
if [ -d /root/vesta/.git ] && [ ! -d /root/.git ]; then
  mkdir -p /root/agent
  shopt -s dotglob nullglob

  merge_dirs() {
    local src="$1" dst="$2"
    mkdir -p "$dst"
    for child in "$src"/* "$src"/.[!.]* "$src"/..?*; do
      [ -e "$child" ] || continue
      local name
      name="$(basename "$child")"
      if [ ! -e "$dst/$name" ]; then
        mv "$child" "$dst/"
      elif [ -d "$child" ] && [ -d "$dst/$name" ]; then
        merge_dirs "$child" "$dst/$name"
      fi
    done
    rmdir "$src" 2>/dev/null || true
  }

  # Only merge ~/vesta/agent/* contents into ~/agent/ — not repo-level files
  if [ -d /root/vesta/agent ]; then
    merge_dirs /root/vesta/agent /root/agent
  fi

  # Move agent-owned paths from ~/vesta/ root (old layouts stored data/logs/notifications here)
  for name in data logs notifications dreamer; do
    for path in /root/vesta/$name /root/$name; do
      [ -d "$path" ] || continue
      merge_dirs "$path" "/root/agent/$name"
    done
  done

  rm -rf /root/vesta
  rm -rf /root/agent/.claude
  mkdir -p /root/.claude
  ln -sfn ../agent/skills /root/.claude/skills

  rm -rf /root/.git
  git -C /root init
  git -C /root remote add origin https://github.com/elyxlz/vesta.git
  git -C /root sparse-checkout init --cone
  SKILL_DIRS=$(find /root/agent/skills -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sed 's|/root/||' | tr '\n' ' ')
  git -C /root sparse-checkout set agent/core agent/prompts agent/dreamer $SKILL_DIRS
  printf '%s\n' '/*' '!.gitignore' '!/agent/' > /root/.gitignore
fi
"#,
    )
    .expect("normalization script");
}

#[test]
fn normalize_legacy_layout_moves_agent_content_only() {
    let name = "test-normalize-layout";
    let container = create_helper_container(name);

    seed_realistic_old_layout(&container);
    run_normalize_script(&container);

    // ~/vesta/ must be gone
    assert!(
        exec_in_container(&container, "test -d /root/vesta").is_err(),
        "~/vesta should be removed"
    );

    // Agent content must be present
    exec_in_container(&container, "test -f /root/agent/prompts/restart.md")
        .expect("restart.md should be in agent/prompts/");
    exec_in_container(&container, "test -f /root/agent/MEMORY.md")
        .expect("MEMORY.md should be in agent/");
    exec_in_container(&container, "test -f /root/agent/data/session_id")
        .expect("session_id should be in agent/data/");

    // Data from ~/vesta/data/ should be merged into ~/agent/data/
    exec_in_container(&container, "test -f /root/agent/data/events.txt")
        .expect("events.txt should be merged from ~/vesta/data/");

    // Agent subdirectories
    for dir in ["prompts", "skills", "data", "logs", "notifications", "dreamer"] {
        exec_in_container(&container, &format!("test -d /root/agent/{dir}"))
            .unwrap_or_else(|_| panic!("~/agent/{dir} should exist"));
    }

    // Repo-level files must NOT be in ~/agent/
    for junk in ["Cargo.toml", "Cargo.lock", "Dockerfile", "README.md", "LICENSE", "release.sh"] {
        assert!(
            exec_in_container(&container, &format!("test -f /root/agent/{junk}")).is_err(),
            "repo file {junk} should NOT be in ~/agent/"
        );
    }

    // Repo-level directories must NOT be in ~/agent/
    for junk_dir in ["cli", "vestad", "app"] {
        assert!(
            exec_in_container(&container, &format!("test -d /root/agent/{junk_dir}")).is_err(),
            "repo dir {junk_dir} should NOT be in ~/agent/"
        );
    }

    // No nested agent/agent/
    assert!(
        exec_in_container(&container, "test -d /root/agent/agent").is_err(),
        "nested ~/agent/agent/ should NOT exist"
    );

    // Git repo at /root
    let toplevel = exec_in_container(&container, "git -C /root rev-parse --show-toplevel")
        .expect("git toplevel");
    assert_eq!(toplevel, "/root");

    // Skills symlink
    exec_in_container(&container, "test -L /root/.claude/skills")
        .expect(".claude/skills symlink should exist");

    cleanup(name);
}
