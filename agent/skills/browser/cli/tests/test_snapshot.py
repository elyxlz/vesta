"""Unit tests for the AX-tree walker (no daemon, no real Chrome)."""

from __future__ import annotations


import pytest

from vesta_browser import snapshot


def _node(ax_id: str, role: str, *, name: str = "", backend: int | None = None, children: list[str] | None = None):
    node: dict = {
        "nodeId": ax_id,
        "role": {"value": role},
        "name": {"value": name},
        "childIds": children or [],
    }
    if backend is not None:
        node["backendDOMNodeId"] = backend
    return node


def test_walk_numbers_interactive_nodes():
    nodes = [
        _node("1", "WebArea", name="Home", children=["2", "3"]),
        _node("2", "button", name="Submit", backend=100),
        _node("3", "link", name="More", backend=101),
    ]
    index = {n["nodeId"]: n for n in nodes}
    refs: dict = {}
    lines: list[str] = []
    snapshot._walk(nodes[0], index, 0, [0], False, False, 50, lines, refs)

    assert set(refs.keys()) == {"e1", "e2"}
    assert refs["e1"]["role"] == "button"
    assert refs["e1"]["name"] == "Submit"
    assert refs["e1"]["backend_node_id"] == 100
    assert refs["e2"]["role"] == "link"
    assert any("button" in line and "e1" in line for line in lines)
    assert any("link" in line and "e2" in line for line in lines)


def test_walk_skips_non_interactive_when_interactive_only():
    nodes = [
        _node("1", "WebArea", name="Page", children=["2", "3"]),
        _node("2", "paragraph", name="some text"),
        _node("3", "button", name="Go", backend=42),
    ]
    index = {n["nodeId"]: n for n in nodes}
    refs: dict = {}
    lines: list[str] = []
    snapshot._walk(nodes[0], index, 0, [0], True, False, 50, lines, refs)

    assert "e1" in refs
    assert refs["e1"]["role"] == "button"
    assert all("paragraph" not in line for line in lines)


def test_walk_hidden_roles_pass_through():
    nodes = [
        _node("1", "WebArea", name="r", children=["2"]),
        _node("2", "none", name="", children=["3"]),
        _node("3", "button", name="Deep", backend=7),
    ]
    index = {n["nodeId"]: n for n in nodes}
    refs: dict = {}
    lines: list[str] = []
    snapshot._walk(nodes[0], index, 0, [0], False, False, 50, lines, refs)

    assert "e1" in refs
    assert refs["e1"]["name"] == "Deep"


def test_refs_store_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("BROWSER_SESSION", "unit-test")
    monkeypatch.setattr(
        snapshot,
        "refs_path",
        lambda session=None: tmp_path / "refs.json",
    )

    snapshot.store_refs("TID1", {"e1": {"backend_node_id": 42, "role": "button", "name": "x"}})
    info = snapshot.read_ref("TID1", "e1")
    assert info["backend_node_id"] == 42
    assert info["role"] == "button"


def test_read_ref_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(
        snapshot,
        "refs_path",
        lambda session=None: tmp_path / "refs.json",
    )
    with pytest.raises(RuntimeError):
        snapshot.read_ref("TID-nothing", "e5")


def test_read_ref_normalizes_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(
        snapshot,
        "refs_path",
        lambda session=None: tmp_path / "refs.json",
    )
    snapshot.store_refs("TID", {"e9": {"backend_node_id": 1, "role": "link", "name": "n"}})
    assert snapshot.read_ref("TID", "ref=e9") == snapshot.read_ref("TID", "e9")
    assert snapshot.read_ref("TID", "@e9") == snapshot.read_ref("TID", "e9")
