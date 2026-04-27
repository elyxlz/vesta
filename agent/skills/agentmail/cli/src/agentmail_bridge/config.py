"""Shared config + helpers for the agentmail skill."""

from __future__ import annotations

import json
import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".agentmail"
CONFIG_PATH = CONFIG_DIR / "config.json"
NOTIFICATIONS_DIR = Path.home() / "agent" / "notifications"

# Local install of the official AgentMail npm CLI. Setup runs
# `npm install agentmail-cli` here (no -g) so our Python `agentmail` binary
# can passthrough to it without colliding on PATH.
NPM_CLI_DIR = CONFIG_DIR / "node_modules"
NPM_CLI_BIN = NPM_CLI_DIR / ".bin" / "agentmail"

AGENTMAIL_API_KEY_ENV = "AGENTMAIL_API_KEY"
AGENTMAIL_WEBHOOK_SECRET_ENV = "AGENTMAIL_WEBHOOK_SECRET"


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


def email_address() -> str:
    cfg = load_config()
    if "email_address" in cfg:
        return cfg["email_address"]
    return f"{agent_name().lower()}@agentmail.to"


def bashrc_set(key: str, value: str) -> None:
    """Persist KEY=VALUE in ~/.bashrc and the current process env. Replaces any
    prior export for the same key."""
    bashrc = Path.home() / ".bashrc"
    text = bashrc.read_text() if bashrc.exists() else ""
    lines = [line for line in text.splitlines() if not line.startswith(f"export {key}=")]
    lines.append(f"export {key}={value}")
    bashrc.write_text("\n".join(lines) + "\n")
    os.environ[key] = value


def api_key() -> str:
    key = os.environ.get(AGENTMAIL_API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"{AGENTMAIL_API_KEY_ENV} not set. Run `agentmail setup` to configure it.")
    return key


def webhook_secret() -> str:
    return os.environ.get(AGENTMAIL_WEBHOOK_SECRET_ENV, "").strip()
