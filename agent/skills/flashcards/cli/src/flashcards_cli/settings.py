"""User-tunable settings, kept in the meta table so a change made by the CLI reaches the daemon on its next tick."""

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, time

from fsrs import Scheduler

from .db import get_meta, set_meta

# Wall-clock window, in the agent's own timezone, inside which the daemon nudges; "22:00-06:00" wraps midnight.
_ACTIVE_HOURS_FORMAT = "HH:MM-HH:MM"


@dataclass(frozen=True)
class Settings:
    desired_retention: float = 0.9
    maximum_interval_days: int = 365
    new_cards_per_day: int = 10
    nudge_interval_minutes: int = 120
    active_hours: str = "09:00-21:00"
    api_enabled: bool = False


SETTING_NAMES = tuple(f.name for f in fields(Settings))
_META_PREFIX = "setting:"


def _parse_clock(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def parse_active_hours(text: str) -> tuple[time, time]:
    try:
        start, end = text.split("-")
        return _parse_clock(start), _parse_clock(end)
    except ValueError:
        raise ValueError(f"active_hours must look like {_ACTIVE_HOURS_FORMAT}, got {text!r}") from None


def within_active_hours(settings: Settings, local_now: datetime) -> bool:
    start, end = parse_active_hours(settings.active_hours)
    now = local_now.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def _parse_value(name: str, raw: str) -> float | int | str | bool:
    if name == "api_enabled":
        lowered = raw.strip().lower()
        if lowered in ("true", "on", "yes", "1"):
            return True
        if lowered in ("false", "off", "no", "0"):
            return False
        raise ValueError("api_enabled must be true or false")
    if name == "desired_retention":
        value = float(raw)
        if not 0.7 <= value <= 0.99:
            raise ValueError("desired_retention must be between 0.7 and 0.99")
        return value
    if name == "active_hours":
        parse_active_hours(raw)
        return raw
    number = int(raw)
    if name == "maximum_interval_days" and number < 1:
        raise ValueError("maximum_interval_days must be at least 1")
    if number < 0:
        raise ValueError(f"{name} must be 0 or more")
    return number


def load_settings(conn: sqlite3.Connection) -> Settings:
    stored = {name: get_meta(conn, _META_PREFIX + name) for name in SETTING_NAMES}
    return Settings(**{name: _parse_value(name, raw) for name, raw in stored.items() if raw is not None})


def set_setting(conn: sqlite3.Connection, name: str, raw: str) -> Settings:
    if name not in SETTING_NAMES:
        raise ValueError(f"unknown setting {name!r}; one of: {', '.join(SETTING_NAMES)}")
    set_meta(conn, _META_PREFIX + name, str(_parse_value(name, raw)))
    return load_settings(conn)


def build_scheduler(settings: Settings) -> Scheduler:
    return Scheduler(desired_retention=settings.desired_retention, maximum_interval=settings.maximum_interval_days)
