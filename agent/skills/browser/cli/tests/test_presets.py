"""Preset selection is deterministic per profile dir, and CAMOU_CONFIG chunks round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from vesta_browser.presets import CHUNK, camou_config_env, select_preset


def test_selection_is_deterministic_per_dir():
    first = select_preset(Path("/home/x/.browser/profile/p1"))
    second = select_preset(Path("/home/x/.browser/profile/p1"))
    assert first["_name"] == second["_name"]


def test_selection_varies_across_dirs():
    names = {select_preset(Path(f"/home/x/profile/{i}"))["_name"] for i in range(30)}
    assert len(names) > 1


def test_env_excludes_internal_name_key():
    preset = select_preset(Path("/home/x/profile/p1"))
    env = camou_config_env(preset)
    joined = "".join(env[f"CAMOU_CONFIG_{i}"] for i in range(1, len(env) + 1))
    assert "_name" not in json.loads(joined)


def test_env_chunks_large_config():
    big = {"navigator.userAgent": "u" * (CHUNK + 5000)}
    env = camou_config_env(big)
    assert set(env) == {"CAMOU_CONFIG_1", "CAMOU_CONFIG_2"}
    joined = "".join(env[f"CAMOU_CONFIG_{i}"] for i in range(1, len(env) + 1))
    assert json.loads(joined) == big


def test_env_single_chunk_for_small_config():
    env = camou_config_env({"timezone": "Europe/London"})
    assert set(env) == {"CAMOU_CONFIG_1"}
