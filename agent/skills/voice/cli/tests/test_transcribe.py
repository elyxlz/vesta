"""The transcribe command: provider first, whisper fallback, transcript-only stdout."""

import functools
import pathlib as pl
import typing as tp

import pytest
from voice import config as vc
from voice import transcribe
from voice.providers import deepgram


def test_prerecorded_transcript_reads_first_alternative() -> None:
    body = {"results": {"channels": [{"alternatives": [{"transcript": "  ciao come stai  "}]}]}}
    assert deepgram._prerecorded_transcript(body) == "ciao come stai"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"results": {"channels": []}},
        {"results": {"channels": [{"alternatives": []}]}},
    ],
)
def test_prerecorded_transcript_empty_when_nothing_recognized(body: dict) -> None:
    assert deepgram._prerecorded_transcript(body) == ""


def test_prerecorded_params_detect_language_when_none_given() -> None:
    params = dict(deepgram._prerecorded_params(None))
    assert params["model"] == deepgram.PRERECORDED_MODEL
    assert params["smart_format"] == "true"
    assert params["language"] == "multi"


def test_prerecorded_params_pin_the_given_language() -> None:
    assert dict(deepgram._prerecorded_params("it"))["language"] == "it"


@pytest.mark.parametrize(
    "text",
    ["", "   ", "\t\n", "[Musica]", "[BLANK_AUDIO]", "[Musik]", "[tk]", "[Musica]  ", "[BLANK_AUDIO][BLANK_AUDIO]", "[Musica] [Musik]"],
)
def test_whisper_tag_only_output_is_silence(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    _fake_whisper(tmp_path, monkeypatch, stdout=text)
    assert transcribe._whisper_transcript(tmp_path / "note.ogg", None) == ""


@pytest.mark.parametrize(
    "text",
    ["Ciao, come stai?", "See you at [the pub] later", "[Musica] and then he said go", "uh [tk] hmm actually no", "x"],
)
def test_whisper_real_output_is_kept(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    _fake_whisper(tmp_path, monkeypatch, stdout=text)
    assert transcribe._whisper_transcript(tmp_path / "note.ogg", None) == text


class _FakeStt:
    name = "deepgram"

    def __init__(self, transcript: str | None, error: Exception | None = None) -> None:
        self._transcript = transcript
        self._error = error
        self.seen: dict[str, tp.Any] = {}

    async def transcribe_file(self, audio_path: pl.Path, creds: dict[str, str], language: str | None) -> str:
        self.seen = {"audio_path": audio_path, "creds": creds, "language": language}
        if self._error is not None:
            raise self._error
        assert self._transcript is not None
        return self._transcript


def _fake_whisper(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, *, stdout: str = "", exit_code: int = 0, stderr: str = "") -> pl.Path:
    """A stand-in whisper_transcribe.sh that records its arguments and answers as told."""
    (tmp_path / "whisper_stdout").write_text(stdout)
    (tmp_path / "whisper_stderr").write_text(stderr)
    script = tmp_path / "whisper_transcribe.sh"
    script.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/whisper_args"\n'
        f'cat "{tmp_path}/whisper_stderr" >&2\n'
        f'cat "{tmp_path}/whisper_stdout"\n'
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(transcribe, "WHISPER_SCRIPT", script)
    return tmp_path / "whisper_args"


@pytest.fixture
def home(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> pl.Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def audio(tmp_path: pl.Path) -> pl.Path:
    path = tmp_path / "note.ogg"
    path.write_bytes(b"opus")
    return path


def _configure_stt(home: pl.Path, *, enabled: bool = True) -> None:
    vc.set_key(home / ".voice", "stt", "deepgram", "dg-key")
    vc.set_enabled(home / ".voice", "stt", enabled)


def _leave_stt_unset(_home: pl.Path) -> None:
    return None


def test_provider_transcript_is_the_only_stdout(
    home: pl.Path, audio: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure_stt(home)
    fake = _FakeStt("ciao come stai")
    monkeypatch.setattr(transcribe.providers, "get_stt", lambda _name: fake)
    whisper_args = _fake_whisper(home, monkeypatch, stdout="never used")

    code = transcribe.main([str(audio), "--language", "it"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "ciao come stai\n"
    assert captured.err == ""
    assert fake.seen == {"audio_path": audio, "creds": {"api_key": "dg-key"}, "language": "it"}
    assert not whisper_args.exists()


def test_empty_provider_transcript_is_silence_not_a_fallback(
    home: pl.Path, audio: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure_stt(home)
    monkeypatch.setattr(transcribe.providers, "get_stt", lambda _name: _FakeStt(""))
    whisper_args = _fake_whisper(home, monkeypatch, stdout="[BLANK_AUDIO]")

    code = transcribe.main([str(audio)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "\n"
    assert not whisper_args.exists()


@pytest.mark.parametrize(
    ("configure", "provider"),
    [
        (_leave_stt_unset, _FakeStt("unused")),
        (functools.partial(_configure_stt, enabled=False), _FakeStt("unused")),
        (_configure_stt, _FakeStt(None, error=RuntimeError("deepgram returned 500"))),
    ],
    ids=["unset", "disabled", "provider error"],
)
def test_whisper_answers_when_the_provider_cannot(
    home: pl.Path,
    audio: pl.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configure: tp.Callable[[pl.Path], None],
    provider: _FakeStt,
) -> None:
    configure(home)
    monkeypatch.setattr(transcribe.providers, "get_stt", lambda _name: provider)
    whisper_args = _fake_whisper(home, monkeypatch, stdout="hello there")

    code = transcribe.main([str(audio), "--language", "en"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "hello there\n"
    assert captured.err == ""
    assert whisper_args.read_text().split("\n")[:3] == [str(audio), "--language", "en"]


def test_both_failing_reports_both_reasons_on_stderr(
    home: pl.Path, audio: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_whisper(home, monkeypatch, exit_code=1, stderr="Error: whisper-cli not found at /usr/local/bin/whisper-cli\nRun the setup first.")

    code = transcribe.main([str(audio)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert (
        captured.err
        == '{"error": "STT not configured; whisper: Error: whisper-cli not found at /usr/local/bin/whisper-cli Run the setup first."}\n'
    )


def test_missing_whisper_script_is_named(
    home: pl.Path, audio: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(transcribe, "WHISPER_SCRIPT", home / "nowhere.sh")

    code = transcribe.main([str(audio)])

    captured = capsys.readouterr()
    assert code == 1
    assert "whisper skill script missing" in captured.err


def test_missing_audio_file_fails_before_any_backend(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = transcribe.main([str(home / "absent.ogg")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "file not found" in captured.err
