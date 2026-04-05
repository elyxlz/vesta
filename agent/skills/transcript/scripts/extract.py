#!/usr/bin/env python3
"""Extract raw session messages from the Claude SDK and save to JSON.

Usage:
    extract.py [output.json]

Reads the current session ID from the vesta data directory and pulls all
messages via get_session_messages(). If no output path is given, writes to
~/vesta/data/session_transcript.json.
"""

import dataclasses
import json
import os
import sys
from pathlib import Path


def find_session_id():
    """Find the current session ID from the vesta data directory."""
    data_dir = Path(os.environ.get("VESTA_DATA_DIR", os.path.expanduser("~/vesta/data")))
    session_file = data_dir / "session_id"
    if not session_file.exists():
        print("Error: no session_id file found", file=sys.stderr)
        sys.exit(1)
    session_id = session_file.read_text().strip()
    if not session_id:
        print("Error: session_id file is empty", file=sys.stderr)
        sys.exit(1)
    return session_id


def extract(output_path=None):
    """Extract session messages and save to JSON."""
    from claude_agent_sdk import get_session_messages

    session_id = find_session_id()
    print(f"Session: {session_id[:16]}...")

    messages = get_session_messages(session_id)
    print(f"Messages: {len(messages)}")

    # Convert to serializable dicts
    data = []
    for m in messages:
        if dataclasses.is_dataclass(m):
            data.append(dataclasses.asdict(m))
        elif hasattr(m, "__dict__"):
            data.append(m.__dict__)
        else:
            data.append({"type": m.type, "uuid": m.uuid, "message": m.message})

    if output_path is None:
        output_path = os.path.expanduser("~/vesta/data/session_transcript.json")

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    size = os.path.getsize(output_path)
    print(f"Saved: {size:,} bytes → {output_path}")

    return {"session_id": session_id, "messages": len(messages), "output": output_path, "bytes": size}


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    extract(output)
