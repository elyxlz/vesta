---
migration_phase: before_sync
---

Your voice is the preset named by `agent_personality` in `~/agent/data/config.json`. When that key is missing, the voice is the preset whose frontmatter declares `default: true`. The coming sync moves `default: true` to a different preset, so an agent with no saved preset would change voice at the next boot without the user choosing it. Save your current preset now, before the sync. Safe to run more than once: it saves nothing when the key is already there.

### 1. Save the current preset

```bash
cd ~/agent && uv run --project core python - <<'PY'
import json, pathlib
from core.config import update_config_store
from core.personalities import DEFAULT_PERSONALITY

store = pathlib.Path.home() / "agent/data/config.json"
cfg = json.loads(store.read_text()) if store.is_file() else {}
if "agent_personality" in cfg:
    print("already saved:", cfg["agent_personality"])
else:
    update_config_store({"agent_personality": DEFAULT_PERSONALITY})
    print("saved:", DEFAULT_PERSONALITY)
PY
```

It prints the preset that is now your voice. Your voice does not change, so do not tell the user about this step.

### 2. Mark this migration applied

Call `mark_migration_applied` with `name="2026-11-pin-personality-preset"`.
