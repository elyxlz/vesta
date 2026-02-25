"""Background monitor for task due date notifications."""

import json
import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, UTC
from pathlib import Path

from . import notifications

THRESHOLDS = [
    ("1 week", timedelta(weeks=1)),
    ("1 day", timedelta(days=1)),
    ("1 hour", timedelta(hours=1)),
    ("15 minutes", timedelta(minutes=15)),
]


def _get_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_datetime(dt_str: str) -> datetime:
    """Parse datetime string. Naive datetimes are treated as local time."""
    parsed = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if parsed.tzinfo:
        return parsed
    # Treat naive datetime as local time, then convert to UTC for comparison
    return parsed.astimezone(UTC)


def run(
    db_path: Path,
    notif_dir: Path,
    stop_event: threading.Event,
    logger: logging.Logger,
    check_interval: int = 60,
):
    logger.info("Task monitor thread started")

    while not stop_event.is_set():
        try:
            now = datetime.now(UTC)
            logger.info(f"Monitor check at {now.isoformat()}")

            with closing(_get_db(db_path)) as conn:
                cursor = conn.execute(
                    "SELECT id, title, due_date, priority, notified_thresholds FROM tasks WHERE status = 'pending' AND due_date IS NOT NULL"
                )
                rows = list(cursor)
                logger.info(f"Found {len(rows)} pending tasks with due dates")

                for row in rows:
                    task_id = row["id"]
                    title = row["title"]
                    due_date_str = row["due_date"]
                    priority = row["priority"]
                    notified_raw = row["notified_thresholds"]

                    notified: list[str] = json.loads(notified_raw) if notified_raw else []

                    try:
                        due_dt = _parse_datetime(due_date_str)
                        logger.info(f"Task '{title}': due_date={due_date_str}, parsed as {due_dt.isoformat()}")
                    except ValueError as e:
                        logger.error(f"Failed to parse due_date '{due_date_str}': {e}")
                        continue

                    for label, delta in THRESHOLDS:
                        if label in notified:
                            continue

                        trigger_time = due_dt - delta
                        logger.debug(
                            f"Task '{title}': {label} trigger={trigger_time.isoformat()}, now={now.isoformat()}, due={due_dt.isoformat()}"
                        )
                        if trigger_time <= now < due_dt:
                            logger.info(f"Writing {label} notification for task: {title}")
                            notifications.write_notification(
                                notif_dir,
                                task_id,
                                title,
                                due_date_str,
                                label,
                                priority,
                            )
                            notified.append(label)

                    if notified_raw != json.dumps(notified):
                        conn.execute(
                            "UPDATE tasks SET notified_thresholds = ? WHERE id = ?",
                            (json.dumps(notified), task_id),
                        )

                conn.commit()

            logger.debug(f"Task monitor check complete, sleeping for {check_interval} seconds")

        except Exception as e:
            logger.error(f"Error in task monitor loop: {e}", exc_info=True)

        if stop_event.wait(check_interval):
            break

    logger.info("Task monitor thread stopped")
