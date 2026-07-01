"""Shared on-disk referral code — the bridge from the `account` skill.

The account skill and this one are separate Python packages (they can't import
each other), so this file mirrors `account_cli.referral_store` byte-for-byte on
the path: the account skill is the only place the code is ever SET
(`vesta-cloud-account set-referral`); this reader is the only thing this skill
does with it. Plain UTF-8 text = the code, stripped. A missing or empty file
means "no code configured".
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
