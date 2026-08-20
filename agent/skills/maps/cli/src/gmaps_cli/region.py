"""The default `--country`, inferred from the box's IANA timezone.

The agent process exports `TZ` from its configured timezone and every maps invocation inherits
it, so the user's zone is already in the environment. tzdata's `zone.tab` maps a zone name to
exactly one country, and it keeps the per-country names devices actually report (`Europe/Oslo`,
`Europe/Vatican`), which `zone1970.tab` folds into multi-country lines. An explicit `--country`
always wins, and a box with no resolvable zone keeps the `us` fallback.
"""

from __future__ import annotations

import os
from pathlib import Path

FALLBACK_COUNTRY = "us"
ZONE_TAB = Path("/usr/share/zoneinfo/zone.tab")
LOCALTIME = Path("/etc/localtime")


def local_zone() -> str | None:
    zone = os.environ.get("TZ")
    if zone:
        return zone
    if LOCALTIME.is_symlink():
        target = os.fspath(LOCALTIME.readlink())
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", maxsplit=1)[1]
    return None


def country_for_zone(zone: str | None, tab: Path | None = None) -> str:
    tab = ZONE_TAB if tab is None else tab
    if zone is None or not tab.exists():
        return FALLBACK_COUNTRY
    for line in tab.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 3 and fields[2] == zone:
            return fields[0].lower()
    return FALLBACK_COUNTRY


def default_country() -> str:
    return country_for_zone(local_zone())
