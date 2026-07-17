"""Preset selection is deterministic per profile dir, and CAMOU_CONFIG chunks round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from vesta_browser.presets import CHUNK, camou_config_env, fit_to_screen, select_preset


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


def test_selected_preset_disables_camoufox_cursor_highlight():
    # Camoufox defaults its red humanize-cursor highlight on; a real session must never show it.
    env = camou_config_env(select_preset(Path("/home/x/profile/p1")))
    joined = "".join(env[f"CAMOU_CONFIG_{i}"] for i in range(1, len(env) + 1))
    assert json.loads(joined)["showcursor"] is False


def test_fit_to_screen_rewrites_geometry_keeping_chrome():
    preset = {
        "screen.width": 1920,
        "screen.height": 1080,
        "screen.availWidth": 1920,
        "screen.availHeight": 1053,
        "window.outerWidth": 1920,
        "window.outerHeight": 1053,
        "window.innerWidth": 1920,
        "window.innerHeight": 953,
        "navigator.platform": "Linux x86_64",
    }
    fitted = fit_to_screen(preset, 1600, 1000)
    assert fitted["screen.width"] == fitted["screen.availWidth"] == fitted["window.outerWidth"] == 1600
    assert fitted["screen.height"] == fitted["screen.availHeight"] == fitted["window.outerHeight"] == 1000
    assert fitted["window.innerWidth"] == 1600  # preset had no horizontal chrome
    assert fitted["window.innerHeight"] == 900  # preset's 100px chrome height carries over
    assert fitted["navigator.platform"] == "Linux x86_64"
    assert preset["window.outerWidth"] == 1920  # input preset untouched


def test_every_bundled_preset_fits_the_handover_screen():
    from vesta_browser.handover import SCREEN_H, SCREEN_W
    from vesta_browser.presets import _load

    for preset in _load():
        fitted = fit_to_screen(preset, SCREEN_W, SCREEN_H)
        assert fitted["window.innerWidth"] <= SCREEN_W
        assert 0 < fitted["window.innerHeight"] <= SCREEN_H


def test_handover_screen_is_a_real_monitor_geometry():
    # fit_to_screen reports the framebuffer verbatim as screen.width/height, so a size no real
    # display ships is an automation tell. 16:10 also keeps the browser filling the page's cut-out.
    from vesta_browser.handover import SCREEN_H, SCREEN_W

    assert (SCREEN_W, SCREEN_H) in {(1920, 1200), (1680, 1050), (1440, 900)}
    assert SCREEN_W / SCREEN_H == 1.6
