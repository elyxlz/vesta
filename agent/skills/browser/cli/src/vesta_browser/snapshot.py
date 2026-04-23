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

STATE_FLAGS = ("checked", "expanded", "selected", "pressed", "disabled", "focused")


def refs_path(session: str | None = None) -> Path:
    if session is None:
        session = os.environ["BROWSER_SESSION"] if "BROWSER_SESSION" in os.environ else "default"
    return Path(f"/tmp/vesta-browser-{session}.refs.json")


def _load_refs_store() -> dict:
    try:
        return json.loads(refs_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_refs_store(store: dict) -> None:
    refs_path().write_text(json.dumps(store))


def store_refs(target_id: str, refs: dict) -> None:
    store = _load_refs_store()
    store[target_id] = refs
    _save_refs_store(store)


def read_ref(target_id: str, ref: str) -> dict:
    store = _load_refs_store()
    if target_id not in store or not store[target_id]:
        raise RuntimeError(f"no refs cached for target {target_id}. Take a fresh snapshot.")
    tab_refs = store[target_id]
    normalized = ref[4:] if ref.startswith("ref=") else ref.removeprefix("@")
    if normalized not in tab_refs:
        raise RuntimeError(f"unknown ref {normalized!r}. Take a fresh snapshot and use a ref from that output.")
    return tab_refs[normalized]


def clear_refs(target_id: str | None = None) -> None:
    if target_id is None:
        try:
            refs_path().unlink()
        except FileNotFoundError:
            pass
        return
    store = _load_refs_store()
    if target_id in store:
        del store[target_id]
        _save_refs_store(store)


# ── Snapshot ──────────────────────────────────────────────────


def _cdp(method: str, **params) -> dict:
    resp = send({"method": method, "params": params})
    return resp["result"] if "result" in resp else {}


def _get_ax_nodes() -> list[dict]:
    resp = _cdp("Accessibility.getFullAXTree")
    return resp["nodes"] if "nodes" in resp else []


def _ax_value(field: dict | None) -> str:
    """AX fields are `{value: ...}` dicts; missing or None → empty string."""
    if not field or "value" not in field or field["value"] is None:
        return ""
    return str(field["value"])


def _node_name(node: dict) -> str:
    return _ax_value(node["name"] if "name" in node else None).strip()


def _node_role(node: dict) -> str:
    return _ax_value(node["role"] if "role" in node else None)


def _node_value(node: dict) -> str:
    return _ax_value(node["value"] if "value" in node else None).strip()


def _node_backend_id(node: dict) -> int | None:
    if "backendDOMNodeId" not in node:
        return None
    try:
        return int(node["backendDOMNodeId"])
    except (ValueError, TypeError):
        return None


def _node_properties(node: dict) -> dict:
    """Flatten AX properties list into a name -> value dict. Missing properties key → {}."""
    if "properties" not in node:
        return {}
    out = {}
    for p in node["properties"]:
        if "name" not in p:
            continue
        value = p["value"]["value"] if "value" in p and "value" in p["value"] else None
        out[p["name"]] = value
    return out


def _node_children(node: dict) -> list[str]:
    return node["childIds"] if "childIds" in node else []


def _build_node_index(nodes: list[dict]) -> dict[str, dict]:
    return {n["nodeId"]: n for n in nodes}


def _root_nodes(nodes: list[dict]) -> list[dict]:
    index = _build_node_index(nodes)
    roots = [n for n in nodes if "parentId" not in n or n["parentId"] not in index]
    return roots or nodes[:1]


def _emit(node: dict, ref: str | None) -> str:
    role = _node_role(node)
    name = _node_name(node)
    val = _node_value(node)
    parts = [role]
    if name:
        parts.append(f'"{name}"')
    if val and val != name:
        parts.append(f'value="{val}"')
    props = _node_properties(node)
    for flag in STATE_FLAGS:
        if flag in props and props[flag]:
            parts.append(f"[{flag}]")
    if "level" in props and props["level"]:
        parts.append(f"level={props['level']}")
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
        return _walk_children(node, index, depth, ref_counter, interactive_only, compact, max_depth, lines, refs)

    interactive = role in INTERACTIVE_ROLES
    container = role in CONTAINER_ROLES
    is_text = role in ("text", "StaticText")

    name = _node_name(node)
    val = _node_value(node)
    has_visible_content = bool(name or val) or interactive

    if interactive_only and not interactive:
        # Recurse into any non-interactive node so we don't miss deeper interactives
        # (web pages aren't always semantically tagged above the action targets).
        return _walk_children(node, index, depth, ref_counter, interactive_only, compact, max_depth, lines, refs)

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
    child_lines: list[str] = []
    child_refs_before = len(refs)
    produced_children = _walk_children(node, index, depth + 1, ref_counter, interactive_only, compact, max_depth, child_lines, refs)
    produced_any = produced_children or len(refs) > child_refs_before

    if interactive or (container and (has_visible_content or produced_any)) or (is_text and name):
        line = f"{indent}- {_emit(node, ref)}" if not is_text else f"{indent}- {name}"
        lines.append(line)
        lines.extend(child_lines)
        return True
    if produced_any:
        lines.extend(child_lines)
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
    for cid in _node_children(node):
        if cid not in index:
            continue
        if _walk(index[cid], index, depth, ref_counter, interactive_only, compact, max_depth, lines, refs):
            produced = True
    return produced


def snapshot(
    interactive_only: bool = False,
    compact: bool = False,
    max_depth: int = 50,
) -> dict:
    """Take a new accessibility snapshot. Returns {text, refs, target_id, url, title}."""
    resp = _cdp("Target.getTargetInfo")
    info = resp["targetInfo"] if "targetInfo" in resp else {}
    target_id = info["targetId"] if "targetId" in info else ""
    url = info["url"] if "url" in info else ""
    title = info["title"] if "title" in info else ""

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
