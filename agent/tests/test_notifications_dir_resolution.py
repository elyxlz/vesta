"""Skill watchers must write notifications into the directory the engine watches.

The engine reads `VestaConfig.notifications_dir`, `~/agent/notifications` in production. A watcher
that writes anywhere else still writes successfully, so the mismatch never raises: notifications
are simply never delivered and nothing complains. These tests import each watcher (the skill CLIs
are installed editable into this venv by check.sh) and check its destination against the engine's,
and guard against a home-relative `~/notifications` constant appearing anywhere under
`agent/skills`.
"""

import pathlib as pl
import re

import pytest
from finance_cli import transaction_watcher
from spotify_cli import organize

from core.config import VestaConfig

SKILLS_DIR = pl.Path(__file__).resolve().parents[1] / "skills"
HOME_RELATIVE = re.compile(r"""Path\.home\(\)\s*/\s*["']notifications["']""")


@pytest.mark.parametrize(
    "notifications_dir",
    [transaction_watcher.NOTIFICATIONS_DIR, organize.NOTIFICATIONS_DIR],
    ids=["finance", "spotify"],
)
def test_watcher_writes_into_the_directory_the_engine_watches(notifications_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_DIR", raising=False)
    assert notifications_dir == VestaConfig().notifications_dir


def test_no_skill_writes_to_the_home_notifications_dir() -> None:
    # Skill sources only: each skill CLI grows a `.venv` the first time its suite runs, and scanning
    # those reads tens of thousands of vendored files whose contents no rule here governs.
    sources = (p for p in SKILLS_DIR.rglob("*.py") if ".venv" not in p.parts)
    offenders = sorted(str(p.relative_to(SKILLS_DIR)) for p in sources if HOME_RELATIVE.search(p.read_text(errors="replace")))
    assert offenders == []
