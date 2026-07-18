//! Release-gated e2e: upgrade a real agent from the PREVIOUS released vestad to the current
//! checkout via an in-place self-update, and assert the agent survives and its migrations
//! converge.
//!
//! Why this exists: agent-state migrations (`agent/core/migrations/*.md`) run as prompts
//! against a real legacy filesystem when a fleet member updates. The in-process pytest suite
//! covers the migration *runner*, but only a live upgrade proves the new release actually
//! converges an old agent without breaking it.
//!
//! The upgrade is functionally identical to `vestad update` (`self_update::perform_update`)
//! minus systemd: the installed vestad binary is replaced in place via an atomic rename (exactly
//! what `self_replace` does) and the daemon is restarted. On the next startup the new binary
//! re-extracts its embedded core (`ensure_agent_code`, fingerprinted in `agent_code.rs`) and
//! `reconcile_containers` restarts the agent, which boots on the new core and runs the migration
//! runner. We drive that restart directly instead of through systemd, which the standalone test
//! daemon does not use. The update runs only AFTER first-start setup has fully settled.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use vesta_tests::{
    docker_cmd, download_released_vestad, dump_agent_diagnostics, exec_in_container, find_vestad,
    previous_released_tag, TestServerBuilder,
};

use super::common::{
    create_file_request, host_credentials_path, provision_and_settle, wait_for_file_contains,
    wait_until_alive_or_die, write_notification,
};

const AGENT_NAME: &str = "upgrade";
/// Generous bound on the whole post-update convergence: a cross-version rebuild snapshots the
/// container filesystem (minutes), then the agent boots on the new core and runs migration prompts
/// against real Claude (more minutes). Reconcile runs in the background, so the test polls through
/// all of it; this only has to not be hit in practice.
const MIGRATION_CONVERGE_TIMEOUT: Duration = Duration::from_secs(1200);
const MIGRATION_POLL_INTERVAL: Duration = Duration::from_secs(5);
const LOG_STREAM_POLL: Duration = Duration::from_secs(2);
const UPGRADE_PROBE_MARKER: &str = "/root/agent/e2e-test/upgrade-ok.txt";

#[test]
fn upgrade_from_previous_release_converges_migrations_and_keeps_agent_healthy() {
    if host_credentials_path().is_none() {
        eprintln!(
            "skipping upgrade e2e: CLAUDE_CREDENTIALS not set (no ~/.claude/.credentials.json)"
        );
        return;
    }

    // Source release (upgrade FROM): VESTA_UPGRADE_FROM overrides; otherwise the highest release
    // below the crate version — the version a fleet member runs before taking this build. No prior
    // release (or no network to discover one) -> nothing to test.
    let current = env!("CARGO_PKG_VERSION");
    let previous_tag = match env_tag("VESTA_UPGRADE_FROM") {
        Some(tag) => tag,
        None => match previous_released_tag(current) {
            Ok(Some(tag)) => tag,
            Ok(None) => {
                eprintln!("skipping upgrade e2e: no released version older than {current}");
                return;
            }
            Err(e) => {
                eprintln!("skipping upgrade e2e: could not resolve previous release ({e})");
                return;
            }
        },
    };
    let old_vestad = match download_released_vestad(&previous_tag) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("skipping upgrade e2e: could not download vestad {previous_tag} ({e})");
            return;
        }
    };

    // Target (upgrade TO): VESTA_UPGRADE_TO downloads that released vestad; otherwise the current
    // checkout's build (the default, and what the release gate uses). Kept alive for the run so
    // its extracted binary survives.
    let target_tag = env_tag("VESTA_UPGRADE_TO");
    let target_vestad = match &target_tag {
        Some(tag) => match download_released_vestad(tag) {
            Ok(v) => Some(v),
            Err(e) => {
                eprintln!("skipping upgrade e2e: could not download target vestad {tag} ({e})");
                return;
            }
        },
        None => None,
    };
    let new_vestad_bin: PathBuf = match &target_vestad {
        Some(v) => v.bin_path.clone(),
        None => find_vestad().expect("locate current vestad build"),
    };
    let target_label = target_tag.clone().unwrap_or_else(|| current.to_string());
    eprintln!("upgrade e2e: {previous_tag} -> {target_label}");

    // This test runs alongside the shared live pool (full `cargo test --test live`). The pool's
    // SERVER runs one-time orphan cleanups at init (kill_orphan_vestads targets /tmp-home
    // vestads; cleanup_orphan_test_containers targets `-t{pid}-` users / `test-e2e-` names). Keep
    // our resources OUT of both patterns so a concurrent SERVER init can't wipe them mid-run: a
    // home under the cargo target tmpdir (not /tmp) and a user containing neither `-t<digit>` nor
    // `test-e2e-`. We do our own cleanup instead.
    remove_stale_upgrade_containers();
    let home =
        tempfile::TempDir::new_in(env!("CARGO_TARGET_TMPDIR")).expect("create persistent home");
    let user = format!("upgrade-e2e-{}", std::process::id());

    // The downloaded old binary's path is the "installed" vestad: the update replaces this exact
    // file and every daemon (old then new) runs from it, so the install location never moves —
    // exactly like a real self-update on a host.
    let installed_vestad = old_vestad.bin_path.clone();

    // ── Old version: a faithful v{N-1} fleet member ──────────────────────────────────────────
    // Clear VESTAD_AGENT_IMAGE so the old vestad uses its OWN released image (matching its
    // embedded core + lockfile), not the checkout's image.
    let old_server = TestServerBuilder::new()
        .user(&user)
        .home(home.path().to_path_buf())
        .vestad_bin(installed_vestad.clone())
        .env_remove("VESTAD_AGENT_IMAGE")
        .start()
        .expect("start old vestad");

    let old_client = old_server.client();
    let agent_name = old_client
        .create_agent(AGENT_NAME)
        .expect("create agent on old vestad");
    // Address the agent by its stable container NAME, never the id from agent_status: reconcile
    // may REBUILD the container on the update (snapshot + recreate -> new id), and migration
    // prompts restart it, so any cached id goes stale. The name survives restarts and rebuilds.
    let container = format!("vesta-{user}-{agent_name}");

    // Stream the agent's own log to the test output for the whole run; survives every restart.
    let _log_stream = AgentLogStream::start(&container);

    provision_and_settle(&old_client, &agent_name, &container);
    let pre_applied = applied_migrations(&container);
    eprintln!(
        "upgrade e2e: setup complete on {previous_tag}; {} migration(s) pre-applied",
        pre_applied.len()
    );

    // Seed the credential-loss precondition a fresh agent lacks (tracked .claude + an untracked
    // sentinel in ~/.claude), so the upgrade boot's guard would delete it absent the fix.
    seed_tracked_claude_precondition(&container);

    // ── The update: replace the installed binary in place, then restart the daemon ────────────
    // Functionally identical to `vestad update` (perform_update) without systemd: self_replace the
    // binary, then restart. The old daemon is still running from the file; an atomic rename over
    // it is safe (the running process keeps the old inode), just as self_replace relies on.
    eprintln!("upgrade e2e: replacing installed vestad with {target_label} and restarting");
    install_vestad_binary(&new_vestad_bin, &installed_vestad);
    drop(old_client);
    drop(old_server);

    // Restart the daemon from the SAME installed path — now the new binary. On startup it
    // re-extracts the new core and reconcile_containers restarts the agent onto it.
    let new_server = TestServerBuilder::new()
        .user(&user)
        .home(home.path().to_path_buf())
        .vestad_bin(installed_vestad.clone())
        .start()
        .expect("restart vestad after update");
    let new_client = new_server.client();

    // The new vestad runs reconcile (and any rebuild) in the BACKGROUND (serve.rs), and a
    // cross-version rebuild snapshots the container's filesystem — minutes. So don't gate on an
    // early "alive": that would pass against the OLD agent before reconcile even stops it. The real
    // end state is the agent back on the NEW core with its migrations applied. Take the expected set
    // from the host agent-code the new vestad extracted at startup (stable; the container is
    // mid-rebuild and answers nothing). wait_for_migrations_applied polls through the whole rebuild.
    let expected = host_core_migrations(home.path());
    assert!(
        !expected.is_empty(),
        "new core ships no migrations — host agent-code path is wrong"
    );
    wait_for_migrations_applied(home.path(), &container, &expected);
    wait_until_alive_or_die(&new_client, &agent_name, &container);

    // The agent must still do real work after the update, not just survive boot.
    write_notification(
        &container,
        &create_file_request(UPGRADE_PROBE_MARKER, "UPGRADED"),
        false,
    )
    .expect("send post-update probe");
    if let Err(e) = wait_for_file_contains(
        &container,
        UPGRADE_PROBE_MARKER,
        "UPGRADED",
        MIGRATION_CONVERGE_TIMEOUT,
    ) {
        dump_agent_diagnostics(&agent_name);
        panic!("agent did not process work after update: {e}");
    }

    // By now the upgrade boot has run the entrypoint .claude self-heal + migrations. The sentinel
    // under ~/.claude must have survived: if the guard untracked .claude but a later git op took
    // untracked files with it, real agents lose .credentials.json here.
    assert!(
        claude_sentinel_survives(&container),
        "an upgrade boot deleted the untracked sentinel under ~/.claude — \
         .credentials.json would be lost the same way (credential-loss regression)"
    );

    let converged = applied_migrations(&container);
    drop(new_client);
    drop(new_server);

    // ── Idempotency: a second boot must not re-run or thrash migrations ──────────────────────
    let rebooted_server = TestServerBuilder::new()
        .user(&user)
        .home(home.path().to_path_buf())
        .vestad_bin(installed_vestad.clone())
        .start()
        .expect("reboot vestad");
    let rebooted_client = rebooted_server.client();
    // Second boot needs no rebuild (the container already matches the current spec), just a
    // backgrounded restart; wait for the agent to come back rather than gating immediately.
    wait_until_alive_or_die(&rebooted_client, &agent_name, &container);

    let mut after_reboot = applied_migrations(&container);
    let mut converged_sorted = converged.clone();
    after_reboot.sort();
    converged_sorted.sort();
    assert_eq!(
        after_reboot, converged_sorted,
        "applied migrations changed on a clean reboot — migrations are not idempotent"
    );
    assert_eq!(
        pending_migration_notifications(&container),
        0,
        "a migration re-fired on a clean reboot — the agent would thrash on every restart"
    );

    let _ = rebooted_client.stop_agent(&agent_name);
    let _ = rebooted_client.destroy_agent(&agent_name);
}

/// Install `src` at `dst`, atomically. Mirrors `self_replace`: stage a copy next to the target,
/// then rename over it. The rename is safe even while a vestad is still running from `dst` (the
/// running process keeps the old inode; the path flips to the new one).
fn install_vestad_binary(src: &Path, dst: &Path) {
    let staged = dst.with_extension("incoming");
    fs::copy(src, &staged).expect("stage new vestad binary");
    fs::set_permissions(&staged, fs::Permissions::from_mode(0o755))
        .expect("make staged vestad executable");
    fs::rename(&staged, dst).expect("replace installed vestad binary");
}

/// Streams an agent container's `vesta.log` to the test's stderr in the background. Polls by
/// container NAME (stable across restarts/rebuilds) and prints only newly appended lines, so the
/// agent's first-start, migration runs, and reboots are all visible live under `--nocapture`.
struct AgentLogStream {
    stop: Arc<AtomicBool>,
    handle: Option<std::thread::JoinHandle<()>>,
}

impl AgentLogStream {
    fn start(container_name: &str) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let stop_flag = stop.clone();
        let name = container_name.to_string();
        let handle = std::thread::spawn(move || {
            let mut printed = 0usize;
            while !stop_flag.load(Ordering::Relaxed) {
                // `cat` fails (Err) when the container is mid-restart or the log doesn't exist yet;
                // just retry on the next tick.
                if let Ok(log) = docker_cmd(&["exec", &name, "cat", "/root/agent/logs/vesta.log"]) {
                    let lines: Vec<&str> = log.lines().collect();
                    if lines.len() < printed {
                        printed = 0; // log was rotated/truncated; re-stream from the top
                    }
                    for line in &lines[printed..] {
                        eprintln!("[agent] {line}");
                    }
                    printed = lines.len();
                }
                std::thread::sleep(LOG_STREAM_POLL);
            }
        });
        Self {
            stop,
            handle: Some(handle),
        }
    }
}

impl Drop for AgentLogStream {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

/// Remove any agent container left by a previous upgrade-test run. These use a `upgrade-e2e-*`
/// name that the shared harness orphan cleanup deliberately ignores, so the upgrade test owns
/// its own hygiene.
fn remove_stale_upgrade_containers() {
    let Ok(list) = docker_cmd(&[
        "ps",
        "-aq",
        "--filter",
        "name=vesta-upgrade-e2e-",
        "--format",
        "{{.Names}}",
    ]) else {
        return;
    };
    for name in list.lines().map(str::trim).filter(|name| !name.is_empty()) {
        let _ = docker_cmd(&["rm", "-f", name]);
    }
}

/// The new core's migration set, read from the host agent-code the new vestad extracted at startup
/// (ensure_agent_code, before the background reconcile). This is the stable convergence target: the
/// container itself is unreadable through the rebuild (stopped, then snapshotted for minutes), so we
/// can't ask it. Path mirrors vestad's `<config_dir>/agent-code/core`.
fn host_core_migrations(home: &Path) -> Vec<String> {
    let dir = home.join(".config/vesta/vestad/agent-code/core/migrations");
    let Ok(entries) = std::fs::read_dir(&dir) else {
        return Vec::new();
    };
    let mut names: Vec<String> = entries
        .filter_map(|entry| entry.ok())
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter_map(|name| name.strip_suffix(".md").map(str::to_string))
        .collect();
    names.sort();
    names
}

/// Read a non-empty env override as a release tag (e.g. `VESTA_UPGRADE_FROM=v0.1.158`).
fn env_tag(key: &str) -> Option<String> {
    std::env::var(key)
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

/// Poll `state.json` until every expected migration is recorded as applied. Real Claude drives
/// this asynchronously after the update reboot, so it can take minutes.
fn wait_for_migrations_applied(home: &Path, container: &str, expected: &[String]) {
    let deadline = std::time::Instant::now() + MIGRATION_CONVERGE_TIMEOUT;
    loop {
        let applied = applied_migrations(container);
        let missing: Vec<&String> = expected.iter().filter(|m| !applied.contains(m)).collect();
        if missing.is_empty() {
            eprintln!("upgrade e2e: all {} migration(s) applied", expected.len());
            return;
        }
        if std::time::Instant::now() >= deadline {
            dump_upgrade_diagnostics(home, container);
            panic!("migrations did not converge after update; still pending: {missing:?}");
        }
        std::thread::sleep(MIGRATION_POLL_INTERVAL);
    }
}

/// On a failed update, print why: the updated vestad's own log (its reconcile decisions live
/// here), the container's state, and what the new core mount actually contains.
fn dump_upgrade_diagnostics(home: &Path, container_name: &str) {
    eprintln!("\n===== UPGRADE DIAGNOSTICS =====");
    match docker_cmd(&[
        "inspect",
        container_name,
        "--format",
        "status={{.State.Status}} exit={{.State.ExitCode}} restarts={{.RestartCount}}",
    ]) {
        Ok(state) => eprintln!("container {container_name}: {state}"),
        Err(e) => eprintln!("container {container_name}: inspect failed ({e})"),
    }
    // `docker logs` works even when the container has exited, so it shows WHY it stopped
    // (entrypoint `uv sync` failures, a crash on the new core, etc.).
    match docker_cmd(&["logs", "--tail", "60", container_name]) {
        Ok(out) => eprintln!("--- container logs (tail 60) ---\n{out}"),
        Err(e) => eprintln!("container logs unavailable ({e})"),
    }
    match docker_cmd(&["exec", container_name, "sh", "-c", "ls /root/agent/core/migrations/ 2>&1; echo '--- core dir:'; ls /root/agent/core/ 2>&1 | head"]) {
        Ok(out) => eprintln!("core mount:\n{out}"),
        Err(e) => eprintln!("core mount: exec failed ({e}) — container not running"),
    }
    // Reconcile/rebuild decisions go to vestad's tracing on stdout; the banner is on stderr. Surface
    // the relevant lines from both so a failed rebuild (e.g. "[3/4] removing", a rebuild error) shows.
    for (label, file) in [
        ("stdout", "vestad-stdout.log"),
        ("stderr", "vestad-stderr.log"),
    ] {
        match fs::read_to_string(home.join(file)) {
            Ok(content) => {
                let relevant: Vec<&str> = content
                    .lines()
                    .filter(|l| {
                        [
                            "reconcile",
                            "rebuild",
                            "[1/4]",
                            "[2/4]",
                            "[3/4]",
                            "[4/4]",
                            "restart",
                            "agent code",
                            "stopped",
                            "starting",
                            "still present",
                            "error",
                            "ERROR",
                            "WARN",
                        ]
                        .iter()
                        .any(|k| l.contains(k))
                    })
                    .collect();
                if !relevant.is_empty() {
                    eprintln!("--- updated vestad {label} (reconcile) ---");
                    for line in relevant.iter().rev().take(40).rev() {
                        eprintln!("{line}");
                    }
                }
            }
            Err(e) => eprintln!("vestad {label} unreadable ({e})"),
        }
    }
    eprintln!("===== END DIAGNOSTICS =====\n");
}

/// A sentinel untracked file inside the agent's runtime ~/.claude, standing in for
/// .credentials.json — the exact file the credential-loss bug deleted.
const CLAUDE_SENTINEL: &str = "/root/.claude/e2e-credential-sentinel";

/// Recreate the precondition that made real agents lose their credentials on upgrade, which a
/// fresh test agent never has on its own: a $HOME git workspace that TRACKS a file under .claude/
/// (months of upstream-sync merges pull the repo's dev .claude/ tooling into tracking), with the
/// agent's live credentials sitting untracked alongside it. Left tracked, a later git op on the
/// upgrade boot can delete the untracked credentials alongside it. We drop a sentinel in ~/.claude
/// and assert post-upgrade that it survived. Without the entrypoint's boot-time untrack this
/// reproduces the de-auth; with it the sentinel is preserved.
fn seed_tracked_claude_precondition(container: &str) {
    // Ensure a plain $HOME git repo deterministically, then track a .claude file and drop the
    // untracked sentinel, so the precondition holds regardless of the old version's first-start timing.
    let script = "set -e; cd /root; \
        [ -d .git ] || git init -q; \
        mkdir -p .claude/skills/e2e-dev-skill; \
        printf 'dev tooling\\n' > .claude/skills/e2e-dev-skill/SKILL.md; \
        git add -f .claude/skills/e2e-dev-skill/SKILL.md; \
        git -c user.email=e2e@vesta -c user.name=e2e commit -q -m 'e2e: simulate tracked dev .claude tooling'; \
        printf 'SENTINEL\\n' > /root/.claude/e2e-credential-sentinel; \
        git ls-files -- .claude";
    let tracked = exec_in_container(container, script).expect("seed tracked .claude precondition");
    assert!(
        tracked.contains(".claude/skills/e2e-dev-skill/SKILL.md"),
        "precondition not established — .claude is not tracked: {tracked}"
    );
}

/// True iff the sentinel untracked file in ~/.claude still exists — i.e. an upgrade-boot reapply
/// did not delete untracked files under .claude (the credential-loss regression).
fn claude_sentinel_survives(container: &str) -> bool {
    exec_in_container(
        container,
        &format!("test -f {CLAUDE_SENTINEL} && echo yes || echo no"),
    )
    .map(|out| out.trim() == "yes")
    .unwrap_or(false)
}

/// The `applied_migrations` list from the agent's persisted state (empty when state.json or the
/// field is absent — both mean "nothing applied yet").
fn applied_migrations(container: &str) -> Vec<String> {
    let raw = exec_in_container(
        container,
        "cat /root/agent/data/state.json 2>/dev/null || echo '{}'",
    )
    .unwrap_or_else(|_| "{}".to_string());
    let value: serde_json::Value =
        serde_json::from_str(raw.trim()).unwrap_or(serde_json::Value::Null);
    value
        .get("applied_migrations")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|x| x.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

/// Count of undelivered migration notification files. Nonzero after a settled boot means a
/// migration re-fired even though it was already applied.
fn pending_migration_notifications(container: &str) -> usize {
    docker_cmd(&[
        "exec",
        container,
        "bash",
        "-lc",
        "ls /root/agent/notifications/migration-*.json 2>/dev/null | wc -l",
    ])
    .ok()
    .and_then(|out| out.trim().parse().ok())
    .unwrap_or(0)
}
