import json
import typing

import pytest
from aiohttp import web

from core import api
from core.personalities import PRESETS_PATH, read_personality_catalog


def test_shipped_personality_catalog_is_ordered_with_one_default():
    catalog = read_personality_catalog()
    assert catalog["default"] == "dry"
    presets = catalog["presets"]
    assert isinstance(presets, list)
    assert [preset["name"] for preset in presets] == ["dry", "classic", "polished", "terse", "chill", "extra"]
    assert all("default" not in preset for preset in presets)
    assert PRESETS_PATH.name == "presets"


def test_personality_catalog_requires_exactly_one_default(tmp_path):
    (tmp_path / "one.md").write_text("---\ntitle: one\norder: 1\n---\nvoice")
    with pytest.raises(ValueError, match="exactly one default"):
        read_personality_catalog(tmp_path)


@pytest.mark.anyio
async def test_personalities_handler_returns_the_skill_catalog():
    response = await api._personalities_handler(typing.cast("web.Request", None))
    assert response.status == 200
    assert json.loads(typing.cast("str", response.text))["default"] == "dry"
