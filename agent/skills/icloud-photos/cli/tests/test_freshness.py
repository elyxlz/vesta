"""Tests for the stale-dependency guard shared by scraper skills."""

import json

import pytest
from icloud_cli import _freshness


class _FakeResp:
    def __init__(self, latest: str) -> None:
        self._body = json.dumps({"info": {"version": latest}}).encode()

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _patch(monkeypatch, installed: str, latest: str | None, *, offline: bool = False) -> None:
    monkeypatch.setattr(_freshness, "version", lambda _pkg: installed)
    if offline:

        def _boom(*_a, **_k):
            raise OSError("no network")

        monkeypatch.setattr(_freshness.urllib.request, "urlopen", _boom)
    else:
        monkeypatch.setattr(_freshness.urllib.request, "urlopen", lambda *_a, **_k: _FakeResp(latest))


def test_stale_exits_nonzero_with_error(monkeypatch, capsys):
    _patch(monkeypatch, installed="2.5.0", latest="2.6.0")
    with pytest.raises(SystemExit) as exc:
        _freshness.require_latest("pyicloud")
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().err)
    assert "2.5.0" in err["error"] and "2.6.0" in err["error"]


def test_current_proceeds(monkeypatch):
    _patch(monkeypatch, installed="2.6.0", latest="2.6.0")
    _freshness.require_latest("pyicloud")  # no SystemExit


def test_newer_local_build_proceeds(monkeypatch):
    _patch(monkeypatch, installed="2.7.0", latest="2.6.0")
    _freshness.require_latest("pyicloud")  # a local build ahead of PyPI is fine


def test_offline_warns_and_proceeds(monkeypatch, capsys):
    _patch(monkeypatch, installed="2.5.0", latest=None, offline=True)
    _freshness.require_latest("pyicloud")  # no SystemExit
    assert "could not verify" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("installed", "latest", "stale"),
    [
        ("0.8.4", "0.9.0", True),
        ("0.9.0", "0.9.0", False),
        ("0.10.0", "0.9.0", False),
        ("0.9.0rc1", "0.9.0", False),
    ],
)
def test_release_ordering(monkeypatch, installed, latest, stale):
    _patch(monkeypatch, installed=installed, latest=latest)
    if stale:
        with pytest.raises(SystemExit):
            _freshness.require_latest("pyicloud")
    else:
        _freshness.require_latest("pyicloud")
