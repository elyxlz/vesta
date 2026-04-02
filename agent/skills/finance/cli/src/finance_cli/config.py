import json
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".finance"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    "app_id": "",
    "key_path": "",
    "session_id": "",
    "accounts": [],
}


def load() -> dict:
    """Load config from disk, returning defaults if file doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text())
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"Failed to read config: {e}"}), file=sys.stderr)
        sys.exit(1)


def save(cfg: dict) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def require_credentials(cfg: dict) -> None:
    """Exit with error if app_id / key_path are not set."""
    if not cfg.get("app_id") or not cfg.get("key_path"):
        print(
            json.dumps({"error": "app_id and key_path are not configured. Run: finance config set --app-id <uuid> --key-path <path-to-pem>"}),
            file=sys.stderr,
        )
        sys.exit(1)


def require_session(cfg: dict) -> None:
    """Exit with error if no active session is stored."""
    require_credentials(cfg)
    if not cfg.get("session_id"):
        print(
            json.dumps({"error": "No active session. Run: finance auth login"}),
            file=sys.stderr,
        )
        sys.exit(1)
