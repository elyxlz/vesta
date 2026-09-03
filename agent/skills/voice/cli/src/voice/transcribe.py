"""transcribe <file> [--language <code>]: one transcript on stdout, whichever backend answered.

The configured STT provider goes first. When STT is unset, disabled, or the provider fails,
the whisper skill's local whisper.cpp script transcribes instead. Only when both fail does the
command print {"error": ...} on stderr and exit non-zero, so any skill can shell it and read
stdout as the transcript.
"""

import argparse
import asyncio
import json
import pathlib as pl
import re
import subprocess
import sys

from . import config as vc
from . import providers

WHISPER_SCRIPT = pl.Path(__file__).resolve().parents[4] / "whisper" / "scripts" / "whisper_transcribe.sh"

# whisper.cpp prints a bracketed tag ("[BLANK_AUDIO]", "[Musica]") instead of text for a
# near-silent clip; output that is nothing but such tags is silence, not a transcript.
_TAG = re.compile(r"\[[^\[\]]+\]")


def _is_silence(text: str) -> bool:
    return not _TAG.sub("", text).strip()


async def _provider_transcript(path: pl.Path, language: str | None) -> str:
    """The configured STT provider's transcript. Raises on any config or provider fault."""
    entry = vc.load(vc.data_dir())["stt"]
    name = vc.provider_name(entry)
    if not entry or name is None:
        raise RuntimeError("STT not configured")
    if not vc.is_enabled(entry):
        raise RuntimeError("STT disabled")
    provider = providers.get_stt(name)
    if provider is None:
        raise RuntimeError(f"unknown STT provider: {name}")
    creds = vc.provider_creds(entry, name)
    if not creds:
        raise RuntimeError(f"no credentials for STT provider: {name}")
    return await provider.transcribe_file(path, creds, language)


def _whisper_transcript(path: pl.Path, language: str | None) -> str:
    """The whisper skill's local transcript. Raises when whisper.cpp cannot run."""
    if not WHISPER_SCRIPT.is_file():
        raise RuntimeError(f"whisper skill script missing: {WHISPER_SCRIPT}")
    args = [str(WHISPER_SCRIPT), str(path)]
    if language:
        args += ["--language", language]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = " ".join(result.stderr.split()) or f"exited {result.returncode}"
        raise RuntimeError(detail)
    text = result.stdout.strip()
    return "" if _is_silence(text) else text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description="Transcribe one audio or video file: the configured STT provider first, local whisper.cpp when it cannot answer.",
    )
    parser.add_argument("file", type=pl.Path)
    parser.add_argument("--language", default=None, help="language code such as en or it; detected when omitted")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.file.is_file():
        print(json.dumps({"error": f"file not found: {args.file}"}), file=sys.stderr)
        return 1
    try:
        transcript = asyncio.run(_provider_transcript(args.file, args.language))
    except Exception as provider_error:
        try:
            transcript = _whisper_transcript(args.file, args.language)
        except RuntimeError as whisper_error:
            print(json.dumps({"error": f"{provider_error}; whisper: {whisper_error}"}), file=sys.stderr)
            return 1
    print(transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
