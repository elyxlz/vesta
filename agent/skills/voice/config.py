"""Read/write ~/vesta/data/voice_config.json atomically."""

import json
import os
import pathlib as pl
import typing as tp

VOICE_CONFIG_FILENAME = "voice_config.json"


class VoiceDomain(tp.TypedDict, total=False):
    provider: str
    credentials: dict[str, dict[str, str]]


class SttDomain(VoiceDomain, total=False):
    keyterms: list[str]
    eot_threshold: float
    eot_timeout_ms: int


class TtsDomain(VoiceDomain, total=False):
    selected_voice_id: str
    custom_voices: list[dict[str, str]]


class VoiceConfig(tp.TypedDict, total=False):
    stt: SttDomain | None
    tts: TtsDomain | None


def config_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / VOICE_CONFIG_FILENAME


def load(data_dir: pl.Path) -> VoiceConfig:
    path = config_path(data_dir)
    if not path.exists():
        return {"stt": None, "tts": None}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"stt": None, "tts": None}
    return {
        "stt": raw.get("stt") or None,
        "tts": raw.get("tts") or None,
    }


def save(data_dir: pl.Path, config: VoiceConfig) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(data_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n")
    os.replace(tmp, path)


def mutate(data_dir: pl.Path, updater: tp.Callable[[VoiceConfig], VoiceConfig]) -> VoiceConfig:
    """Load, apply updater, write back. Returns the new config."""
    current = load(data_dir)
    new = updater(current)
    save(data_dir, new)
    return new


def set_key(data_dir: pl.Path, domain: tp.Literal["stt", "tts"], provider: str, api_key: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        existing = cfg.get(domain) or {}
        creds = dict(existing.get("credentials") or {})
        creds[provider] = {"api_key": api_key}
        cfg[domain] = {**existing, "provider": provider, "credentials": creds}
        return cfg

    return mutate(data_dir, _update)


def clear_domain(data_dir: pl.Path, domain: tp.Literal["stt", "tts"]) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        cfg[domain] = None 
        return cfg

    return mutate(data_dir, _update)


def set_voice(data_dir: pl.Path, voice_id: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = dict(cfg.get("tts") or {})
        if not tts:
            raise ValueError("TTS not configured; set a provider key first")
        tts["selected_voice_id"] = voice_id
        cfg["tts"] = tts  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)


def add_custom_voice(data_dir: pl.Path, voice_id: str, name: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = dict(cfg.get("tts") or {})
        if not tts:
            raise ValueError("TTS not configured; set a provider key first")
        provider = tts.get("provider") or "elevenlabs"
        voices = list(tts.get("custom_voices") or [])
        if any(v.get("id") == voice_id for v in voices):
            return cfg
        voices.append({"provider": provider, "id": voice_id, "name": name})
        tts["custom_voices"] = voices
        cfg["tts"] = tts  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)


def remove_custom_voice(data_dir: pl.Path, voice_id: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        tts = dict(cfg.get("tts") or {})
        if not tts:
            return cfg
        tts["custom_voices"] = [v for v in (tts.get("custom_voices") or []) if v.get("id") != voice_id]
        cfg["tts"] = tts  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)


def add_keyterm(data_dir: pl.Path, term: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = dict(cfg.get("stt") or {})
        if not stt:
            raise ValueError("STT not configured; set a provider key first")
        terms = list(stt.get("keyterms") or [])
        if term not in terms:
            terms.append(term)
        stt["keyterms"] = terms
        cfg["stt"] = stt  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)


def remove_keyterm(data_dir: pl.Path, term: str) -> VoiceConfig:
    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = dict(cfg.get("stt") or {})
        if not stt:
            return cfg
        stt["keyterms"] = [t for t in (stt.get("keyterms") or []) if t != term]
        cfg["stt"] = stt  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)


def set_eot_threshold(data_dir: pl.Path, threshold: float) -> VoiceConfig:
    if not 0.0 < threshold <= 1.0:
        raise ValueError(f"threshold must be in (0, 1], got {threshold}")

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = dict(cfg.get("stt") or {})
        if not stt:
            raise ValueError("STT not configured; set a provider key first")
        stt["eot_threshold"] = threshold
        cfg["stt"] = stt  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)


def set_eot_timeout_ms(data_dir: pl.Path, timeout_ms: int) -> VoiceConfig:
    if timeout_ms < 1000:
        raise ValueError(f"timeout_ms must be >= 1000, got {timeout_ms}")

    def _update(cfg: VoiceConfig) -> VoiceConfig:
        stt = dict(cfg.get("stt") or {})
        if not stt:
            raise ValueError("STT not configured; set a provider key first")
        stt["eot_timeout_ms"] = timeout_ms
        cfg["stt"] = stt  # type: ignore[typeddict-item]
        return cfg

    return mutate(data_dir, _update)
