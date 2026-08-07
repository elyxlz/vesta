"""Daemon health record and daemon_unhealthy notification for the finance watcher.

The daemon contract's optional health half (`skills/vestad/SKILL.md`): the watcher records the
outcome of every poll in `~/agent/data/daemons/finance.health`, `finance daemon status` surfaces
that record beside `running`, and a persistently failing watcher writes one `daemon_unhealthy`
notification so a revoked credential reaches the agent instead of only the log file. The record
survives restarts on purpose: a restart does not fix a dead credential, and the persisted
`notified_at` is what keeps every restart from re-announcing a failure already reported.
"""

import dataclasses
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

NAME = "finance"
HEALTH_FILE = Path.home() / "agent" / "data" / "daemons" / f"{NAME}.health"
# The directory the engine watches (config.notifications_dir). A notification written anywhere
# else still succeeds: nothing is delivered and nothing errors.
NOTIFICATIONS_DIR = Path.home() / "agent" / "notifications"
# A permanent failure (a dead credential) never self-heals, so it is news on the first
# occurrence; a transient one (a 5xx, a dropped connection) earns this many consecutive
# failed polls before it is reported.
UNHEALTHY_AFTER_FAILURES = 3
# While the failure persists, one reminder this often; the recorded notified_at spaces them.
RENOTIFY_SECS = 86400


@dataclasses.dataclass(frozen=True)
class Health:
    """One poll cycle's verdict, as persisted: the first four fields are what status surfaces,
    notified_at is the notification bookkeeping and stays out of the status answer."""

    healthy: bool
    last_success_at: str | None
    consecutive_failures: int
    error: str | None
    notified_at: str | None


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to path atomically: write a sibling temp file, then rename over the target, so
    a reader polling the directory never observes a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def read_health() -> Health | None:
    """The recorded health, or None where there is no readable record: a daemon that has not
    attempted any work yet has no health opinion, and a corrupt record reads the same way rather
    than wedging status."""
    try:
        data = json.loads(HEALTH_FILE.read_text())
        return Health(
            healthy=bool(data["healthy"]),
            last_success_at=data["last_success_at"],
            consecutive_failures=int(data["consecutive_failures"]),
            error=data["error"],
            notified_at=data["notified_at"],
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write(health: Health) -> None:
    atomic_write_text(HEALTH_FILE, json.dumps(dataclasses.asdict(health)))


def record_success(now: datetime | None = None) -> None:
    """A poll cycle that did its job: healthy, counters cleared, and notified_at re-armed so a
    future lapse is announced again."""
    moment = (now if now is not None else datetime.now(UTC)).replace(microsecond=0)
    _write(Health(healthy=True, last_success_at=moment.isoformat(), consecutive_failures=0, error=None, notified_at=None))


def record_failure(error: str, *, permanent: bool, now: datetime | None = None) -> None:
    """A poll cycle that failed: update the record and, once the failure has earned it, write one
    daemon_unhealthy notification. The notification lands before notified_at is persisted, so a
    crash between the two re-announces later rather than suppressing a report that never went out.
    """
    moment = now if now is not None else datetime.now(UTC)
    previous = read_health()
    failures = (previous.consecutive_failures if previous is not None else 0) + 1
    last_success = previous.last_success_at if previous is not None else None
    notified_at = previous.notified_at if previous is not None else None
    if _due_to_notify(notified_at, failures, permanent=permanent, now=moment):
        _write_unhealthy_notification(error, failures, last_success, moment)
        notified_at = moment.replace(microsecond=0).isoformat()
    _write(Health(healthy=False, last_success_at=last_success, consecutive_failures=failures, error=error, notified_at=notified_at))


def _due_to_notify(notified_at: str | None, failures: int, *, permanent: bool, now: datetime) -> bool:
    if notified_at is None:
        return permanent or failures >= UNHEALTHY_AFTER_FAILURES
    try:
        last = datetime.fromisoformat(notified_at)
    except ValueError:
        return True
    return now - last >= timedelta(seconds=RENOTIFY_SECS)


def _write_unhealthy_notification(error: str, failures: int, last_success_at: str | None, now: datetime) -> None:
    since = f"has not succeeded since {last_success_at}" if last_success_at is not None else "has not succeeded once since it started"
    notification = {
        "type": "daemon_unhealthy",
        "source": NAME,
        # interrupt, like daemon_died: a broken poller silently loses every future transaction
        # and lets reads serve stale data, which is worth acting on now.
        "interrupt": True,
        "timestamp": now.replace(microsecond=0).isoformat(),
        "message": f"{NAME} watcher is running but failing: {failures} consecutive failed poll(s), {since}. "
        f"Latest error: {error}. Bank data reads may be stale. Check `finance daemon status` and "
        f"~/agent/logs/{NAME}.log; if the credential is dead, re-authenticate with `finance auth login`.",
    }
    filename = f"{time.time_ns()}-{NAME}-daemon_unhealthy.json"
    atomic_write_text(NOTIFICATIONS_DIR / filename, json.dumps(notification, indent=2))
