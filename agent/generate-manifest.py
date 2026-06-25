#!/usr/bin/env python3
"""Generate core/manifest.json from the provider models in core/config.py.

The pydantic model is the single source of types + defaults + catalog; this writes the JSON
projection so the non-Python layers (vestad embeds it and serves GET /manifest; web/cli read it) can
see the catalog + defaults. CI fails if the committed file is stale.

Run from agent/: uv run python generate-manifest.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from core.config import MANIFEST_PATH, build_manifest  # noqa: E402

if __name__ == "__main__":
    MANIFEST_PATH.write_text(build_manifest().model_dump_json(indent=2) + "\n")
    print(f"Generated {MANIFEST_PATH}")
