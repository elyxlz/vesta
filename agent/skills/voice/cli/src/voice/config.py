"""Read/write ~/.voice/voice_config.json atomically."""

import json
import pathlib as pl
import typing as tp

VOICE_CONFIG_FILENAME = "voice_config.json"

DEFAULT_EOT_THRESHOLD = 0.8
DEFAULT_EOT_TIMEOUT_MS = 5000
EOT_THRESHOLD_MIN = 0.5
EOT_THRESHOLD_MAX = 0.9
EOT_TIMEOUT_MS_MIN = 500
EOT_TIMEOUT_MS_MAX = 10000

# Domain entries are dynamic string-keyed maps: their keys come from each
# provider's settings schema (eot_threshold, keyterms, custom_voices, ...).
SettingValue = bool | int | float | str | list[str] | list[dict[str, str]] | dict[str, dict[str, str]]
Domain = dict[str, SettingValue]
VoiceConfig = dict[tp.Literal["stt", "tts"], Domain | None]


def config_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / VOICE_CONFIG_FILENAME


def load(data_dir: pl.Path) -> VoiceConfig:
    path = config_path(data_dir)
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {"stt": None, "tts": None}
    cfg: VoiceConfig = {
        "stt": raw.get("stt") or None,
        "tts": raw.get("tts") or None,
    }
    # Migrate top-level preferences into their domains.
    stt = cfg["stt"]
    if "voice_auto_send" in raw and stt:
        stt.setdefault("auto_send", raw["voice_auto_send"])
    tts = cfg["tts"]
    if "speech_enabled" in raw and tts:
        tts.setdefault("speech_enabled", raw["speech_enabled"])
    return cfg


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


def _credentials(entry: Domain) -> dict[str, dict[str, str]]:
    creds = entry["credentials"] if "credentials" in entry else {}
    return dict(creds) if isinstance(creds, dict) else {}


def _str_list(entry: Domain, key: str) -> list[str]:
    value = entry[key] if key in entry else []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def custom_voices(entry: Domain) -> list[dict[str, str]]:
    value = entry["custom_voices"] if "custom_voices" in entry else []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def set_key(data_dir: pl.Path, domain: tp.Literal["stt", "tts"], provider: str, api_key: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        existing = cfg[domain] or {}
        creds = _credentials(existing)
        creds[provider] = {"api_key": api_key}
        cfg[domain] = {**existing, "provider": provider, "credentials": creds, "enabled": True}
        return cfg

    return mutate(data_dir, _update)


def clear_domain(data_dir: pl.Path, domain: tp.Literal["stt", "tts"]) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        cfg[domain] = None
        return cfg

    return mutate(data_dir, _update)


def set_voice(data_dir: pl.Path, voice_id: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = cfg["tts"]
        if not tts:
            raise ValueError("TTS not configured; set a provider key first")
        cfg["tts"] = {**tts, "selected_voice_id": voice_id}
        return cfg

    return mutate(data_dir, _update)


def add_custom_voice(data_dir: pl.Path, voice_id: str, name: str, description: str = "") -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = cfg["tts"]
        if not tts:
            raise ValueError("TTS not configured; set a provider key first")
        provider_value = tts["provider"] if "provider" in tts else ""
        provider = provider_value if isinstance(provider_value, str) and provider_value else "elevenlabs"
        voices = custom_voices(tts)
        existing = next((v for v in voices if v.get("id") == voice_id), None)
        if existing:
            existing["name"] = name
            if description:
                existing["description"] = description
            elif "description" in existing:
                del existing["description"]
        else:
            entry: dict[str, str] = {"provider": provider, "id": voice_id, "name": name}
            if description:
                entry["description"] = description
            voices.append(entry)
        cfg["tts"] = {**tts, "custom_voices": voices}
        return cfg

    return mutate(data_dir, _update)


def remove_custom_voice(data_dir: pl.Path, voice_id: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = cfg["tts"]
        if not tts:
            return cfg
        cfg["tts"] = {**tts, "custom_voices": [v for v in custom_voices(tts) if v.get("id") != voice_id]}
        return cfg

    return mutate(data_dir, _update)


def add_keyterm(data_dir: pl.Path, term: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = cfg["stt"]
        if not stt:
            raise ValueError("STT not configured; set a provider key first")
        terms = _str_list(stt, "keyterms")
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
        cfg["stt"] = {**stt, "keyterms": [t for t in _str_list(stt, "keyterms") if t != term]}
        return cfg

    return mutate(data_dir, _update)


def _validated_eot_threshold(value: SettingValue) -> float:
    if isinstance(value, list | dict):
        raise ValueError(f"eot_threshold must be a number, got {value!r}")
    threshold = float(value)
    if not EOT_THRESHOLD_MIN <= threshold <= EOT_THRESHOLD_MAX:
        raise ValueError(
            f"eot_threshold must be in [{EOT_THRESHOLD_MIN}, {EOT_THRESHOLD_MAX}], got {threshold}",
        )
    return threshold


def _validated_eot_timeout_ms(value: SettingValue) -> int:
    if isinstance(value, list | dict):
        raise ValueError(f"eot_timeout_ms must be a number, got {value!r}")
    timeout_ms = int(value)
    if not EOT_TIMEOUT_MS_MIN <= timeout_ms <= EOT_TIMEOUT_MS_MAX:
        raise ValueError(
            f"eot_timeout_ms must be in [{EOT_TIMEOUT_MS_MIN}, {EOT_TIMEOUT_MS_MAX}], got {timeout_ms}",
        )
    return timeout_ms


def set_eot_threshold(data_dir: pl.Path, threshold: float) -> VoiceConfig:
    validated = _validated_eot_threshold(threshold)

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = cfg["stt"]
        if not stt:
            raise ValueError("STT not configured; set a provider key first")
        cfg["stt"] = {**stt, "eot_threshold": validated}
        return cfg

    return mutate(data_dir, _update)


def set_eot_timeout_ms(data_dir: pl.Path, timeout_ms: int) -> VoiceConfig:
    validated = _validated_eot_timeout_ms(timeout_ms)

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = cfg["stt"]
        if not stt:
            raise ValueError("STT not configured; set a provider key first")
        cfg["stt"] = {**stt, "eot_timeout_ms": validated}
        return cfg

    return mutate(data_dir, _update)


def set_stt_auto_send(data_dir: pl.Path, value: bool) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        cfg["stt"] = {**(cfg["stt"] or {}), "auto_send": value}
        return cfg

    return mutate(data_dir, _update)


def set_setting(data_dir: pl.Path, domain: tp.Literal["stt", "tts"], key: str, value: SettingValue) -> VoiceConfig:
    """Generic setter — stores value at cfg[domain][key]."""
    if domain == "stt" and key == "eot_threshold":
        value = _validated_eot_threshold(value)
    elif domain == "stt" and key == "eot_timeout_ms":
        value = _validated_eot_timeout_ms(value)

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        entry = cfg[domain]
        if not entry:
            raise ValueError(f"{domain.upper()} not configured; set a provider key first")
        cfg[domain] = {**entry, key: value}
        return cfg

    return mutate(data_dir, _update)


def set_enabled(data_dir: pl.Path, domain: tp.Literal["stt", "tts"], value: bool) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        cfg[domain] = {**(cfg[domain] or {}), "enabled": value}
        return cfg

    return mutate(data_dir, _update)
