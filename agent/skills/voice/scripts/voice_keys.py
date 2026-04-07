#!/usr/bin/env python3
"""voice_keys.py — manage ~/.voice/voice_config.json.

Commands:
  status
  validate --provider {deepgram|elevenlabs} --key <k>
  set-key  --domain {stt|tts} --provider <p> --key <k>
  clear    --domain {stt|tts}
  enable   --domain {stt|tts}
  disable  --domain {stt|tts}
  set-voice --id <voice_id>
  add-voice --id <voice_id> --name <name>
  remove-voice --id <voice_id>
  add-keyterm <term>
  remove-keyterm <term>
  set-eot (--threshold <f> | --timeout-ms <n>)
"""

import argparse
import asyncio
import json
import pathlib as pl
import sys

# Add the skill dir to sys.path so config.py + providers/ are importable
# as top-level modules.
_SKILL_DIR = pl.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SKILL_DIR))

import config as vc  # noqa: E402
import providers  # noqa: E402


def _data_dir() -> pl.Path:
    return pl.Path.home() / ".voice"


def _print(config: vc.VoiceConfig) -> None:
    print(json.dumps(config, indent=2))


def cmd_status(_args: argparse.Namespace) -> int:
    _print(vc.load(_data_dir()))
    return 0


async def _validate(provider_name: str, api_key: str) -> tuple[bool, str | None]:
    if provider_name in ("deepgram",):
        p = providers.get_stt(provider_name)
    else:
        p = providers.get_tts(provider_name)
    if p is None:
        return False, f"unknown provider: {provider_name}"
    return await p.validate(api_key)


def cmd_validate(args: argparse.Namespace) -> int:
    ok, err = asyncio.run(_validate(args.provider, args.key))
    if ok:
        print(f"{args.provider}: OK")
        return 0
    print(f"{args.provider}: INVALID ({err})", file=sys.stderr)
    return 1


def cmd_set_key(args: argparse.Namespace) -> int:
    ok, err = asyncio.run(_validate(args.provider, args.key))
    if not ok:
        print(f"refusing to save; validation failed: {err}", file=sys.stderr)
        return 1
    cfg = vc.set_key(_data_dir(), args.domain, args.provider, args.key)
    _print(cfg)
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    cfg = vc.clear_domain(_data_dir(), args.domain)
    _print(cfg)
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    cfg = vc.set_enabled(_data_dir(), args.domain, True)
    _print(cfg)
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    cfg = vc.set_enabled(_data_dir(), args.domain, False)
    _print(cfg)
    return 0


def cmd_set_voice(args: argparse.Namespace) -> int:
    try:
        cfg = vc.set_voice(_data_dir(), args.id)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print(cfg)
    return 0


async def _fetch_voice_description(voice_id: str) -> str:
    """Fetch voice description from ElevenLabs API."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return ""
                body = await resp.json()
                labels = body.get("labels") or {}
                desc = labels.get("description", "")
                accent = labels.get("accent", "")
                gender = labels.get("gender", "")
                parts = [p for p in [desc, accent, gender] if p]
                return ", ".join(parts)
    except Exception:
        return ""


def cmd_add_voice(args: argparse.Namespace) -> int:
    description = args.description or ""
    if not description:
        description = asyncio.run(_fetch_voice_description(args.id))
    try:
        cfg = vc.add_custom_voice(_data_dir(), args.id, args.name, description)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print(cfg)
    return 0


def cmd_remove_voice(args: argparse.Namespace) -> int:
    cfg = vc.remove_custom_voice(_data_dir(), args.id)
    _print(cfg)
    return 0


def cmd_add_keyterm(args: argparse.Namespace) -> int:
    try:
        cfg = vc.add_keyterm(_data_dir(), args.term)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print(cfg)
    return 0


def cmd_remove_keyterm(args: argparse.Namespace) -> int:
    cfg = vc.remove_keyterm(_data_dir(), args.term)
    _print(cfg)
    return 0


def cmd_set_eot(args: argparse.Namespace) -> int:
    try:
        if args.threshold is not None:
            cfg = vc.set_eot_threshold(_data_dir(), args.threshold)
        elif args.timeout_ms is not None:
            cfg = vc.set_eot_timeout_ms(_data_dir(), args.timeout_ms)
        else:
            print("specify --threshold or --timeout-ms", file=sys.stderr)
            return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print(cfg)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--provider", required=True)
    p_validate.add_argument("--key", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_set_key = sub.add_parser("set-key")
    p_set_key.add_argument("--domain", required=True, choices=["stt", "tts"])
    p_set_key.add_argument("--provider", required=True)
    p_set_key.add_argument("--key", required=True)
    p_set_key.set_defaults(func=cmd_set_key)

    p_clear = sub.add_parser("clear")
    p_clear.add_argument("--domain", required=True, choices=["stt", "tts"])
    p_clear.set_defaults(func=cmd_clear)

    p_enable = sub.add_parser("enable")
    p_enable.add_argument("--domain", required=True, choices=["stt", "tts"])
    p_enable.set_defaults(func=cmd_enable)

    p_disable = sub.add_parser("disable")
    p_disable.add_argument("--domain", required=True, choices=["stt", "tts"])
    p_disable.set_defaults(func=cmd_disable)

    p_set_voice = sub.add_parser("set-voice")
    p_set_voice.add_argument("--id", required=True)
    p_set_voice.set_defaults(func=cmd_set_voice)

    p_add_voice = sub.add_parser("add-voice")
    p_add_voice.add_argument("--id", required=True)
    p_add_voice.add_argument("--name", required=True)
    p_add_voice.add_argument("--description", default="")
    p_add_voice.set_defaults(func=cmd_add_voice)

    p_remove_voice = sub.add_parser("remove-voice")
    p_remove_voice.add_argument("--id", required=True)
    p_remove_voice.set_defaults(func=cmd_remove_voice)

    p_add_keyterm = sub.add_parser("add-keyterm")
    p_add_keyterm.add_argument("term")
    p_add_keyterm.set_defaults(func=cmd_add_keyterm)

    p_remove_keyterm = sub.add_parser("remove-keyterm")
    p_remove_keyterm.add_argument("term")
    p_remove_keyterm.set_defaults(func=cmd_remove_keyterm)

    p_set_eot = sub.add_parser("set-eot")
    p_set_eot.add_argument("--threshold", type=float, default=None)
    p_set_eot.add_argument("--timeout-ms", type=int, default=None)
    p_set_eot.set_defaults(func=cmd_set_eot)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
