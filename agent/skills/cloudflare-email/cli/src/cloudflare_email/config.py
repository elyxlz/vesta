"""Shared config + helpers for the cloudflare-email skill."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


CONFIG_DIR = Path.home() / ".cloudflare-email"
CONFIG_PATH = CONFIG_DIR / "config.json"
NOTIFICATIONS_DIR = Path.home() / "agent" / "notifications"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def agent_name() -> str:
    name = os.environ.get("AGENT_NAME", "").strip()
    if not name:
        raise RuntimeError("AGENT_NAME not set in environment")
    return name


def email_domain() -> str:
    cfg = load_config()
    domain = cfg.get("domain") or os.environ.get("CF_EMAIL_DOMAIN", "vesta.run")
    return domain


def email_address() -> str:
    return f"{agent_name().lower()}@{email_domain()}"


def keeper_get(path: str) -> str:
    """Read a value from keeper. Returns empty string on miss."""
    try:
        out = subprocess.run(
            ["keeper", "get", path],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def keeper_store(path: str, value: str) -> bool:
    try:
        result = subprocess.run(
            ["keeper", "store", path, value],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def cf_api_token() -> str:
    token = keeper_get("cloudflare/api-token")
    if not token:
        raise RuntimeError("Cloudflare API token missing. Run: keeper store cloudflare/api-token '<token>'")
    return token


def worker_secret() -> str:
    return keeper_get("cloudflare-email/worker-secret")
