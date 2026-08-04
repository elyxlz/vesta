import subprocess

import pytest
from torrents_cli import qb

TORRENT = {
    "name": "A.Quiet.Place.2018.1080p",
    "hash": "abc123def456",
    "state": "downloading",
    "progress": 0.5,
    "size": 2_000_000_000,
    "eta": 600,
    "dlspeed": 1_000_000,
    "ratio": 0.1,
    "num_seeds": 3,
    "num_leechs": 1,
    "save_path": "/media/library/Movies",
    "content_path": "/media/library/Movies/A.Quiet.Place.2018.1080p",
    "ratio_limit": -2,
    "seeding_time_limit": -2,
}


# --- name matching ---


@pytest.mark.parametrize(
    ("needle", "name", "hit"),
    [
        ("quiet place", "A.Quiet.Place.2018.1080p", True),
        ("quiet place 2018", "A.Quiet.Place.2018.1080p", True),
        ("quiet_place", "A Quiet Place 2018", True),
        ("loud place", "A.Quiet.Place.2018.1080p", False),
    ],
)
def test_matching_folds_separators_and_multiple_words(needle, name, hit):
    assert qb.matches(needle, name) is hit


# --- endpoint compatibility ---


def test_pause_uses_current_stop_endpoint(fake_qb, capsys):
    fake_qb.torrents = [TORRENT]
    qb.main(["pause", "quiet", "place"])
    assert "torrents/stop" in fake_qb.paths()
    assert "torrents/pause" not in fake_qb.paths()
    assert "paused 1" in capsys.readouterr().out


def test_pause_falls_back_to_legacy_endpoint_on_404(fake_qb, capsys):
    fake_qb.torrents = [TORRENT]
    fake_qb.removed_endpoints = {"torrents/stop"}
    qb.main(["pause", "quiet", "place"])
    paths = fake_qb.paths()
    assert paths.index("torrents/stop") < paths.index("torrents/pause"), "legacy endpoint must be the fallback, not the first try"
    assert "paused 1" in capsys.readouterr().out


def test_resume_falls_back_to_legacy_endpoint_on_404(fake_qb):
    fake_qb.torrents = [TORRENT]
    fake_qb.removed_endpoints = {"torrents/start"}
    qb.main(["resume", "abc123"])
    assert "torrents/resume" in fake_qb.paths()


# --- refusals exit 1 and act on nothing ---


def test_delete_refuses_without_yes(fake_qb):
    fake_qb.torrents = [TORRENT]
    with pytest.raises(SystemExit) as exc:
        qb.main(["delete", "quiet", "place"])
    assert exc.value.code != 0
    assert "torrents/delete" not in fake_qb.paths()


def test_limits_with_no_name_refuses_without_yes(fake_qb):
    fake_qb.torrents = [TORRENT]
    with pytest.raises(SystemExit) as exc:
        qb.main(["limits"])
    assert exc.value.code != 0
    assert "torrents/setShareLimits" not in fake_qb.paths()


def test_rule_refuses_without_yes(fake_qb):
    fake_qb.torrents = [TORRENT]
    with pytest.raises(SystemExit) as exc:
        qb.main(["rule", "--ratio", "1"])
    assert exc.value.code != 0
    assert "app/setPreferences" not in fake_qb.paths()


def test_rule_with_yes_sets_pause_never_delete(fake_qb, capsys):
    fake_qb.torrents = [TORRENT]
    qb.main(["rule", "--ratio", "1", "--yes"])
    fields = next(fields for _, path, fields in fake_qb.requests if path == "app/setPreferences")
    assert '"max_ratio_act": 0' in fields["json"]
    assert "VERIFIED" in capsys.readouterr().out


# --- file add, both transports ---


def test_add_file_over_http_uploads_multipart(fake_qb, tmp_path, capsys):
    torrent_file = tmp_path / "movie.torrent"
    torrent_file.write_bytes(b"d8:announce3:url4:infod4:name5:moviee" + b"e")
    qb.main(["add", str(torrent_file), "--path", "/media/library/Movies"])
    body = next(b for b in fake_qb.raw_bodies if b"movie.torrent" in b)
    assert b"d8:announce" in body
    assert b"/media/library/Movies" in body
    assert "Ok." in capsys.readouterr().out


def test_add_file_over_ssh_streams_bytes_to_server(monkeypatch, tmp_path, capsys):
    """With MEDIA_SERVER_HOST set, a .torrent file rides ssh stdin into curl on the server,
    never a direct HTTP call from the box."""
    torrent_file = tmp_path / "movie.torrent"
    torrent_file.write_bytes(b"d8:announce3:urle")
    monkeypatch.setenv("MEDIA_SERVER_HOST", "mediabox")
    calls: list[tuple[list[str], bytes | None]] = []

    def fake_run(argv, **kwargs):
        stdin = kwargs["input"] if "input" in kwargs else None
        calls.append((argv, stdin))
        return subprocess.CompletedProcess(argv, 0, stdout=b"Ok.\n200", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    qb.main(["add", str(torrent_file), "--path", "/media/library/Movies"])
    argv, stdin = calls[0]
    assert argv[0] == "ssh" and "mediabox" in argv[-2]
    assert "torrents=@-" in argv[-1] and "localhost" in argv[-1]
    assert stdin == torrent_file.read_bytes()
    assert "Ok." in capsys.readouterr().out


# --- SSH-only commands say so plainly ---


def test_ls_library_without_media_server_errors_clearly(fake_qb):
    with pytest.raises(SystemExit) as exc:
        qb.main(["ls-library"])
    assert "MEDIA_SERVER_HOST" in str(exc.value.code)


def test_unreachable_server_errors_clearly(monkeypatch):
    monkeypatch.delenv("MEDIA_SERVER_HOST", raising=False)
    monkeypatch.setenv("QB_HOST", "127.0.0.1")
    monkeypatch.setenv("QB_PORT", "1")
    with pytest.raises(SystemExit) as exc:
        qb.main(["ls"])
    assert "cannot reach qBittorrent" in str(exc.value.code)


# --- status filtering ---


def test_status_hides_stopped_complete_without_all(fake_qb, capsys):
    fake_qb.torrents = [TORRENT, {**TORRENT, "name": "Done.Movie", "hash": "ffff", "state": "stoppedUP"}]
    qb.main(["status"])
    out = capsys.readouterr().out
    assert "A.Quiet.Place" in out and "Done.Movie" not in out
    qb.main(["status", "--all"])
    assert "Done.Movie" in capsys.readouterr().out


def test_add_infohash_becomes_magnet(fake_qb):
    qb.main(["add", "abc123def456"])
    fields = next(fields for _, path, fields in fake_qb.requests if path == "torrents/add")
    assert fields["urls"].startswith("magnet:?xt=urn:btih:abc123def456")
