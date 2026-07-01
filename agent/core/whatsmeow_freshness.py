"""Runtime check: notify when the whatsapp skill's whatsmeow drifts behind upstream HEAD.

An outdated whatsmeow gets a hard WhatsApp "Client outdated (405)" reject and is an
extra stale-client ban signal, so the skill should ride the bleeding edge (the latest
`go.mau.fi/whatsmeow` main commit). On boot this compares the pinned version to the
current HEAD and, if behind, drops a passive `source=core` notification the agent can
act on (it can run the one-line update itself). Best-effort: it never blocks boot and
fails open on any network/parse error, and it no-ops when the whatsapp skill is not
installed (no go.mod on disk).
"""

from __future__ import annotations

import datetime as dt
import re

import aiohttp

from . import logger
from . import models as vm
from .loops import drop_core_notification

_WM_RE = re.compile(r"go\.mau\.fi/whatsmeow\s+(v\S+)")
_PSEUDO_RE = re.compile(r"v0\.0\.0-(\d{14})-([0-9a-f]+)")
_HEAD_API = "https://api.github.com/repos/tulir/whatsmeow/commits/main"
_HTTP_TIMEOUT_S = 8.0


def installed_version(gomod_text: str) -> str | None:
    """The pinned whatsmeow version from a go.mod body, or None if absent."""
    m = _WM_RE.search(gomod_text)
    return m.group(1) if m else None


def _pseudo_parts(version: str) -> tuple[dt.datetime, str] | None:
    """(commit time, short hash) parsed from a `v0.0.0-DATE-HASH` pseudo-version."""
    m = _PSEUDO_RE.search(version)
    if m is None:
        return None
    try:
        when = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC)
    except ValueError:
        return None
    return when, m.group(2)


def is_behind(installed: str, head_sha: str, head_time: dt.datetime) -> bool:
    """True when `installed` is an older commit than HEAD. Conservative: if the pinned
    version isn't a parseable pseudo-version, or already matches HEAD, return False."""
    parts = _pseudo_parts(installed)
    if parts is None:
        return False
    when, short = parts
    if head_sha.startswith(short):
        return False  # already on HEAD
    return when < head_time


async def latest_head() -> tuple[str, dt.datetime] | None:
    """(sha, commit time) of whatsmeow's main HEAD, or None on any failure."""
    try:
        timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_HEAD_API) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        sha = data["sha"]
        when = dt.datetime.fromisoformat(data["commit"]["committer"]["date"].replace("Z", "+00:00"))
        return sha, when
    except (aiohttp.ClientError, KeyError, ValueError, TypeError):
        return None


async def check_whatsmeow_freshness(config: vm.VestaConfig) -> None:
    """Drop a passive notification if the installed whatsapp-skill whatsmeow is behind
    upstream HEAD. Never raises; safe to fire-and-forget at boot."""
    try:
        gomod = config.skills_dir / "whatsapp" / "cli" / "go.mod"
        if not gomod.exists():
            return  # whatsapp skill not installed
        installed = installed_version(gomod.read_text())
        if installed is None:
            return
        head = await latest_head()
        if head is None:
            return  # fail open on network error
        sha, when = head
        if not is_behind(installed, sha, when):
            return
        body = (
            f"The whatsapp skill is on an outdated whatsmeow ({installed}); upstream HEAD is "
            f"{sha[:12]} ({when.date().isoformat()}). An outdated whatsmeow gets a WhatsApp "
            f"'Client outdated' (405) reject and is an extra stale-client ban signal, so it should "
            f"ride the bleeding edge. To fix: in skills/whatsapp/cli run "
            f"`go get go.mau.fi/whatsmeow@latest && go mod tidy`, then rebuild the skill."
        )
        # Fixed filename stem so repeated boots overwrite rather than pile up duplicates.
        drop_core_notification(type_=vm.TYPE_WHATSMEOW_STALE, body=body, interrupt=False, config=config, name=vm.TYPE_WHATSMEOW_STALE)
        logger.init(f"whatsmeow stale: pinned {installed} behind HEAD {sha[:12]} ({when.date().isoformat()})")
    except Exception as e:  # a maintenance check must never break boot
        logger.init(f"whatsmeow freshness check skipped: {e}")
