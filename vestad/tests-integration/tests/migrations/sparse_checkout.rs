//! Architectural invariant: only *installed* skills are visible on disk and
//! in `git status`. Uninstalled skills shipped by upstream live in
//! `agent/skills/index.json` (so the agent can discover them via
//! `skills-search`) but their directories must not land in the worktree until
//! the user runs `skills-install`.
//!
//! These tests exercise the sparse-checkout pattern set up by
//! `agent/skills/upstream-sync/SETUP.md` ("## 1. Init") and the install /
//! merge flows that the agent runs over time. The bash blocks here mirror
//! that file; if SETUP.md changes, update them in lockstep.

use vesta_tests::{docker_cmd, exec_in_container};

const TEST_IMAGE: &str = "debian:bookworm-slim";

fn create_helper_container(name: &str) -> String {
    let _ = docker_cmd(&["rm", "-f", name]);
    docker_cmd(&["run", "-d", "--name", name, TEST_IMAGE, "sleep", "600"])
        .expect("create helper container");
    name.to_string()
}

fn cleanup(name: &str) {
    let _ = docker_cmd(&["rm", "-f", name]);
}

/// Install git, configure identity, and seed a fake upstream repo at
/// `/srv/upstream` with three skills + an index.json that lists all of them.
fn install_git_and_seed_upstream(container: &str) {
    exec_in_container(
        container,
        r#"set -euo pipefail
        apt-get update -qq && apt-get install -y -qq git >/dev/null 2>&1
        git config --global user.email upstream@test
        git config --global user.name upstream
        git config --global init.defaultBranch master

        mkdir -p /srv/upstream/agent/skills/skills-registry \
                 /srv/upstream/agent/skills/dashboard \
                 /srv/upstream/agent/skills/extra
        echo registry  > /srv/upstream/agent/skills/skills-registry/SKILL.md
        echo dashboard > /srv/upstream/agent/skills/dashboard/SKILL.md
        echo extra     > /srv/upstream/agent/skills/extra/SKILL.md
        cat > /srv/upstream/agent/skills/index.json <<'EOF'
[
  {"name": "skills-registry", "description": "registry"},
  {"name": "dashboard",       "description": "dashboard"},
  {"name": "extra",           "description": "extra"}
]
EOF
        echo "*.tmp" > /srv/upstream/agent/.gitignore
        git -C /srv/upstream init -q -b master
        git -C /srv/upstream add .
        git -C /srv/upstream commit -qm "v1"
    "#,
    )
    .expect("seed upstream");
}

/// Mimic the Dockerfile prune (vestad/Dockerfile:23-26): the image ships only
/// default skills under `/root/agent/skills/`. Here `skills-registry` and
/// `dashboard` are the defaults; `extra` is non-default and so is absent from
/// disk at boot, even though upstream has it.
fn seed_image_layout(container: &str) {
    exec_in_container(
        container,
        r#"set -euo pipefail
        mkdir -p /root/agent/skills/skills-registry /root/agent/skills/dashboard
        echo registry  > /root/agent/skills/skills-registry/SKILL.md
        echo dashboard > /root/agent/skills/dashboard/SKILL.md
    "#,
    )
    .expect("seed image layout");
}

/// Mirror of `agent/skills/upstream-sync/SETUP.md` "## 1. Init".
/// Anchors the sparse pattern to the defaults already on disk so future
/// merges don't pull in newly-added upstream skills.
const SETUP_INIT_SCRIPT: &str = r#"set -euo pipefail
cd /root
git init -q
git remote add origin /srv/upstream
git sparse-checkout init --no-cone
{
  printf '%s\n' '/agent/' '!/agent/core/' '!/agent/pyproject.toml' '!/agent/uv.lock' '!/agent/skills/*/' '/.gitignore'
  for d in agent/skills/*/; do
    [ -d "$d" ] && printf '/%s\n' "$d"
  done
} > .git/info/sparse-checkout
git config user.name agentname
git config user.email agentname@vesta
git checkout -b agentname
"#;

/// Mirror of SETUP.md "## 4. First merge".
const SETUP_FIRST_MERGE_SCRIPT: &str = r#"set -euo pipefail
cd /root
git fetch origin master -q
git merge --allow-unrelated-histories --no-edit -q FETCH_HEAD
"#;

/// `git status` is allowed to mention paths outside `agent/` (the debian
/// helper container leaves dotfiles in `/root` that the real agent ignores
/// via `~/agent/.gitignore`). What matters here is that nothing under
/// `agent/skills/` shows up — uninstalled skill dirs must not pollute the
/// porcelain output.
fn assert_no_skill_noise(container: &str, ctx: &str) {
    let porcelain = exec_in_container(
        container,
        "git -C /root status --porcelain --untracked-files=all -- agent/skills/",
    )
    .expect("git status");
    assert!(
        porcelain.is_empty(),
        "git status under agent/skills/ should be clean ({ctx}), got:\n{porcelain}"
    );
}

#[test]
#[cfg(target_os = "linux")]
fn sparse_checkout_scopes_skills_to_installed_only() {
    let name = "test-sparse-fresh";
    let c = create_helper_container(name);

    install_git_and_seed_upstream(&c);
    seed_image_layout(&c);
    exec_in_container(&c, SETUP_INIT_SCRIPT).expect("setup init");
    exec_in_container(&c, SETUP_FIRST_MERGE_SCRIPT).expect("first merge");

    // --- After fresh setup ---
    // Default skills are on disk.
    exec_in_container(&c, "test -f /root/agent/skills/skills-registry/SKILL.md")
        .expect("skills-registry should be on disk");
    exec_in_container(&c, "test -f /root/agent/skills/dashboard/SKILL.md")
        .expect("dashboard should be on disk");
    // Uninstalled upstream skill is NOT on disk.
    assert!(
        exec_in_container(&c, "test -e /root/agent/skills/extra").is_err(),
        "extra (non-default) should NOT be on disk after fresh setup"
    );
    // Index file IS on disk and lists ALL upstream skills, installed or not.
    let index = exec_in_container(&c, "cat /root/agent/skills/index.json")
        .expect("read index.json");
    for expected in ["\"skills-registry\"", "\"dashboard\"", "\"extra\""] {
        assert!(
            index.contains(expected),
            "index.json should list {expected}, got:\n{index}"
        );
    }
    // No untracked / modified noise.
    assert_no_skill_noise(&c, "after fresh setup");

    // --- skills-install pulls a non-default skill onto disk ---
    // This is what `skills-registry/scripts/skills-install` does after
    // verifying the skill exists upstream.
    exec_in_container(&c, "git -C /root sparse-checkout add agent/skills/extra")
        .expect("skills-install extra");
    exec_in_container(&c, "test -f /root/agent/skills/extra/SKILL.md")
        .expect("extra should be on disk after install");
    assert_no_skill_noise(&c, "after skills-install");

    // --- Upstream adds a new skill; downstream sync must NOT bring it onto disk ---
    exec_in_container(
        &c,
        r#"set -euo pipefail
        cd /srv/upstream
        mkdir -p agent/skills/newone
        echo newone > agent/skills/newone/SKILL.md
        cat > agent/skills/index.json <<'EOF'
[
  {"name": "skills-registry", "description": "registry"},
  {"name": "dashboard",       "description": "dashboard"},
  {"name": "extra",           "description": "extra"},
  {"name": "newone",          "description": "added in v2"}
]
EOF
        git add .
        git commit -qm "v2 add newone"
    "#,
    )
    .expect("upstream v2");

    exec_in_container(
        &c,
        r#"set -euo pipefail
        cd /root
        git fetch origin master -q
        git merge --no-edit -q FETCH_HEAD
    "#,
    )
    .expect("downstream sync");

    // index.json reflects the new skill...
    let index_v2 = exec_in_container(&c, "cat /root/agent/skills/index.json")
        .expect("read index.json after sync");
    assert!(
        index_v2.contains("\"newone\""),
        "index.json should list 'newone' after upstream sync, got:\n{index_v2}"
    );
    // ...but the new skill is NOT on disk and not in git status.
    assert!(
        exec_in_container(&c, "test -e /root/agent/skills/newone").is_err(),
        "newone should NOT be on disk after upstream sync (architectural invariant)"
    );
    assert_no_skill_noise(&c, "after upstream sync");

    cleanup(name);
}

#[test]
#[cfg(target_os = "linux")]
fn upstream_sync_self_heal_narrows_old_broad_pattern() {
    // Existing agents were initialised with the broad pattern `/agent/`,
    // which checks out every upstream skill. The self-heal in SKILL.md step 1
    // detects this and rewrites the pattern to scope to currently-installed
    // skills, so the next merge doesn't pull in new uninstalled skills.
    let name = "test-sparse-selfheal";
    let c = create_helper_container(name);

    install_git_and_seed_upstream(&c);

    // Agent on the OLD broad pattern — every upstream skill ends up on disk.
    exec_in_container(
        &c,
        r#"set -euo pipefail
        cd /root
        git init -q
        git remote add origin /srv/upstream
        git sparse-checkout init --no-cone
        printf '/agent/\n!/agent/core/\n!/agent/pyproject.toml\n!/agent/uv.lock\n/.gitignore\n' > .git/info/sparse-checkout
        git config user.name agentname
        git config user.email agentname@vesta
        git checkout -b agentname
        git fetch origin master -q
        git merge --allow-unrelated-histories --no-edit -q FETCH_HEAD
    "#,
    )
    .expect("old-pattern setup");

    // Confirm the bug: every upstream skill is on disk.
    exec_in_container(&c, "test -d /root/agent/skills/extra")
        .expect("old broad pattern leaves extra on disk (expected pre-heal)");

    // Pretend the user uninstalled extra by removing the dir, leaving the
    // sparse pattern broad. Then run the self-heal block from
    // upstream-sync/SKILL.md step 1.
    exec_in_container(
        &c,
        r#"set -euo pipefail
        rm -rf /root/agent/skills/extra
        cd /root

        if ! grep -qx '!/agent/skills/\*/' .git/info/sparse-checkout 2>/dev/null; then
          INSTALLED=$(find /root/agent/skills -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -u)
          {
            printf '%s\n' '/agent/' '!/agent/core/' '!/agent/pyproject.toml' '!/agent/uv.lock' '!/agent/skills/*/' '/.gitignore'
            for s in $INSTALLED; do printf '/agent/skills/%s/\n' "$s"; done
          } > .git/info/sparse-checkout
          git sparse-checkout reapply
        fi
    "#,
    )
    .expect("self-heal");

    // Now upstream adds a new skill; the narrowed pattern keeps it off disk.
    exec_in_container(
        &c,
        r#"set -euo pipefail
        cd /srv/upstream
        mkdir -p agent/skills/postheal
        echo postheal > agent/skills/postheal/SKILL.md
        git add .
        git commit -qm "v2 add postheal"
    "#,
    )
    .expect("upstream v2");

    exec_in_container(
        &c,
        r#"set -euo pipefail
        cd /root
        git fetch origin master -q
        git merge --no-edit -q FETCH_HEAD
    "#,
    )
    .expect("downstream sync after self-heal");

    assert!(
        exec_in_container(&c, "test -e /root/agent/skills/postheal").is_err(),
        "postheal should NOT be on disk after self-heal narrows the pattern"
    );
    // The originally-installed skills survive.
    exec_in_container(&c, "test -f /root/agent/skills/skills-registry/SKILL.md")
        .expect("skills-registry should still be on disk after self-heal");
    exec_in_container(&c, "test -f /root/agent/skills/dashboard/SKILL.md")
        .expect("dashboard should still be on disk after self-heal");
    assert_no_skill_noise(&c, "after self-heal + sync");

    cleanup(name);
}
