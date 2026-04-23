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


def test_walk_respects_max_depth():
    # Chain of nested containers deeper than max_depth should bottom out without emitting the button.
    nodes = [_node(str(i), "group", name="", children=[str(i + 1)]) for i in range(1, 6)]
    nodes.append(_node("6", "button", name="Deep", backend=99))
    nodes[0]["role"] = {"value": "WebArea"}  # Root.
    index = {n["nodeId"]: n for n in nodes}
    refs: dict = {}
    lines: list[str] = []
    snapshot._walk(nodes[0], index, 0, [0], False, False, 2, lines, refs)
    assert "e1" not in refs


def test_walk_skips_node_without_backend_id():
    nodes = [
        _node("1", "WebArea", name="r", children=["2"]),
        _node("2", "button", name="nobackend"),  # backend omitted
    ]
    index = {n["nodeId"]: n for n in nodes}
    refs: dict = {}
    lines: list[str] = []
    snapshot._walk(nodes[0], index, 0, [0], False, False, 50, lines, refs)
    assert refs == {}


# ── AX value extraction ───────────────────────────────────────


def test_ax_value_handles_missing():
    assert snapshot._ax_value(None) == ""
    assert snapshot._ax_value({}) == ""


def test_ax_value_stringifies():
    assert snapshot._ax_value({"value": 42}) == "42"
    assert snapshot._ax_value({"value": "hello"}) == "hello"
    assert snapshot._ax_value({"value": None}) == ""


def test_node_backend_id_missing_returns_none():
    assert snapshot._node_backend_id({}) is None


def test_node_backend_id_invalid_returns_none():
    assert snapshot._node_backend_id({"backendDOMNodeId": "not-an-int"}) is None


def test_node_backend_id_parses():
    assert snapshot._node_backend_id({"backendDOMNodeId": 17}) == 17
    assert snapshot._node_backend_id({"backendDOMNodeId": "42"}) == 42


def test_node_properties_flattens():
    node = {
        "properties": [
            {"name": "checked", "value": {"value": True}},
            {"name": "level", "value": {"value": 2}},
            {"name": "no-value"},
        ]
    }
    props = snapshot._node_properties(node)
    assert props == {"checked": True, "level": 2, "no-value": None}


def test_node_properties_empty_when_missing():
    assert snapshot._node_properties({}) == {}


def test_emit_includes_state_flags():
    node = _node("1", "button", name="Toggle", backend=1)
    node["properties"] = [{"name": "pressed", "value": {"value": True}}]
    out = snapshot._emit(node, "e1")
    assert "[pressed]" in out
    assert '"Toggle"' in out
    assert "[ref=e1]" in out


def test_root_nodes_picks_node_without_parent():
    nodes = [
        {"nodeId": "A", "role": {"value": "WebArea"}, "name": {"value": "root"}},
        {"nodeId": "B", "parentId": "A", "role": {"value": "button"}, "name": {"value": ""}},
    ]
    roots = snapshot._root_nodes(nodes)
    assert len(roots) == 1
    assert roots[0]["nodeId"] == "A"


# ── Refs store ────────────────────────────────────────────────


def test_refs_store_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("BROWSER_SESSION", "unit-test")
    monkeypatch.setattr(snapshot, "refs_path", lambda session=None: tmp_path / "refs.json")

    snapshot.store_refs("TID1", {"e1": {"backend_node_id": 42, "role": "button", "name": "x"}})
    info = snapshot.read_ref("TID1", "e1")
    assert info["backend_node_id"] == 42
    assert info["role"] == "button"


def test_read_ref_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "refs_path", lambda session=None: tmp_path / "refs.json")
    with pytest.raises(RuntimeError):
        snapshot.read_ref("TID-nothing", "e5")


def test_read_ref_normalizes_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "refs_path", lambda session=None: tmp_path / "refs.json")
    snapshot.store_refs("TID", {"e9": {"backend_node_id": 1, "role": "link", "name": "n"}})
    assert snapshot.read_ref("TID", "ref=e9") == snapshot.read_ref("TID", "e9")
    assert snapshot.read_ref("TID", "@e9") == snapshot.read_ref("TID", "e9")


def test_read_ref_unknown_in_known_target(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "refs_path", lambda session=None: tmp_path / "refs.json")
    snapshot.store_refs("TID", {"e1": {"backend_node_id": 1, "role": "button", "name": "a"}})
    with pytest.raises(RuntimeError, match="unknown ref"):
        snapshot.read_ref("TID", "e99")


def test_clear_refs_all(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "refs_path", lambda session=None: tmp_path / "refs.json")
    snapshot.store_refs("T1", {"e1": {}})
    snapshot.store_refs("T2", {"e1": {}})
    snapshot.clear_refs()
    assert not (tmp_path / "refs.json").exists()


def test_clear_refs_single_target(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "refs_path", lambda session=None: tmp_path / "refs.json")
    snapshot.store_refs("T1", {"e1": {"backend_node_id": 1, "role": "button", "name": ""}})
    snapshot.store_refs("T2", {"e1": {"backend_node_id": 2, "role": "link", "name": ""}})
    snapshot.clear_refs("T1")
    with pytest.raises(RuntimeError):
        snapshot.read_ref("T1", "e1")
    # T2 survives.
    assert snapshot.read_ref("T2", "e1")["backend_node_id"] == 2
