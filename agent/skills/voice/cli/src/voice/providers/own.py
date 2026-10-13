"""Providers of this box.

Add a provider that you wrote to the map of its role, under a name that no other provider of
that role uses. `voice status` then lists it, and `voice <role> connect <name>` selects it.
~/agent/skills/voice/SKILL.md ("Own providers") has the steps and the rules.

    from .whisper_local import WhisperLocal
    STT: dict[str, SttProvider] = {"whisper-local": WhisperLocal()}
"""

from .base import Judge, SttProvider, TtsProvider

STT: dict[str, SttProvider] = {}
TTS: dict[str, TtsProvider] = {}
JUDGES: dict[str, Judge] = {}
