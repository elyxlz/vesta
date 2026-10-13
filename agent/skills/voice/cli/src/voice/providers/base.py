"""Provider interfaces for the three roles: speech to text, text to speech, and the judge.

The engine sees only these types. A provider owns everything behind them: its vendor, its model,
its wire format, and its timeouts.
"""

from __future__ import annotations

import pathlib as pl
import typing as tp

import aiohttp

from voice.settings import Domain, JsonValue, SettingDef

# (valid, error message). `voice <role> check` and `connect` print the message.
Validation = tuple[bool, str | None]


def api_key(creds: dict[str, str]) -> str:
    """The key of a provider that needs one. `creds` is empty for a provider that needs none."""
    return creds["api_key"] if "api_key" in creds else ""


class SttEvent(tp.TypedDict):
    # transcription: the live text of the open segment.
    # committed: the final text of the segment, sent when the turn is over.
    # closed: the provider connection is gone. It is the last event, and its text is "".
    kind: tp.Literal["transcription", "committed", "closed"]
    text: str


class SttOpenError(Exception):
    """The provider refused the realtime connection. `limit` means the provider's own limit on
    sessions at the same time, and `failed` is every other refusal."""

    def __init__(self, reason: tp.Literal["failed", "limit"], message: str) -> None:
        super().__init__(message)
        self.reason: tp.Literal["failed", "limit"] = reason


class SttStream(tp.Protocol):
    async def send(self, pcm: bytes) -> None:
        """Mic audio: pcm_s16le, 16 kHz, mono."""
        ...

    async def commit(self) -> None:
        """End the open segment now. Its `committed` event follows."""
        ...

    async def close(self) -> None: ...

    def events(self) -> tp.AsyncIterator[SttEvent]: ...


class SttProvider(tp.Protocol):
    needs_key: bool

    async def open(self, creds: dict[str, str], settings: Domain) -> SttStream:
        """Open one realtime connection. The provider decides the end of each turn: it sends
        `committed` when the turn is over. Raises SttOpenError when the provider refuses."""
        ...

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation:
        """Check that this provider can do the role: the key works, or the local service answers."""
        ...

    async def transcribe_file(self, audio_path: pl.Path, creds: dict[str, str], language: str | None) -> str:
        """One-shot transcription of an audio file, detecting the language when none is given.
        Returns the trimmed transcript, empty when nothing was said."""
        ...

    async def usage(self, creds: dict[str, str]) -> dict[str, JsonValue]:
        """Usage summary for the account, or an empty object for a provider with no account."""
        ...

    async def balance(self, creds: dict[str, str]) -> dict[str, JsonValue]:
        """Remaining balance for the account, or an empty object for a provider with no account."""
        ...

    def settings_schema(self) -> list[SettingDef]: ...


class TtsError(Exception):
    """The provider refused one synthesis, or the connection failed."""


class TtsProvider(tp.Protocol):
    needs_key: bool
    # The key of this provider's voice setting, so each provider keeps its own voice.
    voice_setting: str
    # The play formats (engine/frames.py PLAY_FORMATS) that this provider can make.
    formats: frozenset[str]
    # What the agent must know to write text for this voice, as one clause of a reply hint.
    # Empty for a voice that says each character of the text.
    reply_hint: str

    def synthesize(
        self,
        text: str,
        voice: str,
        audio_format: str,
        creds: dict[str, str],
        settings: Domain,
        http: aiohttp.ClientSession,
    ) -> tp.AsyncIterator[bytes]:
        """The audio bytes in order, as the provider makes them. `audio_format` is one name from
        `formats`; the caller checks that first. Raises TtsError."""
        ...

    async def subscription(self, creds: dict[str, str]) -> dict[str, JsonValue]:
        """Subscription and usage info, or an empty object for a provider with no quota."""
        ...

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation: ...

    def settings_schema(self) -> list[SettingDef]: ...


class Line(tp.TypedDict):
    by: str
    text: str


class Question(tp.TypedDict):
    agent_name: str
    # The last finished lines of the session, oldest first.
    recent: list[Line]
    # The text of the play that runs now, or None.
    agent_saying: str | None
    # The live text of the open segment.
    user_saying: str


class Verdict(tp.TypedDict):
    said_to: tp.Literal["agent", "echo", "other_person", "not_speech"]
    # None when agent_saying is None.
    wants_stop: bool | None


class Judge(tp.Protocol):
    needs_key: bool

    async def ask(self, question: Question, creds: dict[str, str], settings: Domain, http: aiohttp.ClientSession) -> Verdict | None:
        """Who the words are for, and if the user wants the agent to stop. None when it has no
        verdict: a failure, or its own timeout. It never raises."""
        ...

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation: ...

    def settings_schema(self) -> list[SettingDef]: ...
