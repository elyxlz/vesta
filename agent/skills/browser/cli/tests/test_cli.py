"""Tests for the argparse dispatcher and command helpers that don't need a live browser."""

from __future__ import annotations

import argparse

from vesta_browser import cli, helpers


def test_parser_accepts_all_documented_subcommands():
    parser = cli._build_parser()
    for cmd in (
        "launch",
        "connect",
        "stop",
        "stop-all",
        "sessions",
        "open",
        "navigate",
        "reload",
        "back",
        "forward",
        "snapshot",
        "screenshot",
        "pdf",
        "click",
        "type",
        "press",
        "hover",
        "scroll",
        "wait",
        "evaluate",
        "cdp",
        "http-get",
        "tabs",
        "focus",
        "close",
        "resize",
    ):
        ns = parser.parse_args([cmd] + _minimal_args_for(cmd))
        assert ns.cmd == cmd


def _minimal_args_for(cmd: str) -> list[str]:
    need_url = {"open", "navigate", "connect", "http-get"}
    need_ref = {"type", "hover"}
    need_key = {"press"}
    need_expression = {"evaluate"}
    need_cdp_method = {"cdp"}
    if cmd in need_url:
        return ["https://example.com"]
    if cmd in need_ref:
        if cmd == "type":
            return ["e1", "hello"]
        return ["e1"]
    if cmd in need_key:
        return ["Enter"]
    if cmd in need_expression:
        return ["document.title"]
    if cmd in need_cdp_method:
        return ["Page.reload"]
    if cmd == "click":
        return ["e1"]
    if cmd == "focus" or cmd == "close":
        return ["TARGET_XYZ"]
    if cmd == "resize":
        return ["1920", "1080"]
    return []


def test_parser_launch_flags():
    parser = cli._build_parser()
    ns = parser.parse_args(["launch", "--headless", "--stealth", "--no-sandbox", "--port", "9999"])
    assert ns.headless is True
    assert ns.stealth is True
    assert ns.no_sandbox is True
    assert ns.port == 9999


def test_parser_click_at_coords():
    parser = cli._build_parser()
    ns = parser.parse_args(["click", "--at", "320.5", "180.0"])
    assert ns.at == [320.5, 180.0]
    assert ns.ref is None


def test_parser_click_ref_and_modifiers():
    parser = cli._build_parser()
    ns = parser.parse_args(["click", "e5", "--double", "--right"])
    assert ns.ref == "e5"
    assert ns.double is True
    assert ns.right is True


def test_parser_type_with_submit():
    parser = cli._build_parser()
    ns = parser.parse_args(["type", "e3", "hello world", "--submit", "--slowly"])
    assert ns.ref == "e3"
    assert ns.text == "hello world"
    assert ns.submit is True
    assert ns.slowly is True


def test_parser_wait_branches():
    parser = cli._build_parser()
    ns = parser.parse_args(["wait", "--text", "Ready"])
    assert ns.text == "Ready"
    ns = parser.parse_args(["wait", "--time", "1500"])
    assert ns.time == 1500
    ns = parser.parse_args(["wait", "--url", "**/dashboard"])
    assert ns.url == "**/dashboard"


def test_parser_press_modifiers():
    parser = cli._build_parser()
    ns = parser.parse_args(["press", "a", "--modifiers", "Control", "Shift"])
    assert ns.key == "a"
    assert ns.modifiers == ["Control", "Shift"]


def test_press_combo_shorthand_is_expanded(monkeypatch):
    """'Control+a' should decompose into key='a' + modifier 'Control'."""
    seen: dict = {}

    def fake_press(key: str, modifiers=0):
        seen["key"] = key
        seen["modifiers"] = modifiers

    monkeypatch.setattr(helpers, "press_key", fake_press)
    monkeypatch.setattr(helpers, "wait", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "_print_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(cli.admin, "ensure_daemon", lambda *a, **kw: None)

    args = argparse.Namespace(key="Control+a", modifiers=None)
    rc = cli.cmd_press(args)
    assert rc == 0
    assert seen["key"] == "a"
    assert seen["modifiers"] == ["Control"]


def test_cmd_wait_requires_a_condition(monkeypatch, capsys):
    monkeypatch.setattr(cli.admin, "ensure_daemon", lambda *a, **kw: None)
    args = argparse.Namespace(text=None, url=None, load_state=None, time=None, timeout=1.0)
    rc = cli.cmd_wait(args)
    assert rc == 2
    err = capsys.readouterr().err
    assert "wait needs one of" in err


def test_cmd_click_requires_ref_or_at(monkeypatch, capsys):
    monkeypatch.setattr(cli.admin, "ensure_daemon", lambda *a, **kw: None)
    args = argparse.Namespace(at=None, ref=None, double=False, right=False)
    rc = cli.cmd_click(args)
    assert rc == 2


def test_main_prints_help_when_no_command(monkeypatch, capsys):
    # Simulate argv without command and no stdin pipe.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    rc = cli.main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Vesta browser CLI" in captured.out or "usage:" in captured.out.lower()


def test_snapshot_banner_format(monkeypatch):
    def fake_snapshot(interactive_only: bool = False, compact: bool = False):
        return {
            "target_id": "T1",
            "url": "https://unknown.example/",
            "title": "A",
            "text": '- page\n  - button "Go" [ref=e1]',
            "refs": {"e1": {}},
            "ref_count": 1,
        }

    monkeypatch.setattr(cli.snapshot, "snapshot", fake_snapshot)
    monkeypatch.setattr(cli.helpers, "recipe_banner", lambda _: "")

    banner = cli._snapshot_banner()
    assert "# A" in banner
    assert "# https://unknown.example/" in banner
    assert "1 interactive refs" in banner
    assert "[ref=e1]" in banner


def test_snapshot_banner_handles_snapshot_failure(monkeypatch):
    def blow_up(**kwargs):
        raise RuntimeError("CDP dead")

    monkeypatch.setattr(cli.snapshot, "snapshot", blow_up)
    assert "snapshot failed: CDP dead" in cli._snapshot_banner()


def test_cmd_screenshot_plumbs_webp_and_region(monkeypatch):
    """--webp + --region flow through as format='webp' + region tuple; path default follows format."""
    captured: dict = {}
    monkeypatch.setattr(cli.admin, "ensure_daemon", lambda *a, **kw: None)
    monkeypatch.setattr(cli.helpers, "screenshot", lambda **kw: (captured.update(kw), kw["path"])[1])

    args = argparse.Namespace(path="/tmp/shot.webp", full_page=False, webp=True, jpeg=False, region="10,20,300,200", quality=75)
    assert cli.cmd_screenshot(args) == 0
    assert captured["format"] == "webp"
    assert captured["region"] == (10.0, 20.0, 300.0, 200.0)
    assert captured["quality"] == 75

    captured.clear()
    cli.cmd_screenshot(argparse.Namespace(path=None, full_page=False, webp=True, jpeg=False, region=None, quality=None))
    assert captured["path"].endswith(".webp")


def test_cmd_screenshot_infers_format_from_path_suffix(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cli.admin, "ensure_daemon", lambda *a, **kw: None)
    monkeypatch.setattr(cli.helpers, "screenshot", lambda **kw: (captured.update(kw), kw["path"])[1])
    cli.cmd_screenshot(argparse.Namespace(path="/tmp/x.jpg", full_page=False, webp=False, jpeg=False, region=None, quality=None))
    assert captured["format"] == "jpeg"


def test_cmd_screenshot_rejects_malformed_region(monkeypatch):
    import pytest

    monkeypatch.setattr(cli.admin, "ensure_daemon", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="--region expects"):
        cli.cmd_screenshot(argparse.Namespace(path=None, full_page=False, webp=False, jpeg=False, region="0,0,320", quality=None))
