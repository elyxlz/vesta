import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from zoneinfo import ZoneInfo

from . import auth, capture, folders, graph, notifications, notify, owa_rest, teams
from .config import Config
from .context import MicrosoftContext

_HTML_TAG = re.compile(r"<[^>]+>")

_CATCHUP_GAP_SECONDS = 90
_FRESH_START_LOOKBACK = timedelta(hours=1)
# Bounds how much history a long-dead unit re-reads once it heals, so recovery cannot flood the user.
_MAX_CATCHUP = timedelta(days=7)
# Bounds a cycle's drain per folder in volume as _MAX_CATCHUP bounds it in time; later cycles drain the rest.
_MAIL_PAGE_SIZE = 50
_MAX_WINDOW_MESSAGES = 500


# Zero-width and bidi / formatting characters that marketing emails use to pad previews with
# invisible tokens. Strip before truncating so the 200-char budget buys real signal.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
_WHITESPACE_RUN = re.compile(r"\s+")


def clean_preview(text: str) -> str:
    """Drop zero-width / bidi characters, collapse whitespace, strip."""
    return _WHITESPACE_RUN.sub(" ", _INVISIBLE.sub("", text)).strip()


def strip_fractional(iso: str) -> str:
    """Remove fractional seconds from an ISO-8601 datetime string (Graph returns '.0000000')."""
    return re.sub(r"\.\d+", "", iso)


class MonitorState(TypedDict):
    """last_cycle seeds a unit polled for the first time; units maps "<kind>:<account>" to the end of
    the last window that unit read successfully."""

    last_cycle: str
    units: dict[str, str]


def _read_state(path: Path, now: datetime) -> MonitorState:
    """A legacy bare-timestamp file reads as a last_cycle with no units, so every unit resumes from
    where the old monitor left off."""
    raw = path.read_text().strip() if path.exists() else ""
    if not raw:
        return MonitorState(last_cycle=(now - _FRESH_START_LOOKBACK).isoformat(), units={})
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return MonitorState(last_cycle=raw, units={})
    match parsed:
        case {"last_cycle": str(last_cycle), "units": dict(units)}:
            return MonitorState(last_cycle=last_cycle, units={str(unit): str(watermark) for unit, watermark in units.items()})
        case _:
            raise ValueError(f"Malformed monitor state in {path}: {raw[:100]}")


def _write_state(path: Path, state: MonitorState) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.rename(path)


def _poll_unit(
    ctx: MicrosoftContext, state: MonitorState, unit: str, new_check_time: datetime, poll: Callable[[datetime, bool], datetime | None]
) -> None:
    """Advance the unit's watermark only across the window the poll reports reading through, so a
    failed or part-drained poll re-reads the rest next cycle instead of skipping what it never read."""
    units = state["units"]
    last_dt = max(datetime.fromisoformat(units[unit] if unit in units else state["last_cycle"]), new_check_time - _MAX_CATCHUP)
    gap_seconds = (new_check_time - last_dt).total_seconds()
    catching_up = gap_seconds > _CATCHUP_GAP_SECONDS
    if catching_up:
        ctx.monitor_logger.info("Catching up %s from %s, %.0fs behind", unit, last_dt.isoformat(), gap_seconds)
    read_through = poll(last_dt, catching_up)
    units[unit] = last_dt.isoformat() if read_through is None else read_through.isoformat()


def _whole_window(new_check_time: datetime, poll: Callable[[datetime, bool], bool]) -> Callable[[datetime, bool], datetime | None]:
    """Adapt a poll that reads its window in one shot: it read through the whole cycle, or not at all."""
    return lambda last_dt, catching_up: new_check_time if poll(last_dt, catching_up) else None


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    """A unit read through only as far as its least-drained folder; a folder it could not read wins."""
    if left is None or right is None:
        return None
    return min(left, right)


def _window_read_through(messages: list[dict], new_check_time: datetime) -> datetime | None:
    """How far a fetch honestly read its window: a full-limit response holds more than one cycle drains, so it
    read only as far as the last message fetched. An unusable timestamp reports the window unread, not drained."""
    if len(messages) < _MAX_WINDOW_MESSAGES:
        return new_check_time
    newest = messages[-1]
    if "receivedDateTime" not in newest:
        return None
    try:
        received = datetime.fromisoformat(newest["receivedDateTime"])
    except ValueError:
        return None
    return received if received.tzinfo else None


class EmailAddress(TypedDict):
    name: NotRequired[str]
    address: str


class EmailFrom(TypedDict):
    emailAddress: EmailAddress


class Email(TypedDict):
    id: str
    subject: NotRequired[str]
    from_: NotRequired[EmailFrom]  # 'from' is reserved
    bodyPreview: NotRequired[str]
    receivedDateTime: NotRequired[str]


class EventTime(TypedDict):
    dateTime: str
    timeZone: NotRequired[str]


class EventLocation(TypedDict):
    displayName: NotRequired[str]


class CalendarEvent(TypedDict):
    id: str
    subject: NotRequired[str]
    start: EventTime
    location: NotRequired[EventLocation]


def _parse_event_time(event: CalendarEvent) -> datetime:
    """Parse event start time to UTC-aware datetime. Raises ValueError on failure."""
    start = event["start"]
    start_dt = start["dateTime"]
    start_tz = start["timeZone"] if "timeZone" in start else None

    # Check for timezone info: Z, +HH:MM, or -HH:MM
    has_tz = start_dt.endswith("Z") or "+" in start_dt or (start_dt.count("-") > 2)
    if has_tz:
        return datetime.fromisoformat(start_dt)

    # Local time without timezone - use the event's timeZone field
    if not start_tz:
        raise ValueError(f"Event has dateTime without timezone info: {start_dt}")
    try:
        naive_time = datetime.fromisoformat(start_dt)
        local_tz = ZoneInfo(start_tz)
        return naive_time.replace(tzinfo=local_tz).astimezone(UTC)
    except Exception as e:
        raise ValueError(f"Failed to parse event time {start_dt} with tz {start_tz}: {e}") from e


def _format_threshold_label(minutes: int) -> str:
    """Convert minutes to human-readable label like '1 week', '2 hours'."""
    if minutes >= 10080:
        n = minutes // 10080
        return f"{n} week" + ("s" if n > 1 else "")
    if minutes >= 1440:
        n = minutes // 1440
        return f"{n} day" + ("s" if n > 1 else "")
    if minutes >= 60:
        n = minutes // 60
        return f"{n} hour" + ("s" if n > 1 else "")
    return f"{minutes} minute" + ("s" if minutes != 1 else "")


def _emit_email_notification(ctx: MicrosoftContext, email: dict, account: str, folder_token: str, catching_up: bool) -> None:
    """Write an email notification from a graph-shaped message dict (Graph and OWA REST both use it)."""
    logger = ctx.monitor_logger
    email_from = email["from"] if "from" in email else None
    if not email_from or "emailAddress" not in email_from:
        logger.warning("Email missing sender info: %s", email["id"] if "id" in email else "?")
        return
    sender = email_from["emailAddress"]
    sender_name = sender["name"] if "name" in sender else None
    sender_addr = sender["address"] if "address" in sender else None
    if not sender_addr:
        logger.warning("Email sender missing address: %s", email["id"] if "id" in email else "?")
        return
    logger.info("Writing notification for email from %s", sender_addr)
    display_name = sender_name or sender_addr
    # Only include sender_address when it adds info beyond the display name.
    extra_addr = sender_addr if sender_name and sender_name != sender_addr else None
    notifications.write_notification(
        ctx.notif_dir,
        "email",
        # Email pools by default (calendar reminders keep interrupting); the user adds
        # interrupt rules for the senders/keywords that should reach them right away.
        interrupt=False,
        sender=display_name,
        subject=email["subject"] if "subject" in email else None,
        preview=clean_preview(email["bodyPreview"] if "bodyPreview" in email else "")[:200],
        sender_address=extra_addr,
        account=account,
        folder=folder_token,
        missed=catching_up or None,
    )


def _emit_calendar_reminders(
    ctx: MicrosoftContext, events: list, account: str, last_dt: datetime, new_check_time: datetime, catching_up: bool
) -> None:
    """Write calendar reminders for events crossing a notify threshold this cycle (Graph and OWA REST)."""
    logger = ctx.monitor_logger
    for event in events:
        try:
            event_time = _parse_event_time(event)
        except (KeyError, ValueError) as e:
            logger.warning("Skipping event %s: %s", event["id"] if "id" in event else "?", e)
            continue

        start_dt = event["start"]["dateTime"]
        location = event["location"] if "location" in event else None
        loc = location["displayName"] if location and "displayName" in location else None
        subject = (event["subject"] if "subject" in event else None) or "(No title)"
        mins_until = int((event_time - new_check_time).total_seconds() / 60)

        for threshold_mins in ctx.get_calendar_notify_thresholds():
            trigger_time = event_time - timedelta(minutes=threshold_mins)
            if not (last_dt <= trigger_time < new_check_time):
                continue
            label = _format_threshold_label(threshold_mins)
            logger.info("Writing %s reminder for calendar event: %s", label, subject)
            notifications.write_notification(
                ctx.notif_dir,
                "calendar",
                subject=subject,
                start_time=strip_fractional(start_dt),
                minutes_until=mins_until,
                location=loc,
                account=account,
                missed=(catching_up and event_time < new_check_time) or None,
            )


def _poll_owa_rest_mail(
    ctx: MicrosoftContext,
    config: Config,
    account_email: str,
    watch_folders: list[str],
    new_check_time: datetime,
    last_dt: datetime,
    catching_up: bool,
) -> datetime | None:
    """Poll a locked-tenant OWA REST account's watched folders for new mail, returning how far its
    mail was read. Fetching runs through load_token, so this also keeps the token warm."""
    logger = ctx.monitor_logger
    read_through: datetime | None = new_check_time
    for folder_token in watch_folders:
        try:
            messages = owa_rest.list_messages_since(
                ctx.http_client,
                account_email,
                config,
                folder=folder_token,
                since_utc=last_dt.isoformat().replace("+00:00", "Z"),
                limit=_MAX_WINDOW_MESSAGES,
            )
            logger.info("OWA REST: %d new emails for %s in %s", len(messages), account_email, folder_token)
            for message in messages:  # oldest first, matching arrival order
                _emit_email_notification(ctx, message, account_email, folder_token, catching_up)
            read_through = _earliest(read_through, _window_read_through(messages, new_check_time))
        except Exception as e:
            logger.error("Error fetching OWA REST emails for %s folder %s: %s", account_email, folder_token, e)
            read_through = None
    return read_through


def _poll_owa_rest_calendar(
    ctx: MicrosoftContext,
    config: Config,
    account_email: str,
    new_check_time: datetime,
    last_dt: datetime,
    catching_up: bool,
) -> bool:
    """Emit a locked-tenant OWA REST account's calendar reminders, True when the calendar was read."""
    logger = ctx.monitor_logger
    try:
        max_threshold = max(ctx.get_calendar_notify_thresholds())
        window_end = new_check_time + timedelta(minutes=max_threshold + 60)
        events = owa_rest.list_events(
            ctx.http_client,
            account_email,
            config,
            start_utc=last_dt.isoformat().replace("+00:00", "Z"),
            end_utc=window_end.isoformat().replace("+00:00", "Z"),
            limit=100,
        )
        _emit_calendar_reminders(ctx, events, account_email, last_dt, new_check_time, catching_up)
    except Exception as e:
        logger.error("Error fetching OWA REST calendar for %s: %s", account_email, e)
        return False
    return True


class Identity(TypedDict):
    """A Graph identity (a chatMessage's author, a conversationMember). Graph sends a null
    displayName for removed, federated, and anonymous users."""

    id: str
    displayName: NotRequired[str | None]


class IdentitySet(TypedDict):
    """A chatMessage's `from`: a user, an app, or neither (system events carry `from: null`)."""

    user: NotRequired[Identity | None]
    application: NotRequired[Identity | None]


class ItemBody(TypedDict):
    """A message body."""

    content: NotRequired[str | None]


# One shape over from/body/createdDateTime covers both a Graph chatMessage (the channel path) and a
# chatMessageInfo (a chat's lastMessagePreview): the poller reads only those fields, so conflating the
# two resources is safe. `from` is a keyword, so the functional TypedDict form is the only way to name it.
ChatMessage = TypedDict(
    "ChatMessage",
    {
        "from": NotRequired[IdentitySet | None],
        "body": NotRequired[ItemBody | None],
        "createdDateTime": NotRequired[str],
    },
)


class ConversationMember(TypedDict):
    """A chat member as the poller reads it."""

    displayName: NotRequired[str | None]


class Chat(TypedDict):
    """A Graph chat as the poller reads it. lastMessagePreview is null for a chat with no messages."""

    id: str
    topic: NotRequired[str | None]
    members: NotRequired[list[ConversationMember]]
    lastMessagePreview: NotRequired[ChatMessage | None]


class ChannelResource(TypedDict):
    """A Graph team or channel as the poller reads it."""

    id: NotRequired[str]
    displayName: NotRequired[str | None]


class TeamsNotifiable(TypedDict):
    """What a Teams notification says about a message: who sent it and its body preview."""

    sender: str
    text: str


def _teams_notifiable(message: ChatMessage, my_id: str) -> TeamsNotifiable | None:
    """Sender + body preview for a Teams message, or None when it must not notify: the user's own
    message, or a system event carrying neither author nor body (member added, chat renamed, meeting
    started). Graph gives those `from: null` and an empty body, leaving nothing to report."""
    sender = message["from"] if "from" in message else None
    sender_user = sender["user"] if sender and "user" in sender else None
    if sender_user and "id" in sender_user and sender_user["id"] == my_id:
        return None
    body = message["body"] if "body" in message else None
    content = body["content"] if body and "content" in body else None
    text = clean_preview(_HTML_TAG.sub(" ", content or ""))[:200]
    name = (sender_user["displayName"] if sender_user and "displayName" in sender_user else None) or ""
    if not name and not text:
        return None
    return {"sender": name or "Someone", "text": text}


def _arrived_since(message: ChatMessage, last_dt: datetime) -> bool:
    """True when the message carries a parseable createdDateTime newer than last_dt."""
    if "createdDateTime" not in message:
        return False
    try:
        created = datetime.fromisoformat(message["createdDateTime"])
    except ValueError:
        return False
    return created > last_dt


def _poll_teams_account(ctx: MicrosoftContext, config: Config, account_email: str, last_dt: datetime, catching_up: bool) -> bool:
    """Emit a notification per chat whose latest message arrived since last_dt (excluding the user's
    own messages), True when the chats were read. One /me/chats request per cycle carries every
    chat's last-message preview."""
    logger = ctx.monitor_logger
    try:
        token = teams.resolve_token(config, account_email)
    except teams.TeamsError as e:
        logger.info("Teams token unavailable for %s: %s", account_email, e)
        return False
    try:
        my_id = teams._my_id(ctx.http_client, token)
        chats = cast("list[Chat]", teams.list_chats(ctx.http_client, token, limit=50))
    except Exception as e:
        logger.error("Error fetching Teams chats for %s: %s", account_email, e)
        return False

    for chat in chats:
        preview = chat["lastMessagePreview"] if "lastMessagePreview" in chat else None
        if not preview or not _arrived_since(preview, last_dt):
            continue
        notifiable = _teams_notifiable(preview, my_id)
        if notifiable is None:
            continue  # our own outgoing message, or a contentless system event
        member_list = chat["members"] if "members" in chat else []
        members = ", ".join(name for m in member_list if (name := m["displayName"] if "displayName" in m else None))
        topic = (chat["topic"] if "topic" in chat else None) or members or None
        logger.info("Writing Teams notification from %s in chat %s", notifiable["sender"], chat["id"])
        notifications.write_notification(
            ctx.notif_dir,
            "teams",
            interrupt=True,
            sender=notifiable["sender"],
            topic=topic,
            preview=notifiable["text"],
            chat_id=chat["id"],
            account=account_email,
            missed=catching_up or None,
        )
    return True


def _poll_teams_channels_account(ctx: MicrosoftContext, config: Config, account_email: str, last_dt: datetime, catching_up: bool) -> bool:
    """Emit a non-interrupting notification per Teams CHANNEL message since last_dt (excluding the
    user's own), True when the window was read. Channels are broadcast, so a message per channel would
    be noisy: interrupt=False, unlike chats.

    Enumerating teams needs channel-read access many accounts lack, so a failure there reports the
    window read and degrades to chats-only; parking would flood them if access ever appeared. A single
    team/channel failure is skipped, never fatal. Only a missing token reports the window unread."""
    logger = ctx.monitor_logger
    try:
        token = teams.resolve_token(config, account_email)
    except teams.TeamsError as e:
        logger.info("Teams token unavailable for %s: %s", account_email, e)
        return False
    try:
        my_id = teams._my_id(ctx.http_client, token)
        teams_list = cast("list[ChannelResource]", teams.list_teams(ctx.http_client, token))
    except Exception as e:
        # No channel access (missing ChannelMessage.Read.All / no Graph): degrade to chats-only.
        logger.info("Teams channel messages unavailable for %s, keeping chats-only: %s", account_email, e)
        return True

    for team in teams_list:
        team_id = team["id"] if "id" in team else None
        if not team_id:
            continue
        team_name = (team["displayName"] if "displayName" in team else None) or "Team"
        try:
            channels = cast("list[ChannelResource]", teams.list_channels(ctx.http_client, token, team_id=team_id))
        except Exception as e:
            logger.debug("Skipping Teams channels for team %s (%s): %s", team_name, account_email, e)
            continue
        for channel in channels:
            channel_id = channel["id"] if "id" in channel else None
            if not channel_id:
                continue
            channel_name = (channel["displayName"] if "displayName" in channel else None) or "Channel"
            try:
                messages = cast(
                    "list[ChatMessage]", teams.list_channel_messages(ctx.http_client, token, team_id=team_id, channel_id=channel_id, limit=20)
                )
            except Exception as e:
                logger.debug("Skipping Teams channel %s / %s (%s): %s", team_name, channel_name, account_email, e)
                continue
            for msg in messages:
                if not _arrived_since(msg, last_dt):
                    continue
                notifiable = _teams_notifiable(msg, my_id)
                if notifiable is None:
                    continue  # our own channel post, or a contentless system event
                logger.info("Writing Teams channel notification from %s in %s / %s", notifiable["sender"], team_name, channel_name)
                notifications.write_notification(
                    ctx.notif_dir,
                    "teams",
                    interrupt=False,
                    sender=notifiable["sender"],
                    topic=f"{team_name} / {channel_name}",
                    preview=notifiable["text"],
                    team_id=team_id,
                    channel_id=channel_id,
                    account=account_email,
                    missed=catching_up or None,
                )
    return True


def _refresh_captured_tokens(ctx: MicrosoftContext, config: Config, gave_up: set[str]) -> None:
    """Silently re-mint browser-captured tokens before they expire, so the user signs in only once.
    On a lapsed sign-in, notify once and stop retrying that account until the daemon restarts."""
    logger = ctx.monitor_logger
    for account in capture.due_accounts(config, time.time()):
        if account in gave_up:
            continue
        try:
            saved = capture.refresh_and_save(config, account)
            logger.info("Refreshed Microsoft tokens for %s: %s", account, ", ".join(saved))
        except capture.CaptureError as e:
            logger.warning("Token refresh failed for %s: %s", account, e)
            gave_up.add(account)
            notifications.write_notification(ctx.notif_dir, "auth_needed", interrupt=False, account=account, message=str(e))


def _poll_graph_mail(ctx: MicrosoftContext, acc, new_check_time: datetime, last_dt: datetime, catching_up: bool) -> datetime | None:
    """Poll one MSAL (Graph) account's watched folders for new mail, returning how far its mail was read."""
    logger = ctx.monitor_logger
    conn = graph.GraphConn(ctx.http_client, ctx.cache_file, ctx.scopes, ctx.base_url)
    watch_folders = notify.get_notify_folders(ctx.notify_file, acc.username) if ctx.notify_file else ["inbox"]
    read_through: datetime | None = new_check_time
    for folder_token in watch_folders:
        try:
            folder_id = folders.resolve_folder_id(
                ctx.http_client, ctx.cache_file, ctx.scopes, ctx.base_url, ctx.folders, acc.account_id, folder_token
            )
            emails = list(
                graph.request_paginated(
                    conn,
                    f"/me/mailFolders/{folder_id}/messages",
                    acc.account_id,
                    params={
                        "$filter": f"receivedDateTime gt {last_dt.isoformat()}",
                        "$orderby": "receivedDateTime asc",
                        "$select": "subject,from,bodyPreview,receivedDateTime",
                        "$top": _MAIL_PAGE_SIZE,
                    },
                    limit=_MAX_WINDOW_MESSAGES,
                )
            )
            logger.info("Found %d new emails for %s in %s", len(emails), acc.username, folder_token)

            for email in emails:
                _emit_email_notification(ctx, email, acc.username, folder_token, catching_up)
            read_through = _earliest(read_through, _window_read_through(emails, new_check_time))
        except Exception as e:
            logger.error("Error fetching emails for %s folder %s: %s", acc.username, folder_token, e)
            read_through = None
    return read_through


def _poll_graph_calendar(ctx: MicrosoftContext, acc, new_check_time: datetime, last_dt: datetime, catching_up: bool) -> bool:
    """Emit one MSAL (Graph) account's calendar reminders, True when the calendar was read."""
    logger = ctx.monitor_logger
    conn = graph.GraphConn(ctx.http_client, ctx.cache_file, ctx.scopes, ctx.base_url)
    try:
        max_threshold = max(ctx.get_calendar_notify_thresholds())
        window_end = new_check_time + timedelta(minutes=max_threshold + 60)
        cal_result = graph.request(
            conn,
            "GET",
            "/me/calendarView",
            acc.account_id,
            params={
                "startDateTime": last_dt.isoformat().replace("+00:00", "Z"),
                "endDateTime": window_end.isoformat().replace("+00:00", "Z"),
                "$select": "subject,start,location,id",
            },
        )

        if not cal_result or "value" not in cal_result:
            logger.warning("Unexpected calendar API response: %s", cal_result)
            return False
        events = cal_result["value"]
        logger.info("Found %d upcoming calendar events for %s", len(events), acc.username)
        _emit_calendar_reminders(ctx, events, acc.username, last_dt, new_check_time, catching_up)
    except Exception as e:
        logger.error("Error fetching calendar for %s: %s", acc.username, e)
        return False
    return True


def run(ctx: MicrosoftContext):
    logger = ctx.monitor_logger
    logger.info("Monitor thread started")
    refresh_gave_up: set[str] = set()

    while not ctx.monitor_stop_event.is_set():
        try:
            new_check_time = datetime.now(UTC)
            state = _read_state(ctx.monitor_state_file, new_check_time)
            config = Config(data_dir=ctx.cache_file.parent)

            msal_accounts = auth.list_accounts(ctx.cache_file)
            for acc in msal_accounts:
                logger.info("Checking account: %s", acc.username)
                _poll_unit(ctx, state, f"mail:{acc.username}", new_check_time, partial(_poll_graph_mail, ctx, acc, new_check_time))
                _poll_unit(
                    ctx,
                    state,
                    f"calendar:{acc.username}",
                    new_check_time,
                    _whole_window(new_check_time, partial(_poll_graph_calendar, ctx, acc, new_check_time)),
                )

            # OWA REST accounts (locked tenants) are not in the MSAL cache, so poll them separately
            # for anything Graph did not already cover.
            msal_usernames = {acc.username.casefold() for acc in msal_accounts}
            for account_email in owa_rest.list_accounts(config):
                if account_email.casefold() in msal_usernames:
                    continue
                logger.info("Checking OWA REST account: %s", account_email)
                watch_folders = notify.get_notify_folders(ctx.notify_file, account_email) if ctx.notify_file else ["inbox"]
                _poll_unit(
                    ctx,
                    state,
                    f"mail:{account_email}",
                    new_check_time,
                    partial(_poll_owa_rest_mail, ctx, config, account_email, watch_folders, new_check_time),
                )
                _poll_unit(
                    ctx,
                    state,
                    f"calendar:{account_email}",
                    new_check_time,
                    _whole_window(new_check_time, partial(_poll_owa_rest_calendar, ctx, config, account_email, new_check_time)),
                )

            # Teams chats: every account that has authorized Teams (device or captured token).
            for account_email in teams.list_accounts(config):
                logger.info("Checking Teams account: %s", account_email)
                _poll_unit(
                    ctx,
                    state,
                    f"teams:{account_email}",
                    new_check_time,
                    _whole_window(new_check_time, partial(_poll_teams_account, ctx, config, account_email)),
                )
                _poll_unit(
                    ctx,
                    state,
                    f"channels:{account_email}",
                    new_check_time,
                    _whole_window(new_check_time, partial(_poll_teams_channels_account, ctx, config, account_email)),
                )

            # Keep browser-captured tokens fresh so the user's one sign-in lasts the SSO session.
            _refresh_captured_tokens(ctx, config, refresh_gave_up)

            state["last_cycle"] = new_check_time.isoformat()
            _write_state(ctx.monitor_state_file, state)
            logger.info("Completed check cycle, sleeping for 45 seconds")
            if ctx.monitor_stop_event.wait(45):
                break
        except Exception:
            logger.exception("Error in monitor loop")
            if ctx.monitor_stop_event.wait(45):
                break

    logger.info("Monitor thread stopped")
