"""Shared on-disk referral code — the bridge between this skill and `onboard`.

The account skill and the onboard skill are separate Python packages (they can't
import each other), so this file is the contract between them: `account` is the
only place the code is ever SET (`vesta-cloud-account set-referral`); `onboard`
only reads it, once, when it needs to attribute a completed invite. Plain UTF-8
text = the code, stripped. A missing or empty file means "no code configured".
"""

from __future__ import annotations

from pathlib import Path

PATH = Path.home() / ".config" / "vesta" / "referral_code"


def get_referral_code() -> str | None:
    """The stored referral code, or None if unset."""
    try:
        code = PATH.read_text().strip()
    except OSError:
        return None
    return code or None


def set_referral_code(code: str) -> None:
    """Persist ``code`` (stripped) to the shared referral file, creating its parent dir."""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(code.strip() + "\n")


def clear_referral_code() -> None:
    """Remove the shared referral file, if present."""
    PATH.unlink(missing_ok=True)
