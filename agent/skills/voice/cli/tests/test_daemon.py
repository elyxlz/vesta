import pathlib as pl

import pytest
import voice.config as vc
from voice import daemon

LIVE_LS = "There are screens on:\n\t12345.voice\t(Detached)\n1 Socket in /run/screen/S-root.\n"
DEAD_LS = "There are screens on:\n\t12345.voice\t(Dead ???)\nRemove dead screens with 'screen -wipe'.\n"
NONE_LS = "No Sockets found in /run/screen/S-root.\n"
COLLIDING_LS = "There are screens on:\n\t12345.voice-other\t(Detached)\n1 Socket in /run/screen/S-root.\n"


@pytest.mark.parametrize(
    "screen_ls,want",
    [
        (LIVE_LS, True),
        (DEAD_LS, False),
        (NONE_LS, False),
        (COLLIDING_LS, False),
    ],
)
def test_screen_output_has_live_session(screen_ls: str, want: bool) -> None:
    assert daemon.screen_output_has_live_session(screen_ls, "voice") == want


def test_auth_status_reports_none_when_unconfigured(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "data_dir", lambda: tmp_path)
    assert daemon._auth_status() == {"stt": None, "tts": None}


def test_auth_status_reports_provider_and_enabled(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "data_dir", lambda: tmp_path)
    vc.set_key(tmp_path, "stt", "deepgram", "k")
    vc.set_enabled(tmp_path, "tts", True)
    vc.set_key(tmp_path, "tts", "elevenlabs", "k2")

    auth = daemon._auth_status()

    assert auth["stt"] == {"provider": "deepgram", "enabled": True}
    assert auth["tts"] == {"provider": "elevenlabs", "enabled": True}


def test_start_is_idempotent_when_port_already_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    claims: list[bool] = []
    monkeypatch.setattr(daemon, "resolve_port", lambda *, claim=False: claims.append(claim) or 4242)
    monkeypatch.setattr(daemon, "_screen_session_live", lambda name: True)
    monkeypatch.setattr(daemon, "port_alive", lambda port: True)

    result = daemon.start()

    assert result == {"status": "already_running", "session": "voice", "port": 4242}
    assert claims == [False]


def test_start_claims_a_new_port_when_cached_port_has_an_unrelated_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims: list[bool] = []
    monkeypatch.setattr(daemon, "resolve_port", lambda *, claim=False: claims.append(claim) or 4242)
    monkeypatch.setattr(daemon, "_screen_session_live", lambda name: False)
    monkeypatch.setattr(daemon, "port_alive", lambda port: True)
    monkeypatch.setattr(daemon.shutil, "which", lambda name: "/usr/bin/voice-server")
    monkeypatch.setattr(
        daemon.subprocess,
        "run",
        lambda *args, **kwargs: daemon.subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    result = daemon.start()

    assert result == {"status": "started", "session": "voice", "port": 4242}
    assert claims == [True]


def test_stop_is_idempotent_when_already_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "resolve_port", lambda *, claim=False: 4242)
    monkeypatch.setattr(daemon, "_screen_session_live", lambda name: False)
    monkeypatch.setattr(daemon, "port_alive", lambda port: True)

    result = daemon.stop()

    assert result == {"status": "already_stopped", "session": "voice", "port": 4242}


def test_status_reports_running_port_and_auth(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "resolve_port", lambda *, claim=False: 4242)
    monkeypatch.setattr(daemon, "_screen_session_live", lambda name: True)
    monkeypatch.setattr(daemon, "port_alive", lambda port: True)
    vc.set_key(tmp_path, "stt", "deepgram", "k")

    result = daemon.status()

    assert result == {
        "running": True,
        "session": "voice",
        "port": 4242,
        "auth": {"stt": {"provider": "deepgram", "enabled": True}, "tts": None},
    }


def test_status_does_not_adopt_an_unrelated_listener(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "resolve_port", lambda *, claim=False: 4242)
    monkeypatch.setattr(daemon, "_screen_session_live", lambda name: False)
    monkeypatch.setattr(daemon, "port_alive", lambda port: True)

    assert daemon.status()["running"] is False
