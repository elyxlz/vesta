#!/usr/bin/env python3
"""Dynamic resolver for Thunderbird's published Google OAuth client.

The email-client skill rides Thunderbird's PUBLIC verified Google OAuth client
(currently ...t1hgqj) so users skip standing up their own Google Cloud app plus
verification/CASA. That shared client is a commons policed by Google: it can be
rotated or deleted upstream at any time. The previous client shipped here
(...t1glqf) went DEAD (Google returned invalid_client / "not found") and
silently broke Gmail for everyone until caught by hand.

This module makes that precarity observable and recoverable. Instead of trusting
only the hardcoded constant, it fetches Thunderbird's CURRENT published Google
client id/secret from comm-central's canonical ``OAuth2Providers.sys.mjs``
source, caches it locally with a timestamp, and refreshes on a schedule. On any
fetch or parse failure it falls back to the caller-supplied hardcoded constant,
which stays the guaranteed floor.

This is Google-specific. No other provider's credentials are touched here.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import time
import urllib.request

logger = logging.getLogger(__name__)

# comm-central's canonical OAuth2 provider registry. This is the file Thunderbird
# ships its published desktop-client ids/secrets in; the Google entry lives in the
# ``kIssuers`` map keyed by ``accounts.google.com``.
OAUTH2PROVIDERS_URL = "https://raw.githubusercontent.com/mozilla/releases-comm-central/master/mailnews/base/src/OAuth2Providers.sys.mjs"

# Refresh the local cache once it is older than this. A week is well inside how
# fast Mozilla could plausibly rotate the client, while keeping us off the
# network on essentially every normal command.
DEFAULT_MAX_AGE_DAYS = 7

CACHE_FILENAME = "thunderbird_google_client.json"


def _state_dir() -> pathlib.Path:
    """Top-level email-client state dir (mirrors imap_client._state_dir).

    Duplicated deliberately so this module has no dependency on imap_client
    (which pulls in imap_tools/msal) and stays unit-testable on its own.
    """
    explicit = os.environ.get("EMAIL_CLIENT_DIR")
    d = pathlib.Path(explicit) if explicit else pathlib.Path.home() / ".email-client"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path() -> pathlib.Path:
    return _state_dir() / CACHE_FILENAME


def parse_google_client(text: str) -> tuple[str, str] | None:
    """Extract ``(client_id, client_secret)`` for accounts.google.com.

    The source is prettier-formatted JS, so the ``clientId`` value is often
    wrapped onto its own line. ``\\s`` spans newlines, so the field regexes match
    across the wrap. Returns None if the block or either field is missing, or if
    the client id does not look like a Google OAuth client (a cheap guard against
    latching onto the wrong issuer block).
    """
    m = re.search(r'name:\s*"accounts\.google\.com"', text)
    if not m:
        return None
    # Bound the search to the accounts.google.com issuer object so we can never
    # pick up clientId/clientSecret from a neighbouring provider block.
    window = text[m.start() : m.start() + 1200]
    cid = re.search(r'clientId:\s*"([^"]+)"', window)
    csec = re.search(r'clientSecret:\s*"([^"]+)"', window)
    if not cid or not csec:
        return None
    client_id = cid.group(1)
    if not client_id.endswith(".apps.googleusercontent.com"):
        return None
    return client_id, csec.group(1)


def fetch_google_client(url: str = OAUTH2PROVIDERS_URL, timeout: int = 15) -> tuple[str, str]:
    """Fetch and parse the current Google client. Raises on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "email-client-selfheal"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
    parsed = parse_google_client(text)
    if not parsed:
        raise ValueError("could not parse Google client from OAuth2Providers source")
    return parsed


def _read_cache() -> dict | None:
    p = cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("client_id") or not data.get("client_secret"):
        return None
    return data


def _write_cache(client_id: str, client_secret: str, now: float, url: str) -> None:
    p = cache_path()
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "fetched_at": now,
        "source_url": url,
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(p)


def resolve_google_client(
    fallback_client_id: str,
    fallback_client_secret: str,
    *,
    allow_fetch: bool = True,
    force_refresh: bool = False,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: float | None = None,
    fetcher=None,
) -> dict:
    """Resolve the Google OAuth client id/secret, self-healing from upstream.

    Returns ``{"client_id", "client_secret", "source", "fetched_at"}`` where
    ``source`` is one of:

        "cache"       fresh cache (younger than ``max_age_days``)
        "cache-stale" cache older than the threshold, kept because a refresh was
                      not attempted (allow_fetch=False) or the network fetch failed
        "fetched"     freshly pulled from comm-central this call
        "fallback"    hardcoded constant (no usable cache, fetch off or failed)

    ``allow_fetch=False`` guarantees no network access — callers on the hot path
    (building a provider profile) use this so normal commands stay fast and
    offline-safe. The daily probe and self-heal call with ``allow_fetch=True``
    (and ``force_refresh=True`` for self-heal) to actually track upstream.
    """
    now = now if now is not None else time.time()
    cache = _read_cache()
    fresh = bool(cache) and (now - float(cache.get("fetched_at") or 0)) < max_age_days * 86400

    if cache and fresh and not force_refresh:
        return {
            "client_id": cache["client_id"],
            "client_secret": cache["client_secret"],
            "source": "cache",
            "fetched_at": cache.get("fetched_at"),
        }

    if allow_fetch:
        try:
            client_id, client_secret = (fetcher or fetch_google_client)()
            _write_cache(client_id, client_secret, now, OAUTH2PROVIDERS_URL)
            return {
                "client_id": client_id,
                "client_secret": client_secret,
                "source": "fetched",
                "fetched_at": now,
            }
        except Exception as err:
            logger.warning("google client fetch failed, using best available fallback: %s", err)

    if cache and cache.get("client_id"):
        # A stale-but-real Thunderbird value beats the hardcoded constant: it was
        # pulled from the canonical source at some point, so it tracks upstream
        # more closely than a value baked in at release time.
        return {
            "client_id": cache["client_id"],
            "client_secret": cache["client_secret"],
            "source": "cache" if fresh else "cache-stale",
            "fetched_at": cache.get("fetched_at"),
        }

    return {
        "client_id": fallback_client_id,
        "client_secret": fallback_client_secret,
        "source": "fallback",
        "fetched_at": None,
    }
