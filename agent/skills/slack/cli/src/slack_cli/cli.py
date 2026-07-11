"""Slack channel CLI: a Socket Mode daemon that writes notification files, plus one-shot Web API commands."""

import argparse
import datetime as dt
import logging
import pathlib
import threading
import typing as tp

import pydantic as pyd
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import SlackResponse

from slack_cli.notif import ResolveName, SlackMessageEvent, build_notification, humanize_mentions, write_notification

CREDENTIALS_PATH = pathlib.Path.home() / ".slack" / "credentials.json"
PAGE_LIMIT = 200

logger = logging.getLogger("slack")


class Credentials(pyd.BaseModel):
    bot_token: str
    app_token: str


class SlackProfile(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    display_name: str = ""
    real_name: str = ""


class SlackUser(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    name: str = ""
    deleted: bool = False
    is_bot: bool = False
    profile: SlackProfile = pyd.Field(default_factory=SlackProfile)


class SlackChannel(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    name: str = ""
    is_member: bool = False


class SlackHistoryMessage(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    ts: str
    text: str = ""
    user: str | None = None
    reply_count: int | None = None


def display_name(user: SlackUser) -> str:
    return user.profile.display_name or user.profile.real_name or user.name


def load_credentials() -> Credentials:
    if not CREDENTIALS_PATH.exists():
        raise SystemExit(f"no credentials at {CREDENTIALS_PATH}; run: slack authenticate --bot-token xoxb... --app-token xapp...")
    return Credentials.model_validate_json(CREDENTIALS_PATH.read_text())


def paginate[ModelT: pyd.BaseModel](
    method: tp.Callable[..., SlackResponse], key: str, model: type[ModelT], **kwargs: str | bool | int
) -> tp.Iterator[ModelT]:
    cursor = ""
    while True:
        response = method(cursor=cursor, **kwargs) if cursor else method(**kwargs)
        for item in response[key]:
            yield model.model_validate(item)
        metadata = response.data["response_metadata"] if "response_metadata" in response.data else {}
        cursor = metadata["next_cursor"] if "next_cursor" in metadata else ""
        if not cursor:
            return


def make_user_resolver(web: WebClient) -> ResolveName:
    cache: dict[str, str] = {}

    def resolve(user_id: str) -> str:
        if user_id not in cache:
            try:
                user = SlackUser.model_validate(web.users_info(user=user_id)["user"])
            except SlackApiError as err:
                logger.warning("users_info %s failed: %s", user_id, err.response["error"])
                return user_id
            cache[user_id] = display_name(user)
        return cache[user_id]

    return resolve


def make_channel_resolver(web: WebClient) -> ResolveName:
    cache: dict[str, str] = {}

    def resolve(channel_id: str) -> str:
        if channel_id not in cache:
            try:
                channel = SlackChannel.model_validate(web.conversations_info(channel=channel_id)["channel"])
            except SlackApiError as err:
                logger.warning("conversations_info %s failed: %s", channel_id, err.response["error"])
                return channel_id
            cache[channel_id] = channel.name or channel_id
        return cache[channel_id]

    return resolve


def open_dm(web: WebClient, user_id: str) -> str:
    return SlackChannel.model_validate(web.conversations_open(users=user_id)["channel"]).id


def resolve_target(web: WebClient, target: str) -> str:
    """Turns `#name`, `@user`, or a raw id into a conversation id (opening the DM for user targets)."""
    if target.startswith("#"):
        name = target[1:]
        for channel in paginate(web.conversations_list, "channels", SlackChannel, types="public_channel,private_channel", limit=PAGE_LIMIT):
            if channel.name == name:
                return channel.id
        raise SystemExit(f"channel {target} not found; run: slack channels")
    if target.startswith("@"):
        name = target[1:].lower()
        for user in paginate(web.users_list, "members", SlackUser, limit=PAGE_LIMIT):
            if name in {user.name.lower(), user.profile.display_name.lower(), user.profile.real_name.lower()}:
                return open_dm(web, user.id)
        raise SystemExit(f"user {target} not found; run: slack users")
    if target.startswith(("U", "W")):
        return open_dm(web, target)
    return target


def cmd_authenticate(bot_token: str, app_token: str) -> None:
    auth = WebClient(token=bot_token).auth_test()
    WebClient(token=app_token).apps_connections_open()
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(Credentials(bot_token=bot_token, app_token=app_token).model_dump_json(indent=2) + "\n")
    CREDENTIALS_PATH.chmod(0o600)
    print(f"authenticated to {auth['team']} as {auth['user']} ({auth['user_id']})")


def cmd_serve(notifications_dir: pathlib.Path) -> None:
    credentials = load_credentials()
    web = WebClient(token=credentials.bot_token)
    bot_user_id: str = web.auth_test()["user_id"]
    resolve_user = make_user_resolver(web)
    resolve_channel = make_channel_resolver(web)
    client = SocketModeClient(app_token=credentials.app_token, web_client=web)

    def handle(sm_client: SocketModeClient, request: SocketModeRequest) -> None:
        sm_client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
        if request.type != "events_api" or "event" not in request.payload:
            return
        raw_event = request.payload["event"]
        if raw_event["type"] != "message":
            return
        event = SlackMessageEvent.model_validate(raw_event)
        notif = build_notification(event, bot_user_id=bot_user_id, resolve_user=resolve_user, resolve_channel=resolve_channel)
        if notif is not None:
            path = write_notification(notifications_dir, notif)
            logger.info("wrote %s", path.name)

    client.socket_mode_request_listeners.append(handle)
    client.connect()
    logger.info("connected as %s", bot_user_id)
    threading.Event().wait()


def cmd_send(web: WebClient, target: str, message: str, thread: str | None) -> None:
    response = web.chat_postMessage(channel=resolve_target(web, target), text=message, thread_ts=thread)
    print(f"sent {response['ts']} to {response['channel']}")


def cmd_channels(web: WebClient) -> None:
    for channel in paginate(
        web.conversations_list, "channels", SlackChannel, types="public_channel,private_channel", exclude_archived=True, limit=PAGE_LIMIT
    ):
        member = "member" if channel.is_member else "not a member"
        print(f"{channel.id}\t#{channel.name}\t{member}")


def cmd_users(web: WebClient) -> None:
    for user in paginate(web.users_list, "members", SlackUser, limit=PAGE_LIMIT):
        if user.deleted or user.is_bot or user.id == "USLACKBOT":
            continue
        print(f"{user.id}\t{display_name(user)}\t@{user.name}")


def cmd_history(web: WebClient, target: str, limit: int, thread: str | None) -> None:
    channel_id = resolve_target(web, target)
    if thread:
        response = web.conversations_replies(channel=channel_id, ts=thread, limit=limit)
    else:
        response = web.conversations_history(channel=channel_id, limit=limit)
    resolve_user = make_user_resolver(web)
    for message in reversed([SlackHistoryMessage.model_validate(item) for item in response["messages"]]):
        sender = resolve_user(message.user) if message.user is not None else "app"
        when = dt.datetime.fromtimestamp(float(message.ts), tz=dt.UTC).strftime("%Y-%m-%d %H:%M")
        thread_marker = f" [thread of {message.reply_count}, ts {message.ts}]" if message.reply_count else ""
        print(f"[{when}] {sender}: {humanize_mentions(message.text, resolve_user)}{thread_marker}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="slack", description="Slack channel for Vesta")
    sub = parser.add_subparsers(dest="command", required=True)

    authenticate = sub.add_parser("authenticate", help="validate and store the two app tokens")
    authenticate.add_argument("--bot-token", required=True, help="bot user OAuth token (xoxb...)")
    authenticate.add_argument("--app-token", required=True, help="app-level token with connections:write (xapp...)")

    serve = sub.add_parser("serve", help="run the Socket Mode daemon that writes notifications")
    serve.add_argument("--notifications-dir", required=True, type=pathlib.Path)

    send = sub.add_parser("send", help="post a message")
    send.add_argument("target", help="#channel, @user, or a raw id (C.../D.../U...)")
    send.add_argument("message")
    send.add_argument("--thread", help="parent message ts to reply in its thread")

    sub.add_parser("channels", help="list channels and membership")
    sub.add_parser("users", help="list workspace members")

    history = sub.add_parser("history", help="print recent messages, oldest first")
    history.add_argument("target")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--thread", help="parent message ts to read that thread")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "authenticate":
            cmd_authenticate(args.bot_token, args.app_token)
        elif args.command == "serve":
            cmd_serve(args.notifications_dir)
        else:
            web = WebClient(token=load_credentials().bot_token)
            if args.command == "send":
                cmd_send(web, args.target, args.message, args.thread)
            elif args.command == "channels":
                cmd_channels(web)
            elif args.command == "users":
                cmd_users(web)
            elif args.command == "history":
                cmd_history(web, args.target, args.limit, args.thread)
    except SlackApiError as err:
        raise SystemExit(f"slack api error: {err.response['error']}") from err


if __name__ == "__main__":
    main()
