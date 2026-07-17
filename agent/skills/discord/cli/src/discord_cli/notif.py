"""Maps inbound Discord messages to Vesta notification files."""

import datetime as dt
import json
import pathlib
import uuid

import pydantic as pyd


class MessageFacts(pyd.BaseModel):
    """Library-agnostic facts about one inbound message, extracted from the gateway event."""

    content: str
    author_name: str
    author_id: str
    author_is_self: bool
    author_is_bot: bool
    channel_id: str
    channel_name: str | None = None
    server: str | None = None
    is_dm: bool
    mentions_me: bool
    message_id: str
    timestamp: dt.datetime


def build_notification(facts: MessageFacts) -> dict[str, str | bool] | None:
    """Returns the notification for an inbound message, or None for Vesta's own echoes."""
    if facts.author_is_self:
        return None
    notif: dict[str, str | bool] = {
        "source": "discord",
        "type": "message",
        "timestamp": facts.timestamp.isoformat(),
        "message": facts.content,
        "sender": facts.author_name,
        "sender_id": facts.author_id,
        "channel_id": facts.channel_id,
        "message_id": facts.message_id,
    }
    if facts.channel_name is not None:
        notif["channel_name"] = facts.channel_name
    if facts.server is not None:
        notif["server"] = facts.server
    if facts.author_is_bot:
        notif["from_bot"] = True
    if facts.mentions_me:
        notif["mention"] = True
    if not facts.is_dm and not facts.mentions_me:
        notif["interrupt"] = False
    return notif


def daemon_died_notification() -> dict[str, str | bool]:
    """The notification the gateway daemon writes when it exits, so the agent restarts it.
    interrupt defaults on (discord is a live channel), so a dead daemon preempts."""
    return {
        "source": "discord",
        "type": "daemon_died",
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
    }


def write_notification(notifications_dir: pathlib.Path, notif: dict[str, str | bool]) -> pathlib.Path:
    notifications_dir.mkdir(parents=True, exist_ok=True)
    path = notifications_dir / f"{uuid.uuid4()}-{notif['source']}-{notif['type']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(notif, indent=2) + "\n")
    tmp.rename(path)
    return path
