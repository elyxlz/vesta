"""One-shot transcription: Deepgram prerecorded parsing + the voice-keys transcribe command."""

import pathlib as pl
import typing as tp

import pytest
from voice import config as vc
from voice import voice_keys
from voice.providers import deepgram


def test_prerecorded_transcript_reads_first_alternative() -> None:
    body = {"results": {"channels": [{"alternatives": [{"transcript": "  ciao come stai  "}]}]}}
    assert deepgram._prerecorded_transcript(body) == "ciao come stai"


def test_prerecorded_transcript_empty_when_no_channels() -> None:
    assert deepgram._prerecorded_transcript({"results": {"channels": []}}) == ""
    assert deepgram._prerecorded_transcript({}) == ""


def test_prerecorded_transcript_empty_when_no_alternatives() -> None:
    assert deepgram._prerecorded_transcript({"results": {"channels": [{"alternatives": []}]}}) == ""


def test_prerecorded_language_prefers_multi() -> None:
    assert deepgram._prerecorded_language({"multi_language": True, "language": "it"}) == "multi"


def test_prerecorded_language_reads_explicit_code() -> None:
    assert deepgram._prerecorded_language({"language": "it"}) == "it"


def test_prerecorded_language_none_for_auto_or_absent() -> None:
    assert deepgram._prerecorded_language({"language": "auto"}) is None
    assert deepgram._prerecorded_language({}) is None


def test_prerecorded_params_always_carry_model_and_smart_format() -> None:
    params = dict(deepgram._prerecorded_params({}))
    assert params["model"] == deepgram.PRERECORDED_MODEL
    assert params["smart_format"] == "true"
    assert "language" not in params


def test_prerecorded_params_carry_language_when_set() -> None:
    params = dict(deepgram._prerecorded_params({"language": "it"}))
    assert params["language"] == "it"


class _FakeStt:
    name = "deepgram"

    def __init__(self, transcript: str | None, error: Exception | None = None) -> None:
        self._transcript = transcript
        self._error = error
        self.seen: dict[str, tp.Any] = {}

    async def transcribe_file(self, audio_path: pl.Path, creds: dict[str, str], stt_domain: dict) -> str:
        self.seen = {"audio_path": audio_path, "creds": creds, "stt_domain": stt_domain}
        if self._error is not None:
            raise self._error
        assert self._transcript is not None
        return self._transcript


def _configure_stt(tmp_path: pl.Path, *, enabled: bool = True) -> None:
    vc.set_key(tmp_path, "stt", "deepgram", "dg-key")
    vc.set_enabled(tmp_path, "stt", enabled)


def test_transcribe_prints_only_transcript(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_stt(tmp_path)
    fake = _FakeStt("ciao come stai")
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(voice_keys.providers, "get_stt", lambda _name: fake)
    audio = tmp_path / "note.ogg"
    audio.write_bytes(b"opus")

    code = voice_keys.main(["transcribe", str(audio)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "ciao come stai"
    assert captured.err == ""
    assert fake.seen["creds"] == {"api_key": "dg-key"}
    assert fake.seen["audio_path"] == audio


def test_transcribe_not_configured_errors_on_stderr(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)

    code = voice_keys.main(["transcribe", str(tmp_path / "note.ogg")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "error" in captured.err
    assert "not configured" in captured.err


def test_transcribe_disabled_errors(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_stt(tmp_path, enabled=False)
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)

    code = voice_keys.main(["transcribe", str(tmp_path / "note.ogg")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "disabled" in captured.err


def test_transcribe_provider_error_errors(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_stt(tmp_path)
    fake = _FakeStt(None, error=RuntimeError("deepgram returned 500"))
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(voice_keys.providers, "get_stt", lambda _name: fake)
    audio = tmp_path / "note.ogg"
    audio.write_bytes(b"opus")

    code = voice_keys.main(["transcribe", str(audio)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "deepgram returned 500" in captured.err


def test_transcribe_empty_transcript_is_clean_success(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure_stt(tmp_path)
    fake = _FakeStt("")
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(voice_keys.providers, "get_stt", lambda _name: fake)
    audio = tmp_path / "note.ogg"
    audio.write_bytes(b"opus")

    code = voice_keys.main(["transcribe", str(audio)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == ""
    assert captured.err == ""
