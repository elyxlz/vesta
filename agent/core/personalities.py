"""Personality preset catalog sourced from the personality skill frontmatter."""

import json
import pathlib as pl
import typing as tp

import pydantic as pyd

PRESETS_PATH = pl.Path(__file__).parent.parent / "skills" / "personality" / "presets"
_SAFE_DEFAULT = "dry"


class _PersonalityPreset(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    name: str = pyd.Field(min_length=1)
    emoji: str = ""
    title: str = ""
    description: str = ""
    sample: str = ""
    order: int = pyd.Field(default=2**31 - 1, ge=0)
    default: bool = False


class _PersonalityCatalog(pyd.BaseModel):
    default: str
    presets: list[_PersonalityPreset]


def _frontmatter_value(raw: str) -> pyd.JsonValue:
    value = raw.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.isdigit():
        return int(value)
    if value.startswith('"') and value.endswith('"'):
        decoded = json.loads(value)
        if not isinstance(decoded, str):
            raise ValueError("quoted personality metadata must be a string")
        return decoded
    return value


def _parse_preset(path: pl.Path) -> _PersonalityPreset:
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path.name} has no frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"{path.name} has unterminated frontmatter") from exc

    values: dict[str, pyd.JsonValue] = {"name": path.stem}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{path.name} has invalid frontmatter")
        key, raw = line.split(":", 1)
        values[key.strip()] = _frontmatter_value(raw)
    preset = _PersonalityPreset.model_validate(values)
    if not preset.title:
        preset = preset.model_copy(update={"title": preset.name.replace("-", " ")})
    return preset


def _load_catalog(path: pl.Path = PRESETS_PATH) -> _PersonalityCatalog:
    presets = [_parse_preset(preset_path) for preset_path in path.glob("*.md")]
    presets.sort(key=lambda preset: (preset.order, preset.name))
    defaults = [preset.name for preset in presets if preset.default]
    if len(defaults) != 1:
        raise ValueError("personality presets must declare exactly one default")
    return _PersonalityCatalog(default=defaults[0], presets=presets)


def _load_default() -> str:
    try:
        return _load_catalog().default
    except (OSError, ValueError, pyd.ValidationError):
        return _SAFE_DEFAULT


DEFAULT_PERSONALITY = _load_default()


def read_personality_catalog(path: pl.Path = PRESETS_PATH) -> dict[str, pyd.JsonValue]:
    """Return the live preset metadata and its skill-owned default."""
    catalog = _load_catalog(path)
    payload = catalog.model_dump(mode="json", exclude={"presets": {"__all__": {"default"}}})
    return tp.cast("dict[str, pyd.JsonValue]", payload)
