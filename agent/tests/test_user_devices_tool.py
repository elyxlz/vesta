"""The `user_devices` tool renders vestad's device list for the agent and reports, rather than
raises, when vestad cannot answer."""

import asyncio
from unittest.mock import AsyncMock, patch

from core import config as cfg
from core import models as vm
from core.tools import _vesta_tools


def _tool(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path)
    return {t.name: t for t in _vesta_tools(vm.State(), config)}["user_devices"]


def test_user_devices_renders_the_device_list(tmp_path):
    devices = {"devices": [{"id": "dev-1", "timezone": "Asia/Tokyo", "position": None}]}
    with patch("core.vestad_client.fetch_user_devices", new_callable=AsyncMock, return_value=devices):
        result = asyncio.run(_tool(tmp_path).handler({}))
    text = result["content"][0]["text"]
    assert '"timezone": "Asia/Tokyo"' in text
    assert "isError" not in result


def test_user_devices_reports_an_unreachable_vestad(tmp_path):
    with patch("core.vestad_client.fetch_user_devices", new_callable=AsyncMock, return_value=None):
        result = asyncio.run(_tool(tmp_path).handler({}))
    assert result["content"][0]["text"].startswith("error:")
