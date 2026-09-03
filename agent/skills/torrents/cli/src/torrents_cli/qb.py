"""qb - qBittorrent CLI.

Transport is picked by environment (see qbapi): SSH to the media server when MEDIA_SERVER_HOST is
set, direct HTTP to $QB_HOST (default $BOX_HOST) : $QB_PORT otherwise. `ls-library` and `find` are
filesystem operations on the media server and require the SSH transport.

TorrentLeech is a different service and lives in its own CLI, `tl`. The media library layouts are
documented under integrations/. Apart from `search`, which queries the public apibay index, this
file talks only to qBittorrent.
"""

import argparse
import json
import pathlib as pl
import sys
import typing as tp
import urllib.error
import urllib.parse
import urllib.request

from . import qbapi

APIBAY_TIMEOUT_SECS = 60
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"
ETA_UNKNOWN_SECS = 8640000
STOPPED_COMPLETE_STATES = ("pausedUP", "stoppedUP")  # qBittorrent 4.x and 5.x names
STOPPED_STATES = ("pausedUP", "pausedDL", "stoppedUP", "stoppedDL")


class Torrent(tp.TypedDict, total=False):
    name: str
    hash: str
    state: str
    progress: float
    size: int
    eta: int
    dlspeed: int
    ratio: float
    num_seeds: int
    num_leechs: int
    save_path: str
    content_path: str
    seeding_time: int
    ratio_limit: float
    seeding_time_limit: int


class ServerState(tp.TypedDict):
    free_space_on_disk: int
    dl_info_speed: int
    up_info_speed: int
    write_cache_overload: str
    queued_io_jobs: str
    average_time_queue: int


class SharePrefs(tp.TypedDict, total=False):
    max_ratio: float
    max_seeding_time: int
    max_ratio_act: int


def library_path() -> str:
    return qbapi.env("MEDIA_LIBRARY_PATH", "/media/library")


def torrent_list(server: qbapi.Server, hashes: list[str] | None = None) -> list[Torrent]:
    path = "torrents/info" if hashes is None else "torrents/info?hashes=" + urllib.parse.quote("|".join(hashes))
    return tp.cast(list[Torrent], qbapi.api(server, path))


def join_hashes(torrents: list[Torrent]) -> str:
    return "|".join(t["hash"] for t in torrents)


def norm(text: str) -> str:
    """Fold ., _, - and whitespace so 'quiet place' matches 'A.Quiet.Place'."""
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def matches(needle: str, name: str) -> bool:
    return norm(needle) in norm(name)


def pick(server: qbapi.Server, name: str) -> list[Torrent]:
    hits = [t for t in torrent_list(server) if matches(name, t["name"]) or t["hash"].startswith(name.lower())]
    if not hits:
        sys.exit(f"no torrent matching {name!r}")
    return hits


def human(size: int) -> str:
    return f"{size / 1e9:.1f}GB" if size else "0GB"


def show(torrents: list[Torrent]) -> None:
    for t in sorted(torrents, key=lambda x: -x["progress"]):
        eta = "?" if t["eta"] >= ETA_UNKNOWN_SECS else f"{t['eta'] // 60}min"
        print(
            f"  {t['name'][:44]:44} {t['progress'] * 100:5.1f}% {t['dlspeed'] / 1e6:5.2f}MB/s "
            f"peers {t['num_seeds']:>3} ratio {t['ratio']:5.2f} {t['state']:<12} eta {eta}"
        )
    print(f"  ({len(torrents)} shown)")


def cmd_status(server: qbapi.Server, a: argparse.Namespace) -> None:
    torrents = torrent_list(server)
    if a.name:
        torrents = [t for t in torrents if matches(" ".join(a.name), t["name"])]
    show(torrents if a.all else [t for t in torrents if t["state"] not in STOPPED_COMPLETE_STATES])


def cmd_ls(server: qbapi.Server, a: argparse.Namespace) -> None:
    torrents = torrent_list(server)
    if a.filter:
        torrents = [t for t in torrents if matches(" ".join(a.filter), t["name"])]
    if a.json:
        print(json.dumps(torrents))
    else:
        show(torrents)


def cmd_add(server: qbapi.Server, a: argparse.Namespace) -> None:
    library = library_path()
    movies = qbapi.env("QB_MOVIES", str(pl.PurePosixPath(library) / "Movies"))
    tv = qbapi.env("QB_TV", str(pl.PurePosixPath(library) / "TV"))
    save = a.path or (tv if a.tv else movies)
    for src in a.source:
        path = pl.Path(src)
        if path.is_file():
            result = qbapi.api(server, "torrents/add", {"savepath": save}, file=path)
        else:
            url = src if src.startswith("magnet:") else f"magnet:?xt=urn:btih:{src}"
            result = qbapi.api(server, "torrents/add", {"urls": url, "savepath": save})
        print(f"  {result or 'Ok.'}  -> {save}  {path.name[:50]}")


def cmd_pause(server: qbapi.Server, a: argparse.Namespace) -> None:
    hits = pick(server, " ".join(a.name))
    qbapi.stop_torrents(server, join_hashes(hits))
    print(f"  paused {len(hits)}")


def cmd_resume(server: qbapi.Server, a: argparse.Namespace) -> None:
    hits = pick(server, " ".join(a.name))
    qbapi.start_torrents(server, join_hashes(hits))
    print(f"  resumed {len(hits)}")


def cmd_delete(server: qbapi.Server, a: argparse.Namespace) -> None:
    hits = pick(server, " ".join(a.name))
    print(f"  matched {len(hits)}:")
    for t in hits:
        print(f"    {t['name'][:60]}")
    if not a.yes:
        sys.exit("  refusing without --yes")
    qbapi.api(server, "torrents/delete", {"hashes": join_hashes(hits), "deleteFiles": str(bool(a.files)).lower()})
    print(f"  deleted {len(hits)} (files={'yes' if a.files else 'no'})")


INFO_FIELDS = (
    "hash",
    "state",
    "progress",
    "size",
    "ratio",
    "num_seeds",
    "num_leechs",
    "save_path",
    "content_path",
    "ratio_limit",
    "seeding_time_limit",
)


def cmd_info(server: qbapi.Server, a: argparse.Namespace) -> None:
    for t in pick(server, " ".join(a.name)):
        print(f"  {t['name']}")
        for key in INFO_FIELDS:
            if key in t:
                print(f"    {key:<20} {t[key]}")


def cmd_limits(server: qbapi.Server, a: argparse.Namespace) -> None:
    hits = pick(server, " ".join(a.name)) if a.name else torrent_list(server)
    if not a.name and not a.yes:
        sys.exit(f"  no name given, that would set limits on ALL {len(hits)} torrents; pass --yes")
    hashes = [t["hash"] for t in hits]
    qbapi.api(
        server,
        "torrents/setShareLimits",
        {"hashes": "|".join(hashes), "ratioLimit": str(a.ratio), "seedingTimeLimit": str(a.hours * 60), "inactiveSeedingTimeLimit": "-2"},
    )
    print(f"  set ratio {a.ratio} / {a.hours}h on {len(hits)}, verifying:")
    for t in torrent_list(server, hashes):
        print(f"    {t['name'][:40]:40} ratio_limit={t['ratio_limit']} seed_limit={t['seeding_time_limit']}min")


def cmd_rule(server: qbapi.Server, a: argparse.Namespace) -> None:
    torrents = torrent_list(server)
    live = [t for t in torrents if t["state"] not in STOPPED_STATES]
    hit = [t for t in live if t["ratio"] >= a.ratio or ("seeding_time" in t and t["seeding_time"] >= a.hours * 3600)]
    print(f"  blast radius: {len(torrents)} torrents, {len(live)} live, {len(hit)} would pause now")
    for t in hit[:8]:
        print(f"    {t['state']:<12} ratio {t['ratio']:5.2f}  {t['name'][:44]}")
    if not a.yes:
        sys.exit("  refusing without --yes")
    settings = {
        "max_ratio_enabled": True,
        "max_ratio": a.ratio,
        "max_ratio_act": 0,
        "max_seeding_time_enabled": True,
        "max_seeding_time": a.hours * 60,
    }
    qbapi.api(server, "app/setPreferences", {"json": json.dumps(settings)})
    prefs = tp.cast(SharePrefs, qbapi.api(server, "app/preferences"))
    print(f"  VERIFIED ratio={prefs['max_ratio']} time={prefs['max_seeding_time']}min act={prefs['max_ratio_act']} (0=pause, files kept)")


def server_state(server: qbapi.Server) -> ServerState:
    return tp.cast(dict[str, ServerState], qbapi.api(server, "sync/maindata"))["server_state"]


def cmd_health(server: qbapi.Server, _a: argparse.Namespace) -> None:
    s = server_state(server)
    print(f"  free space  : {human(s['free_space_on_disk'])}")
    print(f"  dl / ul     : {s['dl_info_speed'] / 1e6:.2f} / {s['up_info_speed'] / 1e6:.2f} MB/s")
    print(f"  write cache : {s['write_cache_overload']}%  queued io: {s['queued_io_jobs']}")
    print(f"  avg queue   : {s['average_time_queue']} ms")
    print("  NOTE: peers connected + zero throughput + overload near 100% = DISK, not network.")


def cmd_disk(server: qbapi.Server, _a: argparse.Namespace) -> None:
    if server.ssh_host:
        print(qbapi.ssh_text(server, ["df", "-h", library_path()]).rstrip())
    else:
        print(f"  free on qBittorrent's disk: {human(server_state(server)['free_space_on_disk'])}")


class SearchHit(tp.NamedTuple):
    seeders: int
    size: int
    name: str
    info_hash: str


def cmd_search(_server: qbapi.Server, a: argparse.Namespace) -> None:
    query = " ".join(a.query)
    request = urllib.request.Request("https://apibay.org/q.php?q=" + urllib.parse.quote(query), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=APIBAY_TIMEOUT_SECS) as response:
            raw = response.read().decode(errors="replace")
    except urllib.error.URLError as error:
        sys.exit(f"apibay unreachable: {error.reason}")
    results = tp.cast(list[dict[str, str]], json.loads(raw or "[]"))
    rows = [SearchHit(int(r["seeders"]), int(r["size"]), r["name"], r["info_hash"]) for r in results if r["id"] != "0"]
    if a.min_gb:
        rows = [r for r in rows if r.size >= a.min_gb * 1e9]
    if a.max_gb:
        rows = [r for r in rows if r.size <= a.max_gb * 1e9]
    if a.p1080:
        rows = [r for r in rows if "2160" not in r.name]
    rows.sort(key=lambda r: -r.seeders)
    for hit in rows[: a.limit]:
        print(f"  {hit.seeders:>4}s {human(hit.size):>7}  {hit.info_hash}  {hit.name[:58]}")
    print(f"  ({len(rows)} matches; public trackers. For the private tracker see `tl search`.)")


def cmd_ls_library(server: qbapi.Server, a: argparse.Namespace) -> None:
    print(qbapi.ssh_text(server, ["ls", "-la", str(pl.PurePosixPath(library_path()) / (a.subpath or ""))]).rstrip())


def cmd_find(server: qbapi.Server, a: argparse.Namespace) -> None:
    print(qbapi.ssh_text(server, ["find", library_path(), "-iname", f"*{a.keyword}*"]).rstrip())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="active torrents")
    s.add_argument("name", nargs="*")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("ls", help="list all torrents, optionally filtered")
    s.add_argument("filter", nargs="*")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_ls)

    s = sub.add_parser("add", help="add magnet, info-hash or .torrent file")
    s.add_argument("source", nargs="+")
    s.add_argument("--path")
    s.add_argument("--tv", action="store_true")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("pause")
    s.add_argument("name", nargs="+")
    s.set_defaults(func=cmd_pause)

    s = sub.add_parser("resume")
    s.add_argument("name", nargs="+")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("delete", help="delete by name or hash prefix")
    s.add_argument("name", nargs="+")
    s.add_argument("--files", action="store_true")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("info")
    s.add_argument("name", nargs="+")
    s.set_defaults(func=cmd_info)

    _add_maintenance_commands(sub)
    return p


def _add_maintenance_commands(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    s = sub.add_parser("limits", help="per-torrent share limits")
    s.add_argument("name", nargs="*")
    s.add_argument("--ratio", type=float, default=1.0)
    s.add_argument("--hours", type=int, default=192)
    s.add_argument("--yes", action="store_true", help="required when no name given")
    s.set_defaults(func=cmd_limits)

    s = sub.add_parser("rule", help="GLOBAL share rule for every torrent")
    s.add_argument("--ratio", type=float, default=1.0)
    s.add_argument("--hours", type=int, default=192)
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_rule)

    s = sub.add_parser("health", help="disk space + write-cache/io stats")
    s.set_defaults(func=cmd_health)

    s = sub.add_parser("disk", help="free space")
    s.set_defaults(func=cmd_disk)

    s = sub.add_parser("search", help="search public trackers")
    s.add_argument("query", nargs="+")
    s.add_argument("--min-gb", type=float)
    s.add_argument("--max-gb", type=float)
    s.add_argument("--1080", dest="p1080", action="store_true")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("ls-library", help="list the media library (needs MEDIA_SERVER_HOST)")
    s.add_argument("subpath", nargs="?")
    s.set_defaults(func=cmd_ls_library)

    s = sub.add_parser("find", help="find files in the library (needs MEDIA_SERVER_HOST)")
    s.add_argument("keyword")
    s.set_defaults(func=cmd_find)


def main(argv: list[str] | None = None) -> None:
    a = build_parser().parse_args(argv)
    try:
        a.func(qbapi.server_from_env(), a)
    except qbapi.ApiError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
