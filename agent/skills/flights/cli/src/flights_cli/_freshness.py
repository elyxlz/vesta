"""Preflight guard against running on a stale scraper dependency.

Some skills wrap reverse-engineered libraries (fli for Google Flights,
pyicloud for iCloud) that track upstream sites which change format without
notice. A version behind PyPI is how such a skill silently starts returning
nothing (issue #822). `require_latest` compares the installed version against
PyPI's latest and exits non-zero when behind, turning silent drift into a
loud, actionable error that a `uv tool install --editable --force --reinstall .` clears.

On any network / PyPI failure staleness cannot be proven, so it warns and
returns rather than blocking a working install on a transient PyPI outage.
"""

import json
import sys
import urllib.request
from importlib.metadata import PackageNotFoundError, version

PYPI_TIMEOUT_SECS = 5


def _release_tuple(raw: str) -> tuple[int, ...]:
    """Numeric release segments of a version, ignoring any pre/post suffix."""
    segments = []
    for segment in raw.split("."):
        digits = ""
        for ch in segment:
            if not ch.isdigit():
                break
            digits += ch
        segments.append(int(digits) if digits else 0)
    return tuple(segments)


def require_latest(package: str) -> None:
    """Exit non-zero if `package` is behind its latest PyPI release.

    Prints the error and warnings to stderr so they never contaminate the
    JSON a command writes to stdout.
    """
    try:
        installed = version(package)
    except PackageNotFoundError:
        print(json.dumps({"error": f"{package} is not installed"}), file=sys.stderr)
        sys.exit(1)

    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=PYPI_TIMEOUT_SECS) as resp:
            latest = json.load(resp)["info"]["version"]
    except Exception as exc:
        print(f"warning: could not verify {package} is current against PyPI: {exc}", file=sys.stderr)
        return

    if _release_tuple(installed) < _release_tuple(latest):
        print(
            json.dumps(
                {
                    "error": (
                        f"{package} {installed} is behind the latest release {latest}. This skill wraps a "
                        f"reverse-engineered library that breaks when it falls behind upstream; reinstall to "
                        f"update: cd ~/agent/skills/<skill>/cli && uv tool install --editable --force --reinstall ."
                    )
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)
