"""Accessibility-tree snapshot with numbered refs (e1, e2, ...).

Built directly on CDP `Accessibility.getFullAXTree` + `DOM.resolveNode`. No Playwright.
Ref map is cached per-target-id in /tmp/vesta-browser-<session>.refs.json so actions
in later CLI invocations can resolve refs without re-snapshotting.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .admin import send

INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "listbox",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "spinbutton",
    "tab",
    "treeitem",
    "option",
    "cell",
    "columnheader",
    "rowheader",
}

CONTAINER_ROLES = {
    "main",
    "navigation",
    "banner",
    "contentinfo",
    "complementary",
    "region",
    "form",
    "search",
    "article",
    "dialog",
    "alertdialog",
    "menu",
    "menubar",
    "tablist",
    "tabpanel",
    "tree",
    "grid",
    "table",
    "list",
    "listitem",
    "heading",
    "figure",
    "section",
}

HIDDEN_ROLES = {"none", "presentation", "InlineTextBox"}


def refs_path(session: str | None = None) -> Path:
    name = session or os.environ.get("BROWSER_SESSION", "default")
    return Path(f"/tmp/vesta-browser-{name}.refs.json")


def _load_refs_store() -> dict:
    p = refs_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save_refs_store(store: dict) -> None:
    refs_path().write_text(json.dumps(store))


def store_refs(target_id: str, refs: dict) -> None:
    store = _load_refs_store()
    store[target_id] = refs
    _save_refs_store(store)


def read_ref(target_id: str, ref: str) -> dict:
    store = _load_refs_store()
    tab_refs = store.get(target_id)
    if not tab_refs:
        raise RuntimeError(f"no refs cached for target {target_id}. Take a fresh snapshot.")
    normalized = ref[4:] if ref.startswith("ref=") else ref.removeprefix("@")
    info = tab_refs.get(normalized)
    if not info:
        raise RuntimeError(
            f"unknown ref {normalized!r}. Take a fresh snapshot and use a ref from that output."
        )
    return info


def clear_refs(target_id: str | None = None) -> None:
    if target_id is None:
        try:
            refs_path().unlink()
        except FileNotFoundError:
            pass
        return
    store = _load_refs_store()
    store.pop(target_id, None)
    _save_refs_store(store)


# ── Snapshot ──────────────────────────────────────────────────


def _cdp(method: str, **params) -> dict:
    return send({"method": method, "params": params}).get("result", {})


def _get_ax_nodes() -> list[dict]:
    return _cdp("Accessibility.getFullAXTree").get("nodes", [])


def _value(field: dict | None) -> str:
    if not field:
        return ""
    v = field.get("value")
    return "" if v is None else str(v)


def _node_is_interactive(role: str) -> bool:
    return role in INTERACTIVE_ROLES


def _node_is_container(role: str) -> bool:
    return role in CONTAINER_ROLES


def _node_is_text(role: str) -> bool:
    return role in ("text", "StaticText")


def _node_name(node: dict) -> str:
    return _value(node.get("name")).strip()


def _node_role(node: dict) -> str:
    return _value(node.get("role"))


def _node_value(node: dict) -> str:
    return _value(node.get("value")).strip()


def _node_backend_id(node: dict) -> int | None:
    try:
        return int(node["backendDOMNodeId"])
    except (KeyError, ValueError, TypeError):
        return None


def _build_node_index(nodes: list[dict]) -> dict[str, dict]:
    return {n["nodeId"]: n for n in nodes}


def _root_nodes(nodes: list[dict]) -> list[dict]:
    index = _build_node_index(nodes)
    roots = [n for n in nodes if n.get("parentId") not in index]
    return roots or nodes[:1]


def _emit(node: dict, ref: str | None, include_url: bool = False) -> str:
    role = _node_role(node)
    name = _node_name(node)
    val = _node_value(node)
    parts = [role]
    if name:
        parts.append(f'"{name}"')
    if val and val != name:
        parts.append(f'value="{val}"')
    props = {p["name"]: p.get("value", {}).get("value") for p in node.get("properties", []) if p.get("name")}
    for flag in ("checked", "expanded", "selected", "pressed", "disabled", "focused"):
        if props.get(flag):
            parts.append(f"[{flag}]")
    level = props.get("level")
    if level:
        parts.append(f"level={level}")
    if ref:
        parts.append(f"[ref={ref}]")
    return " ".join(parts)


def _walk(
    node: dict,
    index: dict[str, dict],
    depth: int,
    ref_counter: list[int],
    interactive_only: bool,
    compact: bool,
    max_depth: int,
    lines: list[str],
    refs: dict,
) -> bool:
    """Walk the AX tree, emitting lines and assigning refs. Returns True if this subtree
    produced any output (used to prune empty containers in compact mode)."""
    if depth > max_depth:
        return False

    role = _node_role(node)
    if role in HIDDEN_ROLES:
        return _walk_children(
            node, index, depth, ref_counter, interactive_only, compact, max_depth, lines, refs
        )

    interactive = _node_is_interactive(role)
    container = _node_is_container(role)
    is_text = _node_is_text(role)

    name = _node_name(node)
    val = _node_value(node)
    has_visible_content = bool(name or val) or interactive

    if interactive_only and not interactive:
        # Recurse into any non-interactive node so we don't miss deeper interactives
        # (web pages aren't always semantically tagged above the action targets).
        return _walk_children(
            node, index, depth, ref_counter, interactive_only, compact, max_depth, lines, refs
        )

    ref = None
    if interactive:
        backend = _node_backend_id(node)
        if backend is not None:
            ref_counter[0] += 1
            ref = f"e{ref_counter[0]}"
            refs[ref] = {
                "backend_node_id": backend,
                "role": role,
                "name": name,
            }

    indent = "  " * depth
    produced_children: list[str] = []
    child_lines: list[str] = []
    child_refs_before = len(refs)
    if _walk_children(
        node, index, depth + 1, ref_counter, interactive_only, compact, max_depth, child_lines, refs
    ):
        produced_children = child_lines
    produced_any = bool(produced_children) or len(refs) > child_refs_before

    if interactive or (container and (has_visible_content or produced_any)) or (is_text and name):
        line = f"{indent}- {_emit(node, ref)}" if not is_text else f"{indent}- {name}"
        lines.append(line)
        lines.extend(produced_children)
        return True
    if produced_any:
        # We have descendants worth emitting but this node isn't interesting.
        lines.extend(produced_children)
        return True
    return False


def _walk_children(
    node: dict,
    index: dict[str, dict],
    depth: int,
    ref_counter: list[int],
    interactive_only: bool,
    compact: bool,
    max_depth: int,
    lines: list[str],
    refs: dict,
) -> bool:
    produced = False
    for cid in node.get("childIds", []):
        child = index.get(cid)
        if not child:
            continue
        if _walk(
            child, index, depth, ref_counter, interactive_only, compact, max_depth, lines, refs
        ):
            produced = True
    return produced


def snapshot(
    interactive_only: bool = False,
    compact: bool = False,
    max_depth: int = 50,
) -> dict:
    """Take a new accessibility snapshot. Returns {text, refs, target_id, url, title}."""
    info = _cdp("Target.getTargetInfo").get("targetInfo", {})
    target_id = info.get("targetId", "")
    url = info.get("url", "")
    title = info.get("title", "")

    nodes = _get_ax_nodes()
    index = _build_node_index(nodes)
    roots = _root_nodes(nodes)

    ref_counter = [0]
    lines: list[str] = []
    refs: dict = {}
    for root in roots:
        _walk(root, index, 0, ref_counter, interactive_only, compact, max_depth, lines, refs)

    text = "\n".join(lines)
    store_refs(target_id, refs)
    return {
        "target_id": target_id,
        "url": url,
        "title": title,
        "text": text,
        "refs": refs,
        "ref_count": len(refs),
    }
