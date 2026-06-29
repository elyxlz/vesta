import datetime as dt

import pytest

import core.models as vm
from core import whatsmeow_freshness as wf

_HEAD_SHA = "5f04eac6dbbbaaaa1111222233334444555566ff"
_HEAD_TIME = dt.datetime(2026, 6, 22, 18, 54, 15, tzinfo=dt.UTC)
_ON_HEAD = "v0.0.0-20260622185415-5f04eac6dbbb"  # short hash matches _HEAD_SHA prefix
_OLD = "v0.0.0-20260604205742-c6a4b703e48f"


def _gomod(version: str) -> str:
    return f"module whatsapp\n\ngo 1.25\n\nrequire (\n\tgo.mau.fi/whatsmeow {version}\n)\n"


def test_installed_version_parses():
    assert wf.installed_version(_gomod(_OLD)) == _OLD


def test_installed_version_absent():
    assert wf.installed_version("module x\n\ngo 1.25\n") is None


def test_is_behind_true_when_older():
    assert wf.is_behind(_OLD, _HEAD_SHA, _HEAD_TIME) is True


def test_is_behind_false_on_head():
    assert wf.is_behind(_ON_HEAD, _HEAD_SHA, _HEAD_TIME) is False


def test_is_behind_false_when_unparseable():
    assert wf.is_behind("v1.2.3", _HEAD_SHA, _HEAD_TIME) is False


def _config(tmp_path, version: str | None):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    if version is not None:
        cli = config.skills_dir / "whatsapp" / "cli"
        cli.mkdir(parents=True, exist_ok=True)
        (cli / "go.mod").write_text(_gomod(version))
    return config


def _stale_files(config) -> list:
    return list(config.notifications_dir.glob(f"{vm.TYPE_WHATSMEOW_STALE}*.json"))


@pytest.mark.anyio
async def test_notifies_when_behind(tmp_path, monkeypatch):
    config = _config(tmp_path, _OLD)

    async def fake_head():
        return _HEAD_SHA, _HEAD_TIME

    monkeypatch.setattr(wf, "latest_head", fake_head)
    await wf.check_whatsmeow_freshness(config)
    files = _stale_files(config)
    assert len(files) == 1
    assert _OLD in files[0].read_text()


@pytest.mark.anyio
async def test_silent_when_on_head(tmp_path, monkeypatch):
    config = _config(tmp_path, _ON_HEAD)

    async def fake_head():
        return _HEAD_SHA, _HEAD_TIME

    monkeypatch.setattr(wf, "latest_head", fake_head)
    await wf.check_whatsmeow_freshness(config)
    assert _stale_files(config) == []


@pytest.mark.anyio
async def test_noop_when_skill_absent(tmp_path, monkeypatch):
    config = _config(tmp_path, None)  # no go.mod -> skill not installed

    async def fake_head():
        raise AssertionError("must not hit the network when the skill is absent")

    monkeypatch.setattr(wf, "latest_head", fake_head)
    await wf.check_whatsmeow_freshness(config)
    assert _stale_files(config) == []


@pytest.mark.anyio
async def test_fails_open_on_network_error(tmp_path, monkeypatch):
    config = _config(tmp_path, _OLD)

    async def fake_head():
        return None  # network/proxy failure

    monkeypatch.setattr(wf, "latest_head", fake_head)
    await wf.check_whatsmeow_freshness(config)
    assert _stale_files(config) == []
