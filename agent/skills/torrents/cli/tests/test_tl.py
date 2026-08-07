import json
import subprocess

import pytest
from torrents_cli import tl


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(tl, "CRED", tmp_path / "cred")
    monkeypatch.setattr(tl, "JAR", tmp_path / "cookies")
    return tmp_path


def test_login_skipped_while_cookie_still_valid(monkeypatch, home):
    (home / "cookies").write_text("jar")
    fetched: list[str] = []

    def fake_curl(url, out=None, post=None):
        fetched.append(url)
        return '{"torrentList": []}'

    monkeypatch.setattr(tl, "curl", fake_curl)
    tl.login()
    assert all("/user/account/login/" not in url for url in fetched)


def test_missing_vpn_command_fails_clearly(monkeypatch, home):
    (home / "cookies").write_text("jar")
    tl.proxy_url.cache_clear()

    def fake_run(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exc:
        tl.main(["search", "film"])
    assert "VPN proxy" in str(exc.value.code)


def test_login_fails_clearly_without_credentials(monkeypatch, home):
    monkeypatch.setattr(tl, "curl", lambda url, out=None, post=None: "not json")
    with pytest.raises(SystemExit) as exc:
        tl.login()
    assert "credentials" in str(exc.value.code)


def test_get_rejects_non_bencode_and_removes_the_file(monkeypatch, home, capsys):
    (home / "cookies").write_text("jar")

    def fake_curl(url, out=None, post=None):
        if out is not None:
            out.write_bytes(b"<html>blocked</html>" * 100)
        return '{"torrentList": []}'

    monkeypatch.setattr(tl, "curl", fake_curl)
    out_dir = home / "out"
    tl.main(["get", "12345", "--out", str(out_dir)])
    assert "not a valid torrent" in capsys.readouterr().out
    assert not (out_dir / "12345.torrent").exists()


def test_get_keeps_valid_torrents(monkeypatch, home, capsys):
    (home / "cookies").write_text("jar")

    def fake_curl(url, out=None, post=None):
        if out is not None:
            out.write_bytes(b"d8:announce33:https://tracker.example/announce" + b"x" * 2000 + b"e")
        return '{"torrentList": []}'

    monkeypatch.setattr(tl, "curl", fake_curl)
    out_dir = home / "out"
    tl.main(["get", "12345", "--out", str(out_dir)])
    assert (out_dir / "12345.torrent").exists()
    assert "12345.torrent" in capsys.readouterr().out


def test_search_filters_and_sorts_by_seeders(monkeypatch, home, capsys):
    (home / "cookies").write_text("jar")
    rows = [
        {"fid": "1", "name": "Film.2160p", "size": 20e9, "seeders": 5},
        {"fid": "2", "name": "Film.1080p", "size": 8e9, "seeders": 300},
        {"fid": "3", "name": "Film.1080p.small", "size": 1e9, "seeders": 50},
    ]

    def fake_curl(url, out=None, post=None):
        return json.dumps({"torrentList": rows})

    monkeypatch.setattr(tl, "curl", fake_curl)
    tl.main(["search", "film", "--1080", "--min-gb", "2"])
    out = capsys.readouterr().out
    assert "Film.1080p" in out and "Film.2160p" not in out and "small" not in out
