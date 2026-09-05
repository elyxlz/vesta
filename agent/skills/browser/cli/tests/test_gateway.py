import asyncio
import json
import os
import sys

import pytest
from vesta_browser import gateway

from .fakes import write_gateway_fakes, write_script


@pytest.fixture
def gateway_env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    write_gateway_fakes(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_KEYS", str(tmp_path / "keys.json"))
    monkeypatch.setenv("FAKE_REGISTER_LOG", str(tmp_path / "register.log"))
    monkeypatch.setenv("FAKE_PORT", "43210")
    return tmp_path


def test_register_returns_the_port_and_never_passes_public(gateway_env):
    port = asyncio.run(gateway.register_service("browser"))
    assert port == 43210
    assert (gateway_env / "register.log").read_text() == "browser\n"


def test_mint_list_revoke_round_trip(gateway_env):
    async def run():
        secret = await gateway.mint_key("browser", "browser-handover-abc", 1800)
        key_id = await gateway.find_key_id("browser", "browser-handover-abc")
        await gateway.revoke_key("browser", key_id)
        gone = await gateway.find_key_id("browser", "browser-handover-abc")
        return secret, key_id, gone

    secret, key_id, gone = asyncio.run(run())
    assert secret == "secret-browser-handover-abc" and key_id == "id1" and gone is None
    assert json.loads((gateway_env / "keys.json").read_text()) == []


def test_deregister_is_idempotent(gateway_env):
    asyncio.run(gateway.deregister_service("browser"))
    asyncio.run(gateway.deregister_service("browser"))
    assert (gateway_env / "register.log").read_text() == "deregister browser\nderegister browser\n"


def test_a_failing_script_raises_gateway_error(gateway_env, monkeypatch):
    body = f"#!{sys.executable}\nimport sys; print('vestad down', file=sys.stderr); sys.exit(1)\n"
    write_script(gateway_env / "bin", "register-service", body)
    with pytest.raises(gateway.GatewayError, match="vestad down"):
        asyncio.run(gateway.register_service("browser"))


def test_missing_script_raises_gateway_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(gateway.GatewayError, match="register-service"):
        asyncio.run(gateway.register_service("browser"))
