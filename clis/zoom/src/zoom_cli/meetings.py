from typing import Any

import httpx

from . import auth
from .config import Config

API_BASE = "https://api.zoom.us/v2"


def _headers(config: Config) -> dict[str, str]:
    token = auth.get_token(config)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_meeting(
    config: Config,
    *,
    topic: str,
    duration: int,
    start_time: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "topic": topic,
        "type": 2 if start_time else 1,
        "duration": duration,
    }
    if start_time:
        body["start_time"] = start_time
    if timezone:
        body["timezone"] = timezone

    resp = httpx.post(
        f"{API_BASE}/users/me/meetings",
        headers=_headers(config),
        json=body,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "id": data["id"],
        "join_url": data["join_url"],
        "start_url": data["start_url"],
        "password": data.get("password", ""),
        "start_time": data.get("start_time", ""),
        "duration": data.get("duration", 0),
    }


def list_meetings(config: Config) -> list[dict[str, Any]]:
    resp = httpx.get(
        f"{API_BASE}/users/me/meetings",
        headers=_headers(config),
        params={"type": "upcoming", "page_size": 30},
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "id": m["id"],
            "topic": m.get("topic", ""),
            "start_time": m.get("start_time", ""),
            "duration": m.get("duration", 0),
            "join_url": m.get("join_url", ""),
        }
        for m in data.get("meetings", [])
    ]


def delete_meeting(config: Config, *, meeting_id: str) -> dict[str, str]:
    resp = httpx.delete(
        f"{API_BASE}/meetings/{meeting_id}",
        headers=_headers(config),
    )
    resp.raise_for_status()
    return {"status": "deleted", "meeting_id": meeting_id}
