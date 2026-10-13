"""The settings of each section: which schema checks a value, and the one checked write.

A section is a role (`stt`, `tts`, `judge`) or `behavior`. A role's schema is the schema of its
selected provider, and the behaviors have the engine's schema. Every `set` command and every
`set` route writes through `store_setting`, so a value is checked in exactly one place.
"""

import pathlib as pl

from . import config as voice_config
from . import providers
from .engine import behavior
from .settings import Domain, JsonValue, SettingDef, SettingValue, check_setting


def settings_view(schema: list[SettingDef], entry: Domain) -> list[dict[str, JsonValue]]:
    """The schema with the current value of each setting, which is what a settings card renders."""
    view: list[dict[str, JsonValue]] = []
    for definition in schema:
        key = definition["key"]
        default = definition["default"] if "default" in definition else None
        value = entry[key] if key in entry else default
        view.append({**definition, "value": value})
    return view


def section_schema(config: voice_config.VoiceConfig, section: voice_config.Section) -> tuple[list[SettingDef], list[str]]:
    """The schema that checks a value of this section, and the extra values its voice select
    accepts (the user's own voices). Raises ValueError for a role with no selected provider."""
    if section == "behavior":
        return behavior.BEHAVIOR_SCHEMA, []
    entry = config[section]
    name = voice_config.provider_name(entry)
    provider = providers.get(section, name) if name is not None else None
    if not entry or name is None or provider is None:
        raise ValueError(f"{section} has no selected provider; run `voice {section} connect <provider>` first")
    extra = voice_config.custom_voice_ids(entry, name) if section == "tts" else []
    return provider.settings_schema(), extra


def store_setting(data_dir: pl.Path, section: voice_config.Section, key: str, value: SettingValue) -> None:
    """Check one value against the schema of its section and store it. Raises ValueError."""
    schema, extra = section_schema(voice_config.load(data_dir), section)
    voice_config.set_setting(data_dir, section, key, check_setting(schema, key, value, extra))
