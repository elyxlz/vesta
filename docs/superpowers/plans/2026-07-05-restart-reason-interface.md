# Restart-reason interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let external actors (vestad backup, mount grants, the app) attach a human restart reason the agent surfaces on boot, and standardize all restart-reason copy + the boot message.

**Architecture:** One store (`state.persisted.last_restart_reason`) plus a transient host→container inbox file (`pending_restart_reason`) that vestad writes and the agent drains into that store on boot. Every reason is a `category: detail` string; the boot turn renders as `[System Restart] / Reason: {detail}`.

**Tech Stack:** Python 3 async agent (`uv`), Rust (`vestad`, bollard/axum), docker `cp` via existing `docker_cp_content`.

## Global Constraints

- Python: always `uv run`; no `getattr`/dict `.get()`/`hasattr`; functional (no classes-with-methods); line length 144; `%`-style logging.
- Rust: no `unwrap`/`expect`/`panic!` on fallible paths; named consts for literals; descriptive names.
- Copy: no em-dash (`—`) or en-dash (`–`) in `agent/core/prompts/**` or `agent/skills/**/SKILL.md` (CI `test_deployment.py`). Keep reason strings ASCII-hyphen only.
- Brand voice: never gender Vesta; the agent is addressed as "you" in these strings, which is fine.
- Reason contract: every reason is `"<category>: <detail>"`; `category` ∈ {`clean`,`nightly`,`crash`,`error`,`backup`,`mounts`,`manual`}; `detail` is lowercase, no trailing period, no dash.
- Inbox file path (both sides must agree): container path `/root/agent/data/pending_restart_reason`.

---

### Task 1: Standardize the reason copy (agent constants + call sites)

**Files:**
- Modify: `agent/core/models.py:54-57`
- Modify: `agent/core/main.py:84,90,93` (crash strings)
- Modify: `agent/core/loops.py:224,246` (error strings)
- Test: `agent/tests/test_processor.py` (new assertion near `test_restart_reason_round_trip`)

**Interfaces:**
- Produces: standardized reason constants `CLEAN_RESTART`, `NIGHTLY_RESTART`, `CRASH_RESTART` and the `crash:`/`error:` prefixes consumed by `_is_crash_reason` and by Task 2's renderer.

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_processor.py`:

```python
def test_reason_constants_follow_category_detail_shape():
    from core import models as vm

    for const in (vm.CLEAN_RESTART, vm.NIGHTLY_RESTART, vm.CRASH_RESTART):
        assert ": " in const, f"{const!r} must be 'category: detail'"
        category = const.split(": ", 1)[0]
        assert category in {"clean", "nightly", "crash", "error"}, category
        assert "—" not in const and "–" not in const
    assert vm.CLEAN_RESTART == "clean: routine restart, no specific reason"
    assert vm.NIGHTLY_RESTART == "nightly: the dreamer ran and compacted your session for continuous context"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && uv run pytest tests/test_processor.py::test_reason_constants_follow_category_detail_shape -v`
Expected: FAIL (`CLEAN_RESTART` is still `"restart: clean restart"`).

- [ ] **Step 3: Standardize the constants and inline strings**

`agent/core/models.py` (lines 54-56; leave `FIRST_START_REASON` as is):

```python
CLEAN_RESTART = "clean: routine restart, no specific reason"
NIGHTLY_RESTART = "nightly: the dreamer ran and compacted your session for continuous context"
CRASH_RESTART = "crash: restarted after an unexpected exit"
```

`agent/core/main.py` — update the three crash strings to conversational detail (keep the `crash:` prefix):
- line 84: `state.persisted.last_restart_reason = "crash: the processor was cancelled unexpectedly"`
- line 90: `state.persisted.last_restart_reason = f"crash: {type(exc).__name__}: {exc}"`  *(unchanged — already conformant)*
- line 93: `state.persisted.last_restart_reason = "crash: the processor exited silently"`

`agent/core/loops.py` — error strings (keep `error:` prefix):
- line 224: `state.persisted.last_restart_reason = "error: a turn was cancelled"`
- line 246: `state.persisted.last_restart_reason = f"error: {error_msg}"`  *(unchanged)*

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && uv run pytest tests/test_processor.py::test_reason_constants_follow_category_detail_shape -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/core/models.py agent/core/main.py agent/core/loops.py agent/tests/test_processor.py
git commit -m "refactor(agent): standardize restart reasons to category: detail"
```

---

### Task 2: New boot-message render (`[System Restart]` / `Reason:`)

**Files:**
- Modify: `agent/core/helpers.py:21-28` (`build_restart_context`)
- Modify: `agent/core/prompts/restart.md`
- Test: `agent/tests/test_processor.py`

**Interfaces:**
- Consumes: the `category: detail` reason strings from Task 1.
- Produces: `build_restart_context(reason, config, *, extras)` rendering `[System Restart]\nReason: {detail}\n\n{extras}\n\n{restart.md}`.

- [ ] **Step 1: Write the failing test**

```python
def test_build_restart_context_renders_system_restart_header(tmp_path):
    from core import helpers, models as vm
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    # core_prompts_dir == agent_dir/core/prompts; write a stand-in restart.md so load_prompt resolves.
    config.core_prompts_dir.mkdir(parents=True, exist_ok=True)
    (config.core_prompts_dir / "restart.md").write_text("Read the `restart` skill and follow it.\n")

    out = helpers.build_restart_context(
        "nightly: the dreamer ran and compacted your session for continuous context", config
    )
    assert out.startswith(
        "[System Restart]\nReason: the dreamer ran and compacted your session for continuous context"
    )
    assert out.endswith("Read the `restart` skill and follow it.")
    # a reason without a category prefix renders whole
    out2 = helpers.build_restart_context("first start", config)
    assert "Reason: first start" in out2
```

Also verify the shipped prompt was trimmed:

```python
def test_shipped_restart_prompt_has_no_redundant_restarted_line():
    import pathlib
    text = (pathlib.Path(__file__).parents[1] / "core" / "prompts" / "restart.md").read_text()
    assert "You've restarted" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && uv run pytest tests/test_processor.py::test_build_restart_context_renders_system_restart_header -v`
Expected: FAIL (current output is `[System: nightly: ...]`).

- [ ] **Step 3: Implement the render + trim restart.md**

`agent/core/helpers.py` replace `build_restart_context`:

```python
def build_restart_context(reason: str, config: vm.VestaConfig, *, extras: list[str] | None = None) -> str:
    # Reasons are stored as "category: detail"; the category is an internal tag (drives the
    # crash exit-code path), so show only the human detail under a clear restart header.
    detail = reason.split(": ", 1)[1] if ": " in reason else reason
    parts = [f"[System Restart]\nReason: {detail}"]
    if extras:
        parts.extend(extras)
    greeting = load_prompt("restart", config) or ""
    if greeting.strip():
        parts.append(greeting.strip())
    return "\n\n".join(parts)
```

`agent/core/prompts/restart.md` — drop the redundant lead sentence (first line becomes):

```
Read the `restart` skill and follow it.
```

(Leave the rest of `restart.md` unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && uv run pytest tests/test_processor.py::test_build_restart_context_renders_system_restart_header -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/core/helpers.py agent/core/prompts/restart.md agent/tests/test_processor.py
git commit -m "feat(agent): render boot reason as [System Restart] / Reason:"
```

---

### Task 3: Drain the `pending_restart_reason` inbox on boot

**Files:**
- Modify: `agent/core/state_store.py` (add path + take helper)
- Modify: `agent/core/main.py:218-225` (`_consume_restart_reason`)
- Test: `agent/tests/test_processor.py`

**Interfaces:**
- Consumes: `config.data_dir`.
- Produces: `state_store.take_pending_reason(config) -> str | None` (reads + unlinks the inbox), and `_consume_restart_reason` draining it into `last_restart_reason`.

- [ ] **Step 1: Write the failing test**

```python
def test_consume_restart_reason_drains_pending_inbox(tmp_path):
    from core import state_store, models as vm
    from core.main import _consume_restart_reason
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    state = vm.State()
    state.persisted.last_restart_reason = vm.CLEAN_RESTART

    # No inbox -> existing behavior (returns the persisted reason).
    assert _consume_restart_reason(state, config, first_start=False) == vm.CLEAN_RESTART

    # Inbox present -> it wins and the file is removed one-shot.
    state.persisted.last_restart_reason = vm.CLEAN_RESTART
    (config.data_dir / "pending_restart_reason").write_text("mounts: you now have read-only access to /media/Plex\n")
    got = _consume_restart_reason(state, config, first_start=False)
    assert got == "mounts: you now have read-only access to /media/Plex"
    assert not (config.data_dir / "pending_restart_reason").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && uv run pytest tests/test_processor.py::test_consume_restart_reason_drains_pending_inbox -v`
Expected: FAIL (`take_pending_reason` undefined / inbox ignored).

- [ ] **Step 3: Implement the path + drain**

`agent/core/state_store.py` add near `state_path`:

```python
PENDING_REASON_FILENAME = "pending_restart_reason"


def pending_reason_path(config: cfg.VestaConfig) -> pl.Path:
    return config.data_dir / PENDING_REASON_FILENAME


def take_pending_reason(config: cfg.VestaConfig) -> str | None:
    """Read + delete the one-shot restart-reason inbox vestad may have written before this boot.

    Returns the stripped reason, or None if absent. The file is transport, not storage: it is
    drained into last_restart_reason and removed so it never re-fires on a later boot."""
    path = pending_reason_path(config)
    if not path.exists():
        return None
    reason = path.read_text(encoding="utf-8").strip()
    path.unlink(missing_ok=True)
    return reason or None
```

`agent/core/main.py` — update `_consume_restart_reason`:

```python
def _consume_restart_reason(state: vm.State, config: vm.VestaConfig, *, first_start: bool) -> str:
    """Return the reason to log for this boot and clear it from persisted state. On a never-run agent the absence of a stored reason is innocent; report FIRST_START_REASON instead of a misleading crash label."""
    if first_start:
        return vm.FIRST_START_REASON
    pending = state_store.take_pending_reason(config)
    if pending is not None:
        # An external actor (vestad backup/mounts/manual) handed in a reason for this boot.
        state.persisted.last_restart_reason = pending
    stored = state.persisted.last_restart_reason
    state.persisted.last_restart_reason = None
    state_store.save_state(state.persisted, config)
    return stored or vm.CRASH_RESTART
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && uv run pytest tests/test_processor.py::test_consume_restart_reason_drains_pending_inbox -v`
Expected: PASS.

- [ ] **Step 5: Run the whole agent suite gate**

Run: `cd agent && uv run pytest tests/test_processor.py -q`
Expected: PASS (no regressions in the existing restart-reason round-trip).

- [ ] **Step 6: Commit**

```bash
git add agent/core/state_store.py agent/core/main.py agent/tests/test_processor.py
git commit -m "feat(agent): drain pending_restart_reason inbox into the boot reason"
```

---

### Task 4: vestad `write_pending_restart_reason` helper + route backup through it

**Files:**
- Modify: `vestad/src/docker.rs` (near `docker_cp_content` @ 1530)
- Modify: `vestad/src/backup.rs:106-119`
- Test: `vestad/src/docker.rs` (unit: const value)

**Interfaces:**
- Produces: `pub(crate) const PENDING_RESTART_REASON_PATH: &str` and `pub(crate) async fn write_pending_restart_reason(docker: &Docker, cname: &str, reason: &str) -> Result<(), DockerError>`.

- [ ] **Step 1: Write the failing test**

Add to the `#[cfg(test)]` module in `vestad/src/docker.rs`:

```rust
#[test]
fn pending_restart_reason_path_matches_agent_contract() {
    assert_eq!(super::PENDING_RESTART_REASON_PATH, "/root/agent/data/pending_restart_reason");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vestad && VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad --bin vestad pending_restart_reason_path -- --nocapture`
Expected: FAIL to compile (const undefined).

- [ ] **Step 3: Add the helper and const**

`vestad/src/docker.rs` just above `docker_cp_content`:

```rust
/// One-shot inbox the agent drains on its next boot (see agent `state_store.take_pending_reason`).
/// Written before a stop/recreate so the reason survives into the next boot; plain text, no schema.
pub(crate) const PENDING_RESTART_REASON_PATH: &str = "/root/agent/data/pending_restart_reason";

/// Write `reason` into the agent's boot inbox. Best-effort at the call site: a failed write only
/// costs a missing greeting line, never the restart itself.
pub(crate) async fn write_pending_restart_reason(docker: &Docker, cname: &str, reason: &str) -> Result<(), DockerError> {
    docker_cp_content(docker, cname, reason, PENDING_RESTART_REASON_PATH).await
}
```

- [ ] **Step 4: Route backup through the helper (standardized copy, new path)**

`vestad/src/backup.rs` replace the inline `docker_cp_content(...)` block (106-119) with:

```rust
        tracing::info!(agent = %name, "stopping agent for backup");
        if let Err(err) = write_pending_restart_reason(docker, &cname, "backup: you were paused for a scheduled backup").await {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
        stop_container_with_timeout(docker, &cname, BACKUP_STOP_TIMEOUT_SECS).await.ok();
```

Update the import at `vestad/src/backup.rs:7` — replace `docker_cp_content` with `write_pending_restart_reason`.

- [ ] **Step 5: Run test + compile**

Run: `cd vestad && VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad --bin vestad pending_restart_reason_path`
Expected: PASS. Then `VESTAD_SKIP_APP_BUILD=1 cargo check -p vestad` → clean.

- [ ] **Step 6: Commit**

```bash
git add vestad/src/docker.rs vestad/src/backup.rs
git commit -m "feat(vestad): write_pending_restart_reason helper; route backup through it"
```

---

### Task 5: Mount-change reason generator (pure)

**Files:**
- Modify: `vestad/src/mounts.rs`
- Test: `vestad/src/mounts.rs` (`#[cfg(test)]`)

**Interfaces:**
- Consumes: `actual: &[(String, String, bool)]` (container mounts as `(host, container, writable)`, from `docker::actual_user_mounts`) and `desired: &[HostMount]`.
- Produces: `pub fn mount_change_reason(actual: &[(String, String, bool)], desired: &[HostMount]) -> Option<String>` returning a `mounts: …` string or None if nothing changed.

- [ ] **Step 1: Write the failing tests**

Add to `vestad/src/mounts.rs` tests:

```rust
    fn m(c: &str, w: bool) -> HostMount {
        HostMount { host_path: c.into(), container_path: c.into(), writable: w }
    }

    #[test]
    fn mount_change_reason_grants_removals_and_mixed() {
        // single grant
        assert_eq!(
            mount_change_reason(&[], &[m("/media/Plex", false)]).as_deref(),
            Some("mounts: you now have access to /media/Plex (read-only)")
        );
        // multiple grants
        assert_eq!(
            mount_change_reason(&[], &[m("/media/Plex", false), m("/downloads", true)]).as_deref(),
            Some("mounts: you now have access to /media/Plex (read-only) and /downloads (read-write)")
        );
        // removal only
        assert_eq!(
            mount_change_reason(&[("/media/Plex".into(), "/media/Plex".into(), false)], &[]).as_deref(),
            Some("mounts: your access to /media/Plex was removed")
        );
        // mixed
        assert_eq!(
            mount_change_reason(
                &[("/old".into(), "/old".into(), false)],
                &[m("/media/Plex", false)]
            ).as_deref(),
            Some("mounts: filesystem access changed. granted: /media/Plex (read-only); removed: /old")
        );
        // no change
        assert_eq!(mount_change_reason(&[("/x".into(), "/x".into(), true)], &[m("/x", true)]), None);
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd vestad && VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad --bin vestad mount_change_reason`
Expected: FAIL to compile (function undefined).

- [ ] **Step 3: Implement the generator**

`vestad/src/mounts.rs`:

```rust
/// Join items as "a", "a and b", or "a, b and c" for human-readable reason copy.
fn join_and(items: &[String]) -> String {
    match items {
        [] => String::new(),
        [one] => one.clone(),
        [head @ .., last] => format!("{} and {}", head.join(", "), last),
    }
}

/// A `mounts:` restart reason describing a grant change, or None if nothing changed.
/// `actual` is the container's current user binds as (host, container, writable); `desired` is the
/// new grant list. Classification is by container_path; a writable flip reads as a fresh grant.
pub fn mount_change_reason(actual: &[(String, String, bool)], desired: &[HostMount]) -> Option<String> {
    let actual_set: std::collections::HashSet<(&str, bool)> =
        actual.iter().map(|(_, c, w)| (c.as_str(), *w)).collect();
    let actual_paths: std::collections::HashSet<&str> = actual.iter().map(|(_, c, _)| c.as_str()).collect();
    let desired_paths: std::collections::HashSet<&str> = desired.iter().map(|m| m.container_path.as_str()).collect();

    let mode = |w: bool| if w { "read-write" } else { "read-only" };

    let granted: Vec<String> = desired
        .iter()
        .filter(|mnt| !actual_set.contains(&(mnt.container_path.as_str(), mnt.writable)))
        .map(|mnt| format!("{} ({})", mnt.container_path, mode(mnt.writable)))
        .collect();
    let removed: Vec<String> = actual
        .iter()
        .filter(|(_, c, _)| !desired_paths.contains(c.as_str()))
        .map(|(_, c, _)| c.clone())
        .collect();
    let _ = actual_paths; // reserved for future writable-change wording

    match (granted.is_empty(), removed.is_empty()) {
        (true, true) => None,
        (false, true) => Some(format!("mounts: you now have access to {}", join_and(&granted))),
        (true, false) => Some(format!("mounts: your access to {} was removed", join_and(&removed))),
        (false, false) => Some(format!(
            "mounts: filesystem access changed. granted: {}; removed: {}",
            granted.join(", "),
            removed.join(", ")
        )),
    }
}
```

> Remove the unused `actual_paths`/`let _ =` lines if clippy flags them; they are only a hint for a future writable-change branch.

- [ ] **Step 4: Run to verify it passes**

Run: `cd vestad && VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad --bin vestad mount_change_reason`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vestad/src/mounts.rs
git commit -m "feat(vestad): mount-change restart-reason generator"
```

---

### Task 6: Thread the reason through `restart_agent` + optional `{reason}` API

**Files:**
- Modify: `vestad/src/docker.rs:1835-1862` (`restart_agent`)
- Modify: `vestad/src/serve.rs:634-655` (`restart_agent_handler`) + a `RestartBody` struct
- Test: `vestad/src/docker.rs` behavioral note (compile + existing docker-gated coverage)

**Interfaces:**
- Consumes: `write_pending_restart_reason` (Task 4), `mount_change_reason` (Task 5), `actual_user_mounts`/`user_mounts_drifted` (existing).
- Produces: `restart_agent(docker, name, env_config, user_mounts, reason: Option<String>)` and a handler accepting an optional `{ "reason": "manual: ..." }` body.

- [ ] **Step 1: Add `reason` param to `restart_agent` and write the inbox once**

Rewrite `vestad/src/docker.rs` `restart_agent` so it inspects once, picks the effective reason (caller-supplied wins; else mount-drift synthesized), writes it before any stop, then branches:

```rust
pub async fn restart_agent(
    docker: &Docker,
    name: &str,
    env_config: &AgentEnvConfig,
    user_mounts: &[crate::mounts::HostMount],
    reason: Option<String>,
) -> Result<(), DockerError> {
    validate_name(name)?;
    let cname = container_name(name);
    ensure_exists(docker, &cname).await?;

    let inspected = docker.inspect_container(&cname, None).await.ok();
    let drifted = inspected
        .as_ref()
        .map(|raw| user_mounts_drifted(&actual_user_mounts(raw), user_mounts))
        .unwrap_or(false);

    // Effective reason for this boot: an explicit caller reason wins; otherwise, if grants drifted,
    // synthesize one from the delta. Written before the container stops so it lands in the snapshot.
    let effective_reason = reason.or_else(|| {
        inspected
            .as_ref()
            .and_then(|raw| crate::mounts::mount_change_reason(&actual_user_mounts(raw), user_mounts))
    });
    if let Some(text) = &effective_reason {
        if let Err(err) = write_pending_restart_reason(docker, &cname, text).await {
            tracing::warn!(agent = %name, error = %err, "failed to write restart reason");
        }
    }

    if drifted {
        let available = docker_storage_available_bytes(docker).await;
        if reconcile_blocked_by_disk(available) {
            tracing::warn!(agent = %name, "mount grants changed but disk is critically low; skipping recreate, applying on next reconcile");
        } else {
            tracing::info!(agent = %name, "restart: mount grants drifted, recreating");
            rebuild_agent(docker, name, env_config, user_mounts).await?;
            return start_agent(docker, name).await;
        }
    }
    docker.restart_container(&cname, Some(RestartContainerOptions { t: Some(CONTAINER_RESTART_TIMEOUT_SECS), signal: None })).await?;
    Ok(())
}
```

- [ ] **Step 2: Update the handler to accept an optional reason**

`vestad/src/serve.rs` — add near the other body structs:

```rust
#[derive(Deserialize, Default)]
struct RestartBody {
    #[serde(default)]
    reason: Option<String>,
}
```

Change `restart_agent_handler` to take an optional body (last extractor) and thread it through the detached op. Signature + call:

```rust
async fn restart_agent_handler(
    State(state): State<SharedState>,
    Path(name): Path<String>,
    body: Option<Json<RestartBody>>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!(name = %name, "restarting agent");
    let reason = body.and_then(|Json(b)| b.reason);
    // Detached from this request's connection (see spawn_detached): a self-restart's client is the
    // agent inside the very container this stops.
    spawn_detached(async move {
        let _guard = agent_write_guard(&state, &name).await;
        {
            let mut settings = state.settings.write().await;
            settings.agents.entry(name.clone()).or_default().user_desired = UserDesired::Running;
            save_settings(&settings);
        }
        let user_mounts = {
            let settings = state.settings.read().await;
            settings.agents.get(&name).map(|s| s.mounts.clone()).unwrap_or_default()
        };
        docker::restart_agent(&state.docker, &name, &state.env_config, &user_mounts, reason)
            .await
            .map_err(map_docker_err)?;
        Ok(ok_json())
    })
    .await
}
```

- [ ] **Step 3: Fix other `restart_agent` call sites**

Run: `cd vestad && rg -n 'restart_agent\(' src | rg -v 'fn restart_agent|restart_agent_handler'`
For each caller not passing a reason, add a trailing `None`. Expected callers: none outside the handler — but verify; if any internal caller exists (e.g. provider flow), pass `None`.

- [ ] **Step 4: Compile + full vestad unit suite**

Run: `cd vestad && VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad --bin vestad`
Expected: PASS (168+ tests, including the earlier `restart_detach` test).

Run: `cd vestad && VESTAD_SKIP_APP_BUILD=1 cargo clippy -p vestad --all-targets -- -D warnings 2>&1 | rg -v '2994|assertions_on_constants' | tail`
Expected: no new warnings from these files (the pre-existing `assertions_on_constants` at serve.rs:2994 is unrelated).

- [ ] **Step 5: Commit**

```bash
git add vestad/src/docker.rs vestad/src/serve.rs
git commit -m "feat(vestad): attach restart reason (manual + mount delta) to the boot inbox"
```

---

### Task 7: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Agent checks**

Run: `./check.sh agent`
Expected: ruff + ty + pytest all green.

- [ ] **Step 2: vestad checks (skip web build)**

Run: `VESTAD_SKIP_APP_BUILD=1 ./check.sh vestad`
Expected: clippy clean (modulo the pre-existing serve.rs:2994 lint) + `cargo test -p vestad` green.

- [ ] **Step 3: Manual render sanity**

Run (from `agent/`, so `agent_dir=.` resolves `./core/prompts/restart.md`):
`cd agent && uv run python -c "from pathlib import Path; from core import helpers, models as vm; c=vm.VestaConfig(agent_dir=Path('.')); print(helpers.build_restart_context('mounts: you now have read-only access to /media/Plex', c))"`
Expected output begins:
```
[System Restart]
Reason: you now have read-only access to /media/Plex
```

- [ ] **Step 4: Commit any doc touch-ups, then open the stacked PR**

```bash
gh pr create --base feat/host-filesystem-grants --title "feat: external restart-reason interface" --body "<summary + 'stacked on #974; retarget to master after it merges'>"
```

## Self-Review notes

- Spec coverage: reader (Task 3), writer helper + backup (Task 4), mounts generator (Task 5), API `{reason}` + mount-drift wiring (Task 6), standardized copy (Task 1) + render (Task 2). All spec sections mapped.
- Out of scope (per spec): web app sending a `{reason}` on manual restart; richer structured reasons.
- Crash/exit path untouched: `_is_crash_reason` still reads the stored `crash:`/`error:` prefixed string; the render only strips the prefix for display.
