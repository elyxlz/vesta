"""Shared config + helpers for the cloudflare-email skill."""

from __future__ import annotations

import json
import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".cloudflare-email"
CONFIG_PATH = CONFIG_DIR / "config.json"
NOTIFICATIONS_DIR = Path.home() / "agent" / "notifications"

CF_API_TOKEN_ENV = "CF_API_TOKEN"
CF_WORKER_SECRET_ENV = "CF_WORKER_SECRET"


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


def bashrc_set(key: str, value: str) -> None:
    """Persist KEY=VALUE in ~/.bashrc, replacing any prior export. Also sets it
    in the current process so the same setup run can use it without restart."""
    bashrc = Path.home() / ".bashrc"
    text = bashrc.read_text() if bashrc.exists() else ""
    lines = [line for line in text.splitlines() if not line.startswith(f"export {key}=")]
    lines.append(f"export {key}={value}")
    bashrc.write_text("\n".join(lines) + "\n")
    os.environ[key] = value


def cf_api_token() -> str:
    token = os.environ.get(CF_API_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(f"{CF_API_TOKEN_ENV} not set. Run `cloudflare-email setup` to configure it.")
    return token


def worker_secret() -> str:
    return os.environ.get(CF_WORKER_SECRET_ENV, "").strip()
