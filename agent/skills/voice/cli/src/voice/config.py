"""Read/write ~/.voice/voice_config.json atomically.

The file has one entry for each role (`stt`, `tts`, `judge`) and one `behavior` entry, and an
entry with nothing in it is `{}`. A role entry holds `provider` (the selected one), `credentials` (one entry for each connected provider:
its key, or an empty entry for a provider that needs no key), `enabled`, and the settings of its
providers. Each provider reads only its own setting keys, so a switch between providers loses
nothing.
"""

import json
import pathlib as pl
import typing as tp

from .settings import Domain, SettingValue

VOICE_CONFIG_FILENAME = "voice_config.json"

Role = tp.Literal["stt", "tts", "judge"]
Section = tp.Literal["stt", "tts", "judge", "behavior"]
ROLES: tuple[Role, ...] = ("stt", "tts", "judge")
SECTIONS: tuple[Section, ...] = ("stt", "tts", "judge", "behavior")
# `connect` turns these roles on. The judge sends live text to its provider, so the user turns
# it on as a separate step.
ROLES_ON_AT_CONNECT: tuple[Role, ...] = ("stt", "tts")

# The keys of a role entry that are not a provider's settings.
ROLE_KEYS = ("provider", "credentials", "enabled")

VoiceConfig = dict[Section, Domain]


def data_dir() -> pl.Path:
    return pl.Path.home() / ".voice"


def config_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / VOICE_CONFIG_FILENAME


def load(data_dir: pl.Path) -> VoiceConfig:
    path = config_path(data_dir)
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        raw = {}
    return {section: raw[section] if section in raw and isinstance(raw[section], dict) else {} for section in SECTIONS}


def save(data_dir: pl.Path, config: VoiceConfig) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(data_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n")
    tmp.replace(path)


def mutate(data_dir: pl.Path, updater: tp.Callable[[VoiceConfig], VoiceConfig]) -> VoiceConfig:
    """Load, apply updater, write back. Returns the new config."""
    current = load(data_dir)
    new = updater(current)
    save(data_dir, new)
    return new


def provider_name(entry: Domain) -> str | None:
    """The role's selected provider name, or None when it has none."""
    if "provider" not in entry:
        return None
    name = entry["provider"]
    return name if isinstance(name, str) and name else None


def connected(entry: Domain) -> list[str]:
    """The providers connected to a role, in name order."""
    return sorted(_credentials(entry))


def provider_creds(entry: Domain, provider: str) -> dict[str, str]:
    """The credentials stored for one provider under a role: empty for a provider with no key."""
    creds = _credentials(entry)
    value = creds[provider] if provider in creds else {}
    return dict(value) if isinstance(value, dict) else {}


def provider_settings(entry: Domain) -> Domain:
    """What a provider sees of its role entry: the settings, and never a key of another provider."""
    return {key: value for key, value in entry.items() if key not in ROLE_KEYS}


def is_enabled(entry: Domain) -> bool:
    return "enabled" in entry and bool(entry["enabled"])


def _credentials(entry: Domain) -> dict[str, dict[str, str]]:
    creds = entry["credentials"] if "credentials" in entry else {}
    return dict(creds) if isinstance(creds, dict) else {}


def _str_list(entry: Domain, key: str) -> list[str]:
    value = entry[key] if key in entry else []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def custom_voices(entry: Domain) -> list[dict[str, str]]:
    value = entry["custom_voices"] if "custom_voices" in entry else []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def provider_voices(entry: Domain, provider: str) -> list[dict[str, str]]:
    """The voices the user added for one provider."""
    return [v for v in custom_voices(entry) if "provider" in v and v["provider"] == provider and "id" in v]


def selected_entry(config: VoiceConfig, role: Role) -> tuple[Domain, str]:
    """The role's entry and its selected provider name. Raises ValueError when it has none."""
    entry = config[role]
    name = provider_name(entry)
    if name is None:
        raise ValueError(f"{role} has no selected provider; run `voice {role} connect <provider>` first")
    return entry, name


def connect(data_dir: pl.Path, role: Role, provider: str, creds: dict[str, str]) -> VoiceConfig:
    """Store the provider's entry and select it."""

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        existing = cfg[role]
        stored = _credentials(existing)
        stored[provider] = creds
        enabled = True if role in ROLES_ON_AT_CONNECT else is_enabled(existing)
        cfg[role] = {**existing, "provider": provider, "credentials": stored, "enabled": enabled}
        return cfg

    return mutate(data_dir, _update)


def use(data_dir: pl.Path, role: Role, provider: str) -> VoiceConfig:
    """Select a connected provider. The settings and the key of every provider stay."""

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        entry = cfg[role]
        if provider not in connected(entry):
            raise ValueError(f"{provider} is not connected to {role}; run `voice {role} connect {provider}` first")
        cfg[role] = {**entry, "provider": provider}
        return cfg

    return mutate(data_dir, _update)


def disconnect(data_dir: pl.Path, role: Role, provider: str) -> VoiceConfig:
    """Remove the provider's entry. A selected provider hands over to the next connected one in
    name order, and a role with none left is off."""

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        entry = cfg[role]
        if not entry:
            return cfg
        stored = _credentials(entry)
        stored.pop(provider, None)
        updated: Domain = {**entry, "credentials": stored}
        if provider_name(entry) == provider:
            if stored:
                updated["provider"] = min(stored)
            else:
                del updated["provider"]
                updated["enabled"] = False
        cfg[role] = updated
        return cfg

    return mutate(data_dir, _update)


def set_enabled(data_dir: pl.Path, role: Role, value: bool) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        if value:
            selected_entry(cfg, role)
        cfg[role] = {**cfg[role], "enabled": value}
        return cfg

    return mutate(data_dir, _update)


def set_setting(data_dir: pl.Path, section: Section, key: str, value: SettingValue) -> VoiceConfig:
    """Store one value. The caller checks it against the schema first (settings.check_setting)."""

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        if section == "behavior":
            cfg["behavior"] = {**cfg["behavior"], key: value}
            return cfg
        entry, _name = selected_entry(cfg, section)
        cfg[section] = {**entry, key: value}
        return cfg

    return mutate(data_dir, _update)


def add_custom_voice(data_dir: pl.Path, voice_id: str, name: str, description: str = "") -> VoiceConfig:
    """Add a voice of the user's own to the selected TTS provider, or rename one that is there."""

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts, provider = selected_entry(cfg, "tts")
        voice: dict[str, str] = {"provider": provider, "id": voice_id, "name": name}
        if description:
            voice["description"] = description
        others = [v for v in custom_voices(tts) if not ("id" in v and v["id"] == voice_id)]
        cfg["tts"] = {**tts, "custom_voices": [*others, voice]}
        return cfg

    return mutate(data_dir, _update)


def remove_custom_voice(data_dir: pl.Path, voice_id: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = cfg["tts"]
        if not tts:
            return cfg
        cfg["tts"] = {**tts, "custom_voices": [v for v in custom_voices(tts) if not ("id" in v and v["id"] == voice_id)]}
        return cfg

    return mutate(data_dir, _update)


def keyterms(entry: Domain) -> list[str]:
    return _str_list(entry, "keyterms")


def add_keyterm(data_dir: pl.Path, term: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt, _name = selected_entry(cfg, "stt")
        terms = keyterms(stt)
        if term not in terms:
            terms.append(term)
        cfg["stt"] = {**stt, "keyterms": terms}
        return cfg

    return mutate(data_dir, _update)


def remove_keyterm(data_dir: pl.Path, term: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = cfg["stt"]
        if not stt:
            return cfg
        cfg["stt"] = {**stt, "keyterms": [t for t in keyterms(stt) if t != term]}
        return cfg

    return mutate(data_dir, _update)
