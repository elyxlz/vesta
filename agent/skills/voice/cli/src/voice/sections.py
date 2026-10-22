"""The settings of each section: which schema checks a value, and the one checked write.

A section is a role (`stt`, `tts`, `judge`) or `behavior`. A role's schema is the schema of its
selected provider, and the behaviors have the engine's schema. A behavior has a shared value and a
value for each client that keeps its own; a role setting has one value for every client. Every
`set` command and every `set` route writes through `store_setting`, so a value is checked in
exactly one place, and every status reads through `section_view`, so a view shows what the check
accepts.
"""

import pathlib as pl

from . import config as voice_config
from . import providers
from .engine import behavior
from .settings import JsonValue, SettingDef, SettingOption, SettingValue, check_setting


def _with_own_voices(schema: list[SettingDef], voice_setting: str, voices: list[dict[str, str]]) -> list[SettingDef]:
    """The schema with the user's own voices added to the options of the voice select."""
    own: list[SettingOption] = []
    for voice in voices:
        option: SettingOption = {"value": voice["id"], "label": voice["name"] if "name" in voice else voice["id"], "custom": True}
        if "description" in voice:
            option["description"] = voice["description"]
        own.append(option)
    return [
        {**definition, "options": [*definition["options"], *own]}
        if definition["key"] == voice_setting and "options" in definition
        else definition
        for definition in schema
    ]


def section_schema(config: voice_config.VoiceConfig, section: voice_config.Section) -> list[SettingDef]:
    """The schema that checks a value of this section. Raises ValueError for a role with no
    selected provider."""
    if section == "behavior":
        return behavior.BEHAVIOR_SCHEMA
    entry, name = voice_config.selected_entry(config, section)
    provider = providers.get(section, name)
    if provider is None:
        raise ValueError(f"unknown {section} provider: {name}")
    tts = providers.get_tts(name) if section == "tts" else None
    if tts is None:
        return provider.settings_schema()
    return _with_own_voices(tts.settings_schema(), tts.voice_setting, voice_config.provider_voices(entry, name))


def section_view(config: voice_config.VoiceConfig, section: voice_config.Section, client: str | None = None) -> list[dict[str, JsonValue]]:
    """The schema of the section with the current value of each setting, which is what a settings
    card renders. A client sees its own behaviors. Empty for a role with no selected provider."""
    try:
        schema = section_schema(config, section)
    except ValueError:
        return []
    entry = voice_config.client_behavior(config["behavior"], client) if section == "behavior" else config[section]
    return [{**d, "value": entry[d["key"]] if d["key"] in entry else (d["default"] if "default" in d else None)} for d in schema]


def store_setting(data_dir: pl.Path, section: voice_config.Section, key: str, value: SettingValue, client: str | None = None) -> None:
    """Check one value against the schema of its section and store it, for one client when it names
    one. Raises ValueError."""
    schema = section_schema(voice_config.load(data_dir), section)
    checked = check_setting(schema, key, value)
    if client is None:
        voice_config.set_setting(data_dir, section, key, checked)
    elif section == "behavior":
        voice_config.set_client_behavior(data_dir, client, key, checked)
    else:
        raise ValueError(f"only a behavior has a value for each client, and {section} is a role")


def clear_client_setting(data_dir: pl.Path, client: str, key: str) -> None:
    """Remove the value that one client keeps for a behavior, so it follows the shared value again.
    Raises ValueError for a key that is not a behavior."""
    if all(d["key"] != key for d in behavior.BEHAVIOR_SCHEMA):
        known = ", ".join(d["key"] for d in behavior.BEHAVIOR_SCHEMA)
        raise ValueError(f"unknown behavior: {key} (behaviors: {known})")
    voice_config.set_client_behavior(data_dir, client, key, None)


def store_voice(data_dir: pl.Path, voice_id: str) -> None:
    """Store the voice under the selected TTS provider's own key. Raises ValueError."""
    _entry, name = voice_config.selected_entry(voice_config.load(data_dir), "tts")
    provider = providers.get_tts(name)
    if provider is None:
        raise ValueError(f"unknown tts provider: {name}")
    store_setting(data_dir, "tts", provider.voice_setting, voice_id)
