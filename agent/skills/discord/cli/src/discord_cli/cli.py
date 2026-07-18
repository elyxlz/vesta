"""Discord channel CLI: a gateway daemon that writes notification files, plus one-shot REST commands."""

import argparse
import asyncio
import logging
import pathlib

import aiohttp
import discord
import pydantic as pyd

from discord_cli.notif import MessageFacts, build_notification, daemon_died_notification, write_notification

CREDENTIALS_PATH = pathlib.Path.home() / ".discord" / "credentials.json"
API_BASE = "https://discord.com/api/v10"
# View Channels (1024) + Send Messages (2048) + Read Message History (65536).
INVITE_PERMISSIONS = 68608
TEXT_CHANNEL_TYPES = (0, 5)

logger = logging.getLogger("discord-cli")


class Credentials(pyd.BaseModel):
    bot_token: str


class DiscordUser(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    username: str
    global_name: str | None = None


class DiscordGuild(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    name: str


class DiscordChannel(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    type: int
    name: str | None = None


class DiscordMessage(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    content: str
    timestamp: str
    author: DiscordUser


class DiscordApplication(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="ignore")

    id: str
    name: str


GUILD_LIST = pyd.TypeAdapter(list[DiscordGuild])
CHANNEL_LIST = pyd.TypeAdapter(list[DiscordChannel])
MESSAGE_LIST = pyd.TypeAdapter(list[DiscordMessage])


def load_credentials() -> Credentials:
    if not CREDENTIALS_PATH.exists():
        raise SystemExit(f"no credentials at {CREDENTIALS_PATH}; run: discord authenticate --token <bot token>")
    return Credentials.model_validate_json(CREDENTIALS_PATH.read_text())


async def api_request(token: str, method: str, path: str, body: pyd.JsonValue | None = None) -> pyd.JsonValue:
    async with (
        aiohttp.ClientSession(headers={"Authorization": f"Bot {token}"}) as session,
        session.request(method, f"{API_BASE}{path}", json=body) as response,
    ):
        if response.status >= 400:
            detail = await response.text()
            raise SystemExit(f"discord api error {response.status}: {detail}")
        return await response.json()


def extract_facts(message: discord.Message, *, self_id: int) -> MessageFacts:
    guild = message.guild
    channel = message.channel
    channel_name = f"#{channel.name}" if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)) else None
    return MessageFacts(
        content=message.clean_content,
        author_name=message.author.display_name,
        author_id=str(message.author.id),
        author_is_self=message.author.id == self_id,
        author_is_bot=message.author.bot,
        channel_id=str(channel.id),
        channel_name=channel_name,
        server=guild.name if guild is not None else None,
        is_dm=guild is None,
        mentions_me=any(user.id == self_id for user in message.mentions),
        message_id=str(message.id),
        timestamp=message.created_at,
    )


async def cmd_authenticate(token: str) -> None:
    me = DiscordUser.model_validate(await api_request(token, "GET", "/users/@me"))
    application = DiscordApplication.model_validate(await api_request(token, "GET", "/oauth2/applications/@me"))
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(Credentials(bot_token=token).model_dump_json(indent=2) + "\n")
    CREDENTIALS_PATH.chmod(0o600)
    print(f"authenticated as {me.username}")
    print(f"invite url: https://discord.com/oauth2/authorize?client_id={application.id}&scope=bot&permissions={INVITE_PERMISSIONS}")


def cmd_serve(notifications_dir: pathlib.Path) -> None:
    token = load_credentials().bot_token
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        logger.info("connected as %s", client.user)

    @client.event
    async def on_message(message: discord.Message) -> None:
        user = client.user
        if user is None:
            return
        notif = build_notification(extract_facts(message, self_id=user.id))
        if notif is not None:
            path = await asyncio.to_thread(write_notification, notifications_dir, notif)
            logger.info("wrote %s", path.name)

    try:
        client.run(token)
    finally:
        # client.run returns on SIGTERM/SIGINT and re-raises on a fatal gateway error;
        # either way the daemon is gone, so tell the agent to restart it. An intentional
        # screen quit sends SIGHUP, which terminates before this runs, so no false alarm.
        write_notification(notifications_dir, daemon_died_notification())


async def cmd_send(token: str, target: str, message: str, reply: str | None) -> None:
    channel_id = target
    if target.startswith("@"):
        dm = DiscordChannel.model_validate(await api_request(token, "POST", "/users/@me/channels", {"recipient_id": target[1:]}))
        channel_id = dm.id
    body: dict[str, pyd.JsonValue] = {"content": message}
    if reply is not None:
        body["message_reference"] = {"message_id": reply}
    sent = DiscordMessage.model_validate(await api_request(token, "POST", f"/channels/{channel_id}/messages", body))
    print(f"sent {sent.id} to {channel_id}")


async def cmd_channels(token: str) -> None:
    for guild in GUILD_LIST.validate_python(await api_request(token, "GET", "/users/@me/guilds")):
        for channel in CHANNEL_LIST.validate_python(await api_request(token, "GET", f"/guilds/{guild.id}/channels")):
            if channel.type in TEXT_CHANNEL_TYPES:
                print(f"{channel.id}\t{guild.name} #{channel.name}")


async def cmd_history(token: str, channel_id: str, limit: int) -> None:
    messages = MESSAGE_LIST.validate_python(await api_request(token, "GET", f"/channels/{channel_id}/messages?limit={limit}"))
    for message in reversed(messages):
        when = message.timestamp[:16].replace("T", " ")
        name = message.author.global_name or message.author.username
        print(f"[{when}] {name}: {message.content} (id {message.id})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="discord", description="Discord channel for Vesta")
    sub = parser.add_subparsers(dest="command", required=True)

    authenticate = sub.add_parser("authenticate", help="validate and store the bot token, print the invite url")
    authenticate.add_argument("--token", required=True)

    serve = sub.add_parser("serve", help="run the gateway daemon that writes notifications")
    serve.add_argument("--notifications-dir", required=True, type=pathlib.Path)

    send = sub.add_parser("send", help="post a message")
    send.add_argument("target", help="a channel id, or @<user id> to DM that user")
    send.add_argument("message")
    send.add_argument("--reply", help="message id to reference-reply to")

    sub.add_parser("channels", help="list servers and their text channels")

    history = sub.add_parser("history", help="print recent messages, oldest first")
    history.add_argument("channel_id")
    history.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "authenticate":
        asyncio.run(cmd_authenticate(args.token))
    elif args.command == "serve":
        cmd_serve(args.notifications_dir)
    else:
        token = load_credentials().bot_token
        if args.command == "send":
            asyncio.run(cmd_send(token, args.target, args.message, args.reply))
        elif args.command == "channels":
            asyncio.run(cmd_channels(token))
        elif args.command == "history":
            asyncio.run(cmd_history(token, args.channel_id, args.limit))


if __name__ == "__main__":
    main()
