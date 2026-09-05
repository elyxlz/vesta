import asyncio
import json
import os
import pathlib as pl
import stat
import sys

import pytest
from vesta_browser import gateway

FAKE_SERVICE_KEY = f"""#!{sys.executable}
import json, os, sys
cmd = sys.argv[1]
service = sys.argv[2]
state = os.environ["FAKE_KEYS"]
keys = json.load(open(state)) if os.path.exists(state) else []
if cmd == "mint":
    label = sys.argv[sys.argv.index("--label") + 1]
    ttl = sys.argv[sys.argv.index("--ttl") + 1]
    keys.append({{"id": f"id{{len(keys) + 1}}", "label": label, "ttl": int(ttl)}})
    json.dump(keys, open(state, "w"))
    print(f"secret-{{label}}")
elif cmd == "list":
    print(json.dumps({{"keys": [{{"id": k["id"], "label": k["label"]}} for k in keys]}}))
elif cmd == "revoke":
    keys = [k for k in keys if k["id"] != sys.argv[3]]
    json.dump(keys, open(state, "w"))
else:
    print("usage", file=sys.stderr); sys.exit(2)
"""

FAKE_REGISTER = f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_REGISTER_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
print(os.environ["FAKE_PORT"])
"""

FAKE_DEREGISTER = f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_REGISTER_LOG"], "a").write("deregister " + sys.argv[1] + "\\n")
"""


def _script(bin_dir: pl.Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def gateway_env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir, "service-key", FAKE_SERVICE_KEY)
    _script(bin_dir, "register-service", FAKE_REGISTER)
    _script(bin_dir, "deregister-service", FAKE_DEREGISTER)
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
    _script(gateway_env / "bin", "register-service", f"#!{sys.executable}\nimport sys; print('vestad down', file=sys.stderr); sys.exit(1)\n")
    with pytest.raises(gateway.GatewayError, match="vestad down"):
        asyncio.run(gateway.register_service("browser"))


def test_missing_script_raises_gateway_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(gateway.GatewayError, match="register-service"):
        asyncio.run(gateway.register_service("browser"))
