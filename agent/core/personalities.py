"""Personality preset management.

Presets live in `agent/core/prompts/personalities/*.md`. Each preset contains the
subsection content (### Who..., ### Respect & Boundaries, ...) that lives under
MEMORY.md's first H2 section (the CORE IDENTITY & PERSONALITY one).

Anchoring on the H2 header keeps this backward-compatible with existing agents
whose MEMORY.md predates any personality tooling. The section is identified by
the first H2 whose title contains "personality" or "identity" (case-insensitive).
"""

import pathlib as pl
import re

from . import models as vm
from .helpers import get_memory_path

_FRONTMATTER_RE = re.compile(r"^<!--\s*(\w+)\s*:\s*(.*?)\s*-->\s*$", re.MULTILINE)

# Matches the personality H2 header and everything beneath it until the next H2
# (or end of file). Group 1 = header line; group 2 = body.
_SECTION_RE = re.compile(
    r"^(##\s[^\n]*?(?:personality|identity)[^\n]*)\n(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)


def personalities_dir(config: vm.VestaConfig) -> pl.Path:
    return config.core_prompts_dir / "personalities"


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Parse leading `<!-- key: value -->` lines into a dict; return (meta, body)."""
    meta: dict[str, str] = {}
    lines = raw.splitlines(keepends=True)
    consumed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            consumed += 1
            continue
        match = _FRONTMATTER_RE.match(stripped)
        if not match:
            break
        meta[match.group(1)] = match.group(2)
        consumed += 1
    body = "".join(lines[consumed:]).lstrip("\n")
    return meta, body


def _preset_body(path: pl.Path) -> str:
    """Return preset body with frontmatter stripped. [agent_name] placeholder kept."""
    _, body = _parse_frontmatter(path.read_text())
    return body


def _normalized_active_block(memory_text: str, agent_name: str) -> str | None:
    """Return the current personality block with the agent's name folded back to
    `[agent_name]` so it can be compared against the raw preset body."""
    match = _SECTION_RE.search(memory_text)
    if not match:
        return None
    block = match.group(2).strip()
    if agent_name:
        block = re.sub(rf"\b{re.escape(agent_name)}\b", "[agent_name]", block)
    return block


def list_personalities(config: vm.VestaConfig) -> list[dict]:
    """Return available presets. Includes an `active` flag on the one currently in MEMORY.md."""
    pdir = personalities_dir(config)
    if not pdir.exists():
        return []

    memory_path = get_memory_path(config)
    active_block = _normalized_active_block(memory_path.read_text(), config.agent_name) if memory_path.exists() else None

    results: list[dict] = []
    for path in sorted(pdir.glob("*.md")):
        meta, _ = _parse_frontmatter(path.read_text())
        preset_body = _preset_body(path).strip()
        results.append(
            {
                "name": path.stem,
                "title": meta["title"] if "title" in meta else path.stem.replace("-", " "),
                "emoji": meta["emoji"] if "emoji" in meta else "",
                "description": meta["description"] if "description" in meta else "",
                "active": active_block is not None and active_block == preset_body,
            }
        )
    return results


def apply_personality(name: str, config: vm.VestaConfig) -> None:
    """Replace the body of MEMORY.md's personality H2 section with a preset."""
    if "/" in name or ".." in name or name == "":
        raise ValueError(f"invalid personality name: {name!r}")

    preset_path = personalities_dir(config) / f"{name}.md"
    if not preset_path.exists():
        raise FileNotFoundError(f"personality preset not found: {name}")

    memory_path = get_memory_path(config)
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path}")

    memory_text = memory_path.read_text()
    match = _SECTION_RE.search(memory_text)
    if not match:
        raise ValueError("could not find a personality section in MEMORY.md (expected an H2 header containing 'personality' or 'identity')")

    new_body = _preset_body(preset_path).strip().replace("[agent_name]", config.agent_name)
    updated = memory_text[: match.start()] + match.group(1) + "\n\n" + new_body + "\n\n" + memory_text[match.end() :]
    memory_path.write_text(updated)
