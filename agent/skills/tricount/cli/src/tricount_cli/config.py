"""Config and credentials storage for tricount CLI."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".tricount"
CREDS_FILE = CONFIG_DIR / "credentials.json"


def creds_path() -> Path:
    return CREDS_FILE


def load_creds() -> dict | None:
    if CREDS_FILE.exists():
        return json.loads(CREDS_FILE.read_text())
    return None


def save_creds(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps(data, indent=2))
    CREDS_FILE.chmod(0o600)


def delete_creds() -> bool:
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()
        return True
    return False
