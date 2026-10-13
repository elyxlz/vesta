"""voice: the one command of the voice skill.

    voice status
    voice <role> check <provider> [--key <k>]
    voice <role> connect <provider> [--key <k>]
    voice <role> use <provider>
    voice <role> disconnect <provider>
    voice <role> on | off
    voice <role> set <key> <value>
    voice behavior set <key> <value>
    voice tts voice <id>
    voice tts voices add <id> --name <n> [--description <d>] | remove <id>
    voice stt keyterms add <term> | remove <term>
    voice daemon start|stop|restart|status
    voice serve

<role> is stt, tts, or judge. Each command prints one line of JSON on stdout. A command that
fails prints one line of JSON on stderr and exits non-zero.
"""

import argparse
import asyncio
import json
import pathlib as pl
import sys
import typing as tp

from . import config as vc
from . import daemon, invalidation, providers, sections, server
from .settings import JsonValue

USAGE_EXIT = 2


class CommandError(Exception):
    """A command that cannot do its job. Its message is the `error` of the one JSON line."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> tp.NoReturn:
        print(json.dumps({"error": f"{message}; run `{self.prog} --help`"}), file=sys.stderr)
        raise SystemExit(USAGE_EXIT)


def _data_dir() -> pl.Path:
    return vc.data_dir()


def _role_view(config: vc.VoiceConfig, role: vc.Role) -> dict[str, JsonValue]:
    """One role as `voice status` shows it. A key is never printed."""
    entry = config[role] or {}
    view: dict[str, JsonValue] = {
        "providers": providers.names(role),
        "connected": vc.connected(entry),
        "selected": vc.provider_name(entry),
        "on": vc.is_enabled(entry),
        "settings": {s["key"]: s["value"] for s in sections.section_view(config, role)},
    }
    if role == "stt":
        view["keyterms"] = vc.keyterms(entry)
    if role == "tts":
        view["voices"] = [dict(voice) for voice in vc.custom_voices(entry)]
    return view


def status_view(config: vc.VoiceConfig) -> dict[str, JsonValue]:
    view: dict[str, JsonValue] = {role: _role_view(config, role) for role in vc.ROLES}
    view["behavior"] = {s["key"]: s["value"] for s in sections.section_view(config, "behavior")}
    return view


def _print_status(scope: vc.Section | None = None) -> int:
    """The answer of every command that reads or changes the config: the whole status, one line."""
    print(json.dumps(status_view(vc.load(_data_dir()))))
    if scope is not None:
        asyncio.run(invalidation.notify(scope))
    return 0


def _provider_creds(
    role: vc.Role, name: str, key: str | None
) -> tuple[providers.SttProvider | providers.TtsProvider | providers.Judge, dict[str, str]]:
    provider = providers.get(role, name)
    if provider is None:
        raise CommandError(f"unknown {role} provider: {name} (providers: {', '.join(providers.names(role))})")
    if provider.needs_key and not key:
        raise CommandError(f"{name} needs a key: add --key <key>")
    if not provider.needs_key and key:
        raise CommandError(f"{name} takes no key: run the command with no --key")
    return provider, ({"api_key": key} if key else {})


def _check(role: vc.Role, name: str, key: str | None) -> dict[str, str]:
    """Check that the provider can do the role. Returns its credentials entry."""
    provider, creds = _provider_creds(role, name, key)
    settings = vc.provider_settings(vc.load(_data_dir())[role] or {})
    ok, error = asyncio.run(provider.validate(creds, settings))
    if not ok:
        raise CommandError(f"{name} failed the {role} check: {error}")
    return creds


def cmd_status(_args: argparse.Namespace) -> int:
    return _print_status()


def cmd_check(args: argparse.Namespace) -> int:
    _check(args.role, args.provider, args.key)
    print(json.dumps({"role": args.role, "provider": args.provider, "ok": True}))
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    vc.connect(_data_dir(), args.role, args.provider, _check(args.role, args.provider, args.key))
    return _print_status(args.role)


def cmd_use(args: argparse.Namespace) -> int:
    vc.use(_data_dir(), args.role, args.provider)
    return _print_status(args.role)


def cmd_disconnect(args: argparse.Namespace) -> int:
    vc.disconnect(_data_dir(), args.role, args.provider)
    return _print_status(args.role)


def cmd_on(args: argparse.Namespace) -> int:
    vc.set_enabled(_data_dir(), args.role, True)
    return _print_status(args.role)


def cmd_off(args: argparse.Namespace) -> int:
    vc.set_enabled(_data_dir(), args.role, False)
    return _print_status(args.role)


def cmd_set(args: argparse.Namespace) -> int:
    sections.store_setting(_data_dir(), args.role, args.key, args.value)
    return _print_status(args.role)


def cmd_voice(args: argparse.Namespace) -> int:
    sections.store_voice(_data_dir(), args.id)
    return _print_status("tts")


def cmd_voices_add(args: argparse.Namespace) -> int:
    vc.add_custom_voice(_data_dir(), args.id, args.name, args.description)
    return _print_status("tts")


def cmd_voices_remove(args: argparse.Namespace) -> int:
    vc.remove_custom_voice(_data_dir(), args.id)
    return _print_status("tts")


def cmd_keyterms_add(args: argparse.Namespace) -> int:
    vc.add_keyterm(_data_dir(), args.term)
    return _print_status("stt")


def cmd_keyterms_remove(args: argparse.Namespace) -> int:
    vc.remove_keyterm(_data_dir(), args.term)
    return _print_status("stt")


def cmd_daemon(args: argparse.Namespace) -> int:
    return daemon.daemon_cmd(args.action)


def cmd_serve(_args: argparse.Namespace) -> int:
    server.main()
    return 0


def _add_role(sub: "argparse._SubParsersAction[_Parser]", role: vc.Role) -> "argparse._SubParsersAction[_Parser]":
    parser = sub.add_parser(role, help=f"the {role} role: check, connect, use, disconnect, on, off, set")
    verbs = parser.add_subparsers(dest="verb", required=True)
    for verb, func in (("check", cmd_check), ("connect", cmd_connect)):
        p = verbs.add_parser(verb)
        p.add_argument("provider")
        p.add_argument("--key", default=None)
        p.set_defaults(func=func, role=role)
    for verb, func in (("use", cmd_use), ("disconnect", cmd_disconnect)):
        p = verbs.add_parser(verb)
        p.add_argument("provider")
        p.set_defaults(func=func, role=role)
    verbs.add_parser("on").set_defaults(func=cmd_on, role=role)
    verbs.add_parser("off").set_defaults(func=cmd_off, role=role)
    _add_set(verbs, role)
    return verbs


def _add_set(verbs: "argparse._SubParsersAction[_Parser]", section: vc.Section) -> None:
    p = verbs.add_parser("set")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(func=cmd_set, role=section)


def _build_parser() -> _Parser:
    parser = _Parser(prog="voice", description="The voice skill: providers, settings, and the voice daemon.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="each role and each behavior").set_defaults(func=cmd_status)

    stt = _add_role(sub, "stt")
    keyterms = stt.add_parser("keyterms").add_subparsers(dest="action", required=True)
    for action, func in (("add", cmd_keyterms_add), ("remove", cmd_keyterms_remove)):
        p = keyterms.add_parser(action)
        p.add_argument("term")
        p.set_defaults(func=func)

    tts = _add_role(sub, "tts")
    voice = tts.add_parser("voice")
    voice.add_argument("id")
    voice.set_defaults(func=cmd_voice)
    voices = tts.add_parser("voices").add_subparsers(dest="action", required=True)
    add = voices.add_parser("add")
    add.add_argument("id")
    add.add_argument("--name", required=True)
    add.add_argument("--description", default="")
    add.set_defaults(func=cmd_voices_add)
    remove = voices.add_parser("remove")
    remove.add_argument("id")
    remove.set_defaults(func=cmd_voices_remove)

    _add_role(sub, "judge")

    behavior_verbs = sub.add_parser("behavior", help="values that change how a session acts").add_subparsers(dest="verb", required=True)
    _add_set(behavior_verbs, "behavior")

    p_daemon = sub.add_parser("daemon", help="manage the voice daemon: start|stop|restart|status")
    p_daemon.add_argument("action", nargs="?", default="", metavar="start|stop|restart|status")
    p_daemon.set_defaults(func=cmd_daemon)
    sub.add_parser("serve", help="run the voice service in the foreground; the daemon starts it").set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    if not args_in or args_in[0] == "help":
        parser.print_help()
        return 0
    args = parser.parse_args(args_in)
    try:
        duplicates = providers.duplicate_names()
        if duplicates:
            raise CommandError(f"a provider name is used two times in providers/own.py ({'; '.join(duplicates)}); give it a new name")
        return args.func(args)
    except (CommandError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
