"""Provider interfaces for STT/TTS backends."""

from __future__ import annotations

import typing as tp

from aiohttp import web


class SettingDef(tp.TypedDict, total=False):
    key: str
    type: str  # "bool" | "number" | "select"
    label: str
    description: str
    default: tp.Any
    config: list["SettingDef"]
    config_label: str
    # number:
    min: float
    max: float
    step: float
    unit: str
    # select:
    options: list[dict[str, tp.Any]]


class SttProvider(tp.Protocol):
    name: str

    async def relay(self, browser_ws: web.WebSocketResponse, creds: dict[str, str], stt_domain: dict) -> None:
        """Open upstream STT connection, relay audio frames <-> transcript events."""
        ...

    async def usage(self, creds: dict[str, str]) -> dict:
        """Return usage summary for the given credentials."""
        ...

    async def balance(self, creds: dict[str, str]) -> dict:
        """Return remaining balance for the given credentials."""
        ...

    async def validate(self, api_key: str) -> tuple[bool, str | None]:
        """Return (valid, error_message) for the given API key."""
        ...

    def settings_schema(self) -> list[SettingDef]:
        """Return provider-specific settings definitions."""
        ...


class TtsProvider(tp.Protocol):
    name: str

    async def speak(
        self,
        text: str,
        voice_id: str,
        creds: dict[str, str],
        request: web.Request,
    ) -> web.StreamResponse:
        """Stream synthesized audio bytes back as audio/mpeg."""
        ...

    def premade_voices(self) -> list[dict]:
        """Return the provider's premade voice catalogue."""
        ...

    async def subscription(self, creds: dict[str, str]) -> dict:
        """Return subscription/usage info."""
        ...

    async def validate(self, api_key: str) -> tuple[bool, str | None]:
        """Return (valid, error_message) for the given API key."""
        ...

    def settings_schema(self) -> list[SettingDef]:
        """Return provider-specific settings definitions."""
        ...
