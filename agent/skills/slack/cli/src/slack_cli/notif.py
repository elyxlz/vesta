"""Maps inbound Slack events to Vesta notification files."""

import datetime as dt
import json
import pathlib
import re
import typing as tp
import uuid

import pydantic as pyd

MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")

ResolveName = tp.Callable[[str], str]


class SlackMessageEvent(pyd.BaseModel):
    """The subset of a Slack `message` event a notification needs."""

    model_config = pyd.ConfigDict(extra="ignore")

    type: str
    subtype: str | None = None
    user: str | None = None
    bot_id: str | None = None
    text: str = ""
    channel: str
    channel_type: str
    ts: str
    thread_ts: str | None = None


def humanize_mentions(text: str, resolve_user: ResolveName) -> str:
    return MENTION_RE.sub(lambda match: f"@{resolve_user(match.group(1))}", text)


def build_notification(
    event: SlackMessageEvent,
    *,
    bot_user_id: str,
    resolve_user: ResolveName,
    resolve_channel: ResolveName,
) -> dict[str, str | bool] | None:
    """Returns the notification for an inbound message, or None when it should be skipped (echoes, bots, edits)."""
    if event.type != "message" or event.subtype is not None:
        return None
    if event.bot_id is not None or event.user is None or event.user == bot_user_id:
        return None
    notif: dict[str, str | bool] = {
        "source": "slack",
        "type": "message",
        "timestamp": dt.datetime.fromtimestamp(float(event.ts), tz=dt.UTC).isoformat(),
        "message": humanize_mentions(event.text, resolve_user),
        "sender": resolve_user(event.user),
        "sender_id": event.user,
        "channel_id": event.channel,
        "message_ts": event.ts,
    }
    if event.thread_ts is not None:
        notif["thread_ts"] = event.thread_ts
    if event.channel_type != "im":
        notif["channel_name"] = f"#{resolve_channel(event.channel)}"
    mentioned = f"<@{bot_user_id}>" in event.text
    if mentioned:
        notif["mention"] = True
    direct = event.channel_type in ("im", "mpim")
    if not direct and not mentioned:
        notif["interrupt"] = False
    return notif


def write_notification(notifications_dir: pathlib.Path, notif: dict[str, str | bool]) -> pathlib.Path:
    notifications_dir.mkdir(parents=True, exist_ok=True)
    path = notifications_dir / f"{uuid.uuid4()}-{notif['source']}-{notif['type']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(notif, indent=2) + "\n")
    tmp.rename(path)
    return path
