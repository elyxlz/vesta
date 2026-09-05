# Browser Daemon (PR 3: callers, skill docs, fleet migration, retirement) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every internal caller of the browser skill to `browser exec`, rewrite the skill's model-facing docs for the daemon, ship the fleet migration that installs the engines and daemon on every existing agent, and retire the last references to the old runtime.

**Architecture:** Maps sends one Python program per operation to `browser exec --session default` and parses `output.stdout`. Microsoft gets one Chromium session per account (`microsoft-<slug>`, standard mode): interactive sign-in through `browser handover start --session <name> --url <url>`, token capture and the unattended refresh through headless `browser exec`; the second call site in `auth_commands.py` folds into `capture.py`. `SKILL.md` and `SETUP.md` are rewritten under the `vesta-prompt-guide` skill to the spec's operational structure. One prompt migration converges the fleet. Stale prose across maps, flights, microsoft, MEMORY.md, and the domain recipes is corrected.

**Tech Stack:** Python 3.11+ (maps and microsoft CLIs), prompt migrations (`agent/core/migrations/*.md`), skill markdown.

**Spec:** `docs/superpowers/specs/2026-09-04-browser-daemon-design.md` (Internal callers, Skill documents, Packaging and fleet migration, Retired and kept).

**Base:** branch `feat/browser-callers`, stacked on `feat/browser-handover` (PR 2). Worktree `/home/emi/vesta-wt-browser-spec`.

## Global Constraints

- Plan 1's Global Constraints bind (Python conventions, one JSON line, no spaced dashes, "Vesta" for the agent, commit trailers `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01VWMfwWdkJHjAXDbAJjv5Kd`).
- Everything under `agent/` is read cold by Vesta: state the mechanism, never the previous design; no "now", "no longer", "new", "old"; imperative operational prose; load the `vesta-prompt-guide` skill before editing any `SKILL.md`, `SETUP.md`, migration, `MEMORY.md`, or recipe.
- `SKILL.md` `description` is discovery text (when to use, what triggers stealth), never a workflow summary. Body order: choose a mode; run one program (`browser exec --session <name> [--stealth] <<'PY' ... PY`); helpers on both engines (the `PORTABLE_HELPERS` list, one line per group); engine escape hatches (`cdp()` Chromium only, `page` Camoufox only, mismatch means change the code or start a new session, never replay in the other engine); read the result (`ok`/`error`, then `session.engine`, `page`, `artifacts`; a screenshot path is a file to read, not an image seen); handover (one command returns `user_url`; send that URL alone; `browser handover stop` when done; never share a local port); recovery (`browser doctor`, `browser engines`, `browser sessions`, `browser daemon start`). Raise the Bash timeout together with `--timeout`. No engine internals, pins, socket paths, or provider talk in `SKILL.md`.
- `SETUP.md` (read once at activation): `uv tool install --editable ~/agent/skills/browser/cli`; `uv sync --frozen --project ~/agent/skills/browser/engines/chromium` and `.../camoufox`; confirm `/usr/bin/chromium` and `/opt/camoufox/<tag>/camoufox` exist, else run `~/agent/skills/browser/install-engines.sh`; `browser daemon start`; add `browser daemon start` to `~/agent/skills/restart/daemons.sh` (the restart skill's file, one line, agent-edited); `browser doctor` shows both routes `ready`; runtime paths table; handover requirements (`VESTAD_PUBLIC_URL`, the four binaries and noVNC); recovery. Never instruct installing during a task.
- Microsoft: per-account session name `microsoft-<slug>` where `slug = email.lower()` with every non-alphanumeric character replaced by `_` (the skill's existing `_sanitize_filename` rule); Chromium engine (standard mode, no `--stealth`); the session's profile is daemon-owned (`~/agent/data/browser/profiles/chromium/microsoft-<slug>`), so `~/.microsoft/browser-profiles/` and `--user-data-dir` disappear; each account signs in once more through the new handover (a Firefox profile cannot become a Chromium one; the migration tells the user).
- Maps: `browser exec --session default` (Chromium); no `DISPLAY` forcing; `MAPS_BROWSER_BIN` stays as the binary override; parse `output.stdout` from the envelope; `ok: false` → `BrowserUnavailableError(error.message)`; `error.code == "daemon_down"` → the message names `browser daemon start`.
- Migration `agent/core/migrations/2026-09-browser-daemon.md` (after_sync, non-interruptible, idempotent, cumulative): run `~/agent/skills/browser/install-engines.sh`; `uv tool install --editable --force ~/agent/skills/browser/cli`; `uv sync --frozen --project` both engines; stop any old runtime (`pkill`-free: read `/proc/*/cmdline` for `vesta_browser.daemon` or `camoufox` launched from `~/.cache/camoufox`, SIGTERM those pids); remove `/tmp/vesta-browser-*`, `~/.cache/camoufox`, `~/.browser`; run `deregister-service browser` (the old runtime registered that service `--public`, and only a new registration or a deregistration flips it; the daemon re-registers it private on the next handover); replace any `browser` line in `daemons.sh` with `browser daemon start` (add if absent); `browser daemon start`; `browser doctor` and report `ready` for both routes; if `~/.microsoft/browser-profiles/` holds any account, tell the user each locked-tenant account needs `microsoft auth setup --account <email> --browser` again, then remove that directory; end with `Call mark_migration_applied with name="2026-09-browser-daemon"`.
- Tests: maps and microsoft suites keep their shims but the shims answer the `exec` envelope shape (one JSON line with `ok`, `output.stdout`); no test needs a real daemon.

---

## File structure

```
agent/skills/maps/cli/src/gmaps_cli/browser_bridge.py     Task 1
agent/skills/maps/cli/tests/{test_browser_bridge,test_cli}.py  Task 1 (shims)
agent/skills/maps/SKILL.md, SETUP.md                       Task 1 (prose)
agent/skills/microsoft/cli/src/microsoft_cli/capture.py    Task 2
agent/skills/microsoft/cli/src/microsoft_cli/auth_commands.py  Task 2 (fold the two closures)
agent/skills/microsoft/cli/tests/{test_owa_rest,test_teams,test_capture}.py  Task 2
agent/skills/microsoft/SKILL.md, SETUP.md                  Task 2 (prose)
agent/skills/browser/SKILL.md, SETUP.md                    Task 3 (rewrite)
agent/skills/browser/interaction-skills/*.md, domain-skills/*  Task 3 (stale command references)
agent/skills/flights/SKILL.md, agent/MEMORY.md             Task 4
agent/core/migrations/2026-09-browser-daemon.md            Task 4
docs/superpowers/specs/2026-09-04-browser-daemon-design.md Task 4 (Microsoft engine amendment)
```

---

### Task 1: Maps on `browser exec`

**Files:** `browser_bridge.py`, its two test files, `maps/SKILL.md` lines 106-136, `maps/SETUP.md` lines 34-38.

**Interfaces:** keep `entitylist_get(op, pb)`, `entitylist_write(op, build_pb)`, the three error classes, `MAPS_BROWSER_BIN`. Replace `_run(*args)` with `_exec(code: str) -> str` that runs `[browser_bin, "exec", "--session", "default"]` with `code` on stdin, no env changes, `check=False`; `FileNotFoundError` → `BrowserUnavailableError`; parse the single stdout or stderr line as JSON: when `ok` is false raise `BrowserUnavailableError(error["message"])` (prefix "start the browser daemon: " when `error["code"] == "daemon_down"`); return `output["stdout"].strip()`. Programs:

```python
_TAB_PROGRAM = """
tabs = [t for t in list_tabs() if t["url"].startswith("https://www.google.com/maps")]
if tabs:
    switch_tab(tabs[0]["target_id"])
else:
    new_tab("https://www.google.com/maps")
    wait_for_load()
"""
_FETCH_PROGRAM = _TAB_PROGRAM + 'import json\nprint(json.dumps(js({js!r})))\n'
```

where `js` is the existing `_FETCH_JS`/`_HTML_JS` expression (an async IIFE; `js()` on Browser Harness returns the awaited value). `_parse_envelope` stays and parses the printed JSON.

- [ ] Tests: update the shims to read stdin and print one envelope line: `{"schema":"browser.result.v1","ok":true,...,"output":{"stdout": <FAKE_EVAL_OUT or the HTML json>,"stderr":"","exit_code":0,"duration_ms":1}}`; the signed-out shim keys on `"maps/search/coffee" in code`; add a test where the shim prints an `ok: false` `daemon_down` envelope on stderr and exits 1 → `BrowserUnavailableError` naming `browser daemon start`; assert the shim received `exec --session default` and no `DISPLAY` was injected (shim dumps `argv` and `"DISPLAY" in os.environ` to a file).
- [ ] Prose: `SKILL.md` "Saved lists" section: same instructions with `browser handover start --url "<google sign-in>"` returning `user_url`, then `browser handover stop`; `SETUP.md`: "need the `browser` skill active and its daemon running (`browser daemon start`)".
- [ ] Run `uv run --project skills/maps/cli pytest skills/maps/cli/tests -q`, lint, guards; commit `refactor(skills/maps): drive google maps through browser exec`.

---

### Task 2: Microsoft on Chromium sessions

**Files:** `capture.py`, `auth_commands.py`, tests, `microsoft/SKILL.md:8`, `microsoft/SETUP.md` lines 45-105.

**Interfaces (capture.py):**
- `def session_name(account_email: str) -> str` → `f"microsoft-{slug}"` with the `_sanitize_filename` rule (import it from `email.py` or move the helper into a tiny shared module; no duplication).
- `def _exec(code: str, *, session: str, timeout: float = 120.0) -> str`: `browser exec --session <session> --timeout <int(timeout)>` with `code` on stdin, no env edits; parse the envelope exactly as maps does (share nothing across skills; each skill owns its copy, as the daemon-contract rule says); `ok: false` → `CaptureError(error["message"])`.
- `begin_interactive(config, account)`: `browser handover start --session <session_name> --url https://outlook.office.com/mail/ --minutes 30` → parse the envelope, return `data["user_url"]`. No `stop-all`, no `--user-data-dir`.
- `_harvest(session)`: `_exec(f'new_tab({MAIL_URL!r}); wait_for_load(); print(js({_MAIL_TOKEN_JS!r}))', session=...)` polled as today; same for Teams.
- `finish_interactive(config, account)`: `browser handover stop`, then `_harvest`; a failed harvest → `CaptureError("no signed-in browser session; ...")`.
- `refresh(config, account)`: `_harvest` only (headless). Remove `profile_dir`.
- `stop()`: `browser handover stop` only (idempotent).
- `auth_commands.py`: `_owa_login_browser` and `_teams_capture_browser` call `capture.capture_token(config, account, kind)` (a new small public function running the headless program for one target) instead of their own `_run` closures; the `sign_in_required` return shape stays.
- The microsoft daemon (`monitor.py`) is unchanged: `due_accounts`/`refresh_and_save` keep their signatures.

- [ ] Tests: `test_capture.py` gains `session_name` cases (`Alice@Example.com` → `microsoft-alice_example_com`) and an `_exec` envelope test with a shim; `test_owa_rest.py`/`test_teams.py` fakes move from `subprocess.run` patches keyed on `args[1] == "evaluate"` to patching `capture.capture_token`; `test_monitor.py` unchanged.
- [ ] Prose: `SETUP.md` lines 77-81: "driven by the agent through the `browser` skill (`browser exec`, a Chromium session per account)"; drop `DISPLAY=:99`; lines 56-59 keep the one-URL handover story; `SKILL.md:8` unchanged unless it names a command.
- [ ] Run `uv run --project skills/microsoft/cli pytest skills/microsoft/cli/tests -q`, lint, guards; commit `refactor(skills/microsoft): one chromium session per account through the browser daemon`.

---

### Task 3: Rewrite the browser skill docs

**Files:** `agent/skills/browser/SKILL.md` (full rewrite), `SETUP.md` (full rewrite), `interaction-skills/*.md` (drop `connection.md`, `remote-control.md`, rewrite `handover.md` to the daemon flow, fix any `browser <old verb>` in the others), `domain-skills/` (rewrite the 7 command references in `trip-com/booking.md`, `thetrainline/booking.md`, `1password-share/reading-shared-items.md` to `browser exec` programs; replace `browser-harness/1.0` User-Agent strings and `~/Developer/browser-harness` paths with neutral text).

- [ ] Load `vesta-prompt-guide`; write `SKILL.md` to the Global Constraints structure (the current body still teaches the public handover route and the deleted commands; nothing of it survives except the linked recipes) (target under 120 lines; the recipes stay as linked references at the end); write `SETUP.md`.
- [ ] `./check.sh guards` (brand copy and dash checks over `agent/skills/*/SKILL.md`); commit `docs(skills/browser): the browser exec contract`.

---

### Task 4: Flights, memory, the migration, the spec amendment

- [ ] `flights/SKILL.md`: line 10 → "Browser automation through the browser skill (`browser exec --stealth`, Camoufox)"; lines 74-77 → a `browser exec --session flights --stealth` program that opens `https://www.trip.com/flights/` and prints `page_info()`; keep the prose steps.
- [ ] `agent/MEMORY.md:27` stays (already names `browser handover start`).
- [ ] Write `agent/core/migrations/2026-09-browser-daemon.md` per the Global Constraints, modeled on `2026-09-upstream-pr-watcher.md` (prose paragraph, numbered `###` steps with bash blocks, the final `mark_migration_applied` step). The old-process step uses a bash loop over `/proc/[0-9]*/cmdline` with `tr '\0' ' '` and `kill`; never `pkill` (removed from the image).
- [ ] Spec: the Migration section's step that moves `~/.microsoft/browser-profiles/<email>` into a Camoufox profile becomes: tell the user each locked-tenant account needs `microsoft auth setup --account <email> --browser` again, then remove that directory; and add the `deregister-service browser` step. In Internal callers → Microsoft, replace "One stealth session per account ... `--stealth`" with the Chromium ruling and its reason (headless Firefox cannot load the Outlook/Teams SPAs; SSO needs cookies, not stealth), and the one-time re-sign-in.
- [ ] `./check.sh guards && ./check.sh agent`; commit `feat(agent): browser daemon fleet migration; flights and spec follow-ups`.

---

### Task 5: PR

- [ ] Push `feat/browser-callers`, open the PR against `feat/browser-handover` titled `refactor(skills): move browser callers to browser exec and converge the fleet`, body from the spec's Internal callers and Migration sections, stating the release order (#2391 → PR 2 → this) and the one-time Microsoft re-sign-in.

## Self-review notes

- Spec coverage: Internal callers (Tasks 1, 2), Skill documents (Task 3), Migration (Task 4), Retired and kept (Task 3 recipes; the code retirement happened in PR 1), the Microsoft engine amendment (Task 4).
- Deviation from the spec, deliberate: Microsoft on Chromium, not Camoufox, because of the headless-Firefox SPA limitation the old code documents; recorded in the spec by Task 4.
