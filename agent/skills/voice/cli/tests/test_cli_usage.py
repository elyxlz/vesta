import pytest

import voice.voice_keys as voice_keys


def test_bare_invocation_prints_usage_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = voice_keys.main([])

    assert code == 0
    out = capsys.readouterr().out
    assert "daemon" in out


def test_help_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        voice_keys.main(["--help"])

    assert exc.value.code == 0


def test_daemon_subcommands_are_registered(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        voice_keys.main(["daemon", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for want in ("start", "stop", "restart", "status"):
        assert want in out
