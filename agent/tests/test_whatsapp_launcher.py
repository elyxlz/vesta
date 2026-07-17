"""Exercises the REAL whatsapp launcher (agent/skills/whatsapp/whatsapp) against a
fake `go` toolchain: cached build + exec (rebuild only on source change), the
non-blocking whatsmeow update CHECK on serve (warn only, never `go get`), and the
deliberate `update-deps` path."""

import os
import pathlib as pl
import subprocess

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "agent/skills/whatsapp/whatsapp"

FAKE_GO = """#!/bin/bash
echo "$@" >> "$GO_LOG"
case "$1" in
  get) exit "${GO_GET_EXIT:-0}" ;;
  list) [ -n "${WHATSMEOW_UPDATE:-}" ] && echo "$WHATSMEOW_UPDATE"; exit 0 ;;
  build)
    out=""; prev=""
    for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
    printf '#!/bin/bash\\necho "$@" > "$RUN_LOG"\\n' > "$out"
    chmod +x "$out"
    ;;
esac
"""


def _run(tmp_path, args, whatsmeow_update=""):
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    (fakebin / "go").write_text(FAKE_GO)
    (fakebin / "go").chmod(0o755)
    env = os.environ | {
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "GO_LOG": str(tmp_path / "go.log"),
        "RUN_LOG": str(tmp_path / "run.log"),
        "WHATSMEOW_UPDATE": whatsmeow_update,
    }
    result = subprocess.run(["bash", str(LAUNCHER), *args], env=env, capture_output=True, text=True, cwd=tmp_path, check=False)
    go_log = (tmp_path / "go.log").read_text() if (tmp_path / "go.log").exists() else ""
    run_log = (tmp_path / "run.log").read_text() if (tmp_path / "run.log").exists() else ""
    return result, go_log, run_log


def test_serve_runs_update_check_then_builds_and_execs(tmp_path):
    result, go_log, run_log = _run(tmp_path, ["serve", "--notifications-dir", "/tmp/notif"])
    assert result.returncode == 0, result.stderr
    go_calls = go_log.splitlines()
    # serve runs a non-blocking update CHECK (never `go get`), then builds and execs.
    assert go_calls[0].startswith("list -m -u ")
    assert "get " not in go_log
    assert go_calls[1].startswith("build -tags fts5 -o ")
    assert run_log.strip() == "serve --notifications-dir /tmp/notif"


def test_one_shot_commands_skip_the_whatsmeow_update_check(tmp_path):
    result, go_log, run_log = _run(tmp_path, ["send", "Alice", "hi there"])
    assert result.returncode == 0, result.stderr
    assert "list " not in go_log
    assert run_log.strip() == "send Alice hi there"


def test_serve_warns_when_newer_whatsmeow_exists_and_still_serves_current_pin(tmp_path):
    result, go_log, run_log = _run(tmp_path, ["serve", "--notifications-dir", "/tmp/notif"], whatsmeow_update="v0.0.1 v0.0.2")
    assert result.returncode == 0, result.stderr
    assert "newer whatsmeow is available" in result.stderr
    assert "get " not in go_log  # the check warns, it never upgrades
    assert run_log.strip() == "serve --notifications-dir /tmp/notif"


def test_rebuild_replaces_the_cached_binary_without_leftover_temps(tmp_path):
    _run(tmp_path, ["list-chats"])
    result, _, run_log = _run(tmp_path, ["list-chats"])
    assert result.returncode == 0, result.stderr
    assert run_log.strip() == "list-chats"
    assert sorted(p.name for p in (tmp_path / "cache" / "whatsapp").iterdir()) == ["whatsapp"]
