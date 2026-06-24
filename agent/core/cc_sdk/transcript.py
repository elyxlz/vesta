"""Read and parse the interactive `claude` session transcript (append-only JSONL).

The transcript is the source of truth for assistant output. We tail it from a byte
offset and turn each new main-agent `assistant` line into an AssistantMessage with
the same block shape the official SDK produced. Subagent lines (isSidechain=true)
are skipped — their progress is surfaced via SubagentStart/Stop hooks instead.
"""

import json
import pathlib as pl
import typing as tp

from .messages import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock


def read_new_objects(path: pl.Path, offset: int) -> tuple[list[dict[str, tp.Any]], int]:
    """Return JSON objects for newly-appended complete lines and the advanced offset."""
    if not path.exists():
        return [], offset
    with path.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    if not chunk:
        return [], offset
    last_nl = chunk.rfind(b"\n")
    if last_nl == -1:
        return [], offset
    complete = chunk[: last_nl + 1]
    objects: list[dict[str, tp.Any]] = []
    for raw in complete.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects, offset + len(complete)


def _is_main_assistant(obj: dict[str, tp.Any]) -> bool:
    type_ = obj["type"] if "type" in obj else None
    if type_ != "assistant":
        return False
    return not ("isSidechain" in obj and obj["isSidechain"])


def assistant_message_from(obj: dict[str, tp.Any]) -> AssistantMessage | None:
    if not _is_main_assistant(obj):
        return None
    message = obj["message"] if "message" in obj else {}
    raw_content = message["content"] if "content" in message else []
    if not isinstance(raw_content, list):
        return None
    blocks: list[tp.Any] = []
    for block in raw_content:
        if not isinstance(block, dict) or "type" not in block:
            continue
        kind = block["type"]
        if kind == "text" and "text" in block:
            blocks.append(TextBlock(text=block["text"]))
        elif kind == "thinking" and "thinking" in block:
            signature = block["signature"] if "signature" in block else ""
            blocks.append(ThinkingBlock(thinking=block["thinking"], signature=signature))
        elif kind == "tool_use":
            blocks.append(
                ToolUseBlock(
                    id=block["id"] if "id" in block else "",
                    name=block["name"] if "name" in block else "",
                    input=block["input"] if "input" in block else {},
                )
            )
    model = message["model"] if "model" in message else None
    is_api_error = bool(obj["isApiErrorMessage"]) if "isApiErrorMessage" in obj else False
    return AssistantMessage(content=blocks, model=model, is_api_error=is_api_error)


def is_compact_summary(obj: dict[str, tp.Any]) -> bool:
    """True for the transcript line claude writes when a /compact finishes (its only completion marker)."""
    return "isCompactSummary" in obj and bool(obj["isCompactSummary"])


def usage_from(obj: dict[str, tp.Any]) -> dict[str, tp.Any] | None:
    if not _is_main_assistant(obj):
        return None
    message = obj["message"] if "message" in obj else {}
    if "usage" in message and isinstance(message["usage"], dict):
        return message["usage"]
    return None
