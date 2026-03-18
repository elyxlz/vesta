import argparse
import json
import sys
from pathlib import Path

from .config import Config
from . import meetings


def build_config(args) -> Config:
    config = Config()
    if "state_dir" in vars(args) and args.state_dir:
        base = Path(args.state_dir)
        config.data_dir = base / "data" / "zoom"
    return config


def _setup(config: Config):
    config.data_dir.mkdir(parents=True, exist_ok=True)
    account_id = input("Account ID: ").strip()
    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()

    creds = {
        "account_id": account_id,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    config.credentials_file.write_text(json.dumps(creds, indent=2))
    return {"status": "credentials saved", "path": str(config.credentials_file)}


def main():
    parser = argparse.ArgumentParser(prog="zoom")
    parser.add_argument("--state-dir", type=str)
    group = parser.add_subparsers(dest="group", required=True)

    # setup
    group.add_parser("setup")

    # meeting
    meeting_parser = group.add_parser("meeting")
    meeting_sub = meeting_parser.add_subparsers(dest="command", required=True)

    p_create = meeting_sub.add_parser("create")
    p_create.add_argument("--topic", required=True)
    p_create.add_argument("--duration", type=int, required=True)
    p_create.add_argument("--start-time", default=None)
    p_create.add_argument("--timezone", default=None)

    meeting_sub.add_parser("list")

    p_delete = meeting_sub.add_parser("delete")
    p_delete.add_argument("--id", required=True, dest="meeting_id")

    args = parser.parse_args()
    config = build_config(args)
    config.data_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.group == "setup":
            result = _setup(config)
        elif args.group == "meeting":
            result = _dispatch_meeting(args, config)
        else:
            parser.print_help()
            return
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _dispatch_meeting(args, config):
    if args.command == "create":
        return meetings.create_meeting(
            config,
            topic=args.topic,
            duration=args.duration,
            start_time=args.start_time,
            timezone=args.timezone,
        )
    elif args.command == "list":
        return meetings.list_meetings(config)
    elif args.command == "delete":
        return meetings.delete_meeting(config, meeting_id=args.meeting_id)
