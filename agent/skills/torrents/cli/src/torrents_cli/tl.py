"""tl - TorrentLeech client: search the tracker and fetch .torrent files.

Deliberately knows nothing about qBittorrent or the media library. It finds torrents and puts
.torrent files on disk; handing them to the client is `qb add <file>`.

TorrentLeech's WEBSITE requires the VPN proxy (direct access is blocked; the `vpn` skill provides
the proxy URL). The torrent traffic itself does not: the download client reaches the tracker on
its own.
"""

import argparse
import functools
import json
import pathlib as pl
import subprocess
import sys
import typing as tp
import urllib.parse

TL = "https://www.torrentleech.org"
CRED = pl.Path("~/.torrentleech_cred").expanduser()
JAR = pl.Path("~/.torrentleech_cookies").expanduser()
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"
CURL_TIMEOUT_SECS = 90
MIN_TORRENT_BYTES = 1000


class Listing(tp.TypedDict):
    fid: str
    name: str
    size: int
    seeders: int


@functools.cache
def proxy_url() -> str:
    try:
        proxy = subprocess.run(["vpn", "proxy-url"], capture_output=True, text=True, check=False).stdout.strip()
    except FileNotFoundError:
        proxy = ""
    if not proxy:
        sys.exit("no VPN proxy available (is the vpn skill active?); the TorrentLeech website is unreachable without it")
    return proxy


def curl(url: str, out: pl.Path | None = None, post: dict[str, str] | None = None) -> str:
    cmd = ["curl", "-s", "--max-time", str(CURL_TIMEOUT_SECS), "-A", USER_AGENT, "-L", "--proxy", proxy_url(), "-c", str(JAR), "-b", str(JAR)]
    for key, value in (post or {}).items():
        cmd += ["--data-urlencode", f"{key}={value}"]
    if out is not None:
        cmd += ["-o", str(out)]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def logged_in() -> bool:
    return curl(f"{TL}/torrents/browse/list/query/test").startswith("{")


def login() -> None:
    """Idempotent: only re-authenticates when the stored cookie has gone stale."""
    if JAR.exists() and logged_in():
        return
    if not CRED.exists():
        sys.exit(f'no credentials at {CRED}: write {{"username": ..., "password": ...}} and chmod 600 it')
    cred = tp.cast(dict[str, str], json.loads(CRED.read_text()))
    curl(f"{TL}/user/account/login/", post={"username": cred["username"], "password": cred["password"]})
    JAR.chmod(0o600)
    if not logged_in():
        sys.exit("TorrentLeech login failed; check ~/.torrentleech_cred")


def query(text: str) -> list[Listing]:
    login()
    url = f"{TL}/torrents/browse/list/query/{urllib.parse.quote(text)}/orderby/seeders/order/desc"
    payload = tp.cast(dict[str, list[Listing]], json.loads(curl(url) or "{}"))
    return payload["torrentList"] if "torrentList" in payload else []


def cmd_search(a: argparse.Namespace) -> None:
    rows = query(" ".join(a.query))
    if a.p1080:
        rows = [r for r in rows if "2160" not in r["name"]]
    if a.uhd:
        rows = [r for r in rows if "2160" in r["name"]]
    if a.min_gb:
        rows = [r for r in rows if r["size"] >= a.min_gb * 1e9]
    if a.max_gb:
        rows = [r for r in rows if r["size"] <= a.max_gb * 1e9]
    rows.sort(key=lambda r: -r["seeders"])
    rows = rows[: a.limit]
    if a.json:
        print(json.dumps(rows))
        return
    for r in rows:
        print(f"  {r['seeders']:>4}s {r['size'] / 1e9:6.1f}GB  {r['fid']:<12} {r['name'][:60]}")
    print(f"  ({len(rows)} shown; fetch with: tl get <fid>)")


def cmd_get(a: argparse.Namespace) -> None:
    """Download .torrent by fid. The filename in TL's download URL is arbitrary
    (/download/<fid>/x.torrent returns the correct file), so no name lookup is needed;
    qBittorrent reads the real name from inside the file."""
    login()
    out_dir = pl.Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for fid in a.fid:
        dest = out_dir / f"{fid}.torrent"
        curl(f"{TL}/download/{fid}/x.torrent", out=dest)
        size = dest.stat().st_size if dest.exists() else 0
        # every bencoded torrent starts with 'd' (a dict); anything else is an error page
        if size < MIN_TORRENT_BYTES or not dest.read_bytes().startswith(b"d"):
            print(f"  {fid}: not a valid torrent ({size}B), skipped")
            dest.unlink(missing_ok=True)
            continue
        print(f"  {dest}  ({size}B)")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search the tracker")
    s.add_argument("query", nargs="+")
    s.add_argument("--1080", dest="p1080", action="store_true", help="exclude 2160p")
    s.add_argument("--uhd", action="store_true", help="only 2160p")
    s.add_argument("--min-gb", type=float)
    s.add_argument("--max-gb", type=float)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("get", help="download .torrent file(s) by fid")
    s.add_argument("fid", nargs="+")
    s.add_argument("--out", default="/tmp/tl")
    s.set_defaults(func=cmd_get)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
