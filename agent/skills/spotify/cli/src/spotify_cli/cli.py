"""Spotify CLI entry point."""

import argparse
import json
import sys

from . import auth, organize, playback, playlists, search
from .config import Config


def _run_watch(args, config: Config) -> dict:
    if args.init:
        return organize.init_watch(config)
    # Daemon mode — runs forever; handle KeyboardInterrupt for clean exit
    try:
        organize.watch_daemon(config, interval=args.interval)
    except KeyboardInterrupt:
        organize._log("Watch daemon stopped by user.")
        sys.exit(0)
    return {}  # unreachable


def _add_auth_parsers(subparsers) -> None:
    auth_parser = subparsers.add_parser("auth", help="Authentication")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    setup_p = auth_sub.add_parser("setup", help="Save Spotify app credentials")
    setup_p.add_argument("--client-id", required=True)
    setup_p.add_argument("--client-secret", required=True)
    setup_p.set_defaults(func=lambda args, config: auth.save_credentials(config, args.client_id, args.client_secret))

    auth_sub.add_parser("login", help="Start OAuth login flow").set_defaults(func=lambda _args, config: auth.login(config))

    cb_p = auth_sub.add_parser("callback", help="Handle OAuth callback")
    cb_p.add_argument("--url", required=True, help="The full redirect URL after authorization")
    cb_p.set_defaults(func=lambda args, config: auth.handle_callback(config, args.url))

    auth_sub.add_parser("status", help="Check auth status").set_defaults(func=lambda _args, config: auth.status(config))


def _add_playlist_parsers(subparsers) -> None:
    pl_parser = subparsers.add_parser("playlists", help="Playlist management")
    pl_sub = pl_parser.add_subparsers(dest="playlist_command", required=True)

    list_p = pl_sub.add_parser("list", help="List your playlists")
    list_p.add_argument("--limit", type=int, default=50)
    list_p.set_defaults(func=lambda args, config: playlists.list_playlists(config, limit=args.limit))

    show_p = pl_sub.add_parser("show", help="Show playlist tracks")
    show_p.add_argument("--id", required=True, help="Playlist ID or URI")
    show_p.add_argument("--limit", type=int, default=50)
    show_p.set_defaults(func=lambda args, config: playlists.show_playlist(config, args.id, limit=args.limit))

    create_p = pl_sub.add_parser("create", help="Create a playlist")
    create_p.add_argument("--name", required=True)
    create_p.add_argument("--description", default="")
    create_p.add_argument("--private", action="store_true")
    create_p.set_defaults(
        func=lambda args, config: playlists.create_playlist(config, name=args.name, description=args.description or "", public=not args.private)
    )

    add_p = pl_sub.add_parser("add", help="Add tracks to playlist")
    add_p.add_argument("--id", required=True, help="Playlist ID")
    add_p.add_argument("--uris", required=True, help="Comma-separated track URIs/IDs")
    add_p.set_defaults(func=lambda args, config: playlists.add_tracks(config, args.id, [u.strip() for u in args.uris.split(",")]))

    rm_p = pl_sub.add_parser("remove", help="Remove tracks from playlist")
    rm_p.add_argument("--id", required=True, help="Playlist ID")
    rm_p.add_argument("--uris", required=True, help="Comma-separated track URIs/IDs")
    rm_p.set_defaults(func=lambda args, config: playlists.remove_tracks(config, args.id, [u.strip() for u in args.uris.split(",")]))

    liked_p = pl_sub.add_parser("liked", help="Show liked/saved songs")
    liked_p.add_argument("--limit", type=int, default=50)
    liked_p.add_argument("--offset", type=int, default=0)
    liked_p.set_defaults(func=lambda args, config: playlists.liked_songs(config, limit=args.limit, offset=args.offset))


def _add_search_parser(subparsers) -> None:
    search_p = subparsers.add_parser("search", help="Search Spotify")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--type", default="track", help="track, album, artist, or comma-separated")
    search_p.add_argument("--limit", type=int, default=10)
    search_p.set_defaults(func=lambda args, config: search.search(config, query=args.query, search_type=args.type, limit=args.limit))


def _add_organize_parsers(subparsers) -> None:
    org_parser = subparsers.add_parser("organize", help="Library organization")
    org_sub = org_parser.add_subparsers(dest="organize_command", required=True)

    sync_p = org_sub.add_parser("sync", help="Like all tracks from own playlists")
    sync_p.add_argument("--dry-run", action="store_true", help="Preview without changes")
    sync_p.set_defaults(func=lambda args, config: organize.sync_likes(config, dry_run=args.dry_run))

    sort_p = org_sub.add_parser("sort", help="Sort orphan liked songs into playlists by genre")
    sort_p.add_argument("--dry-run", action="store_true", help="Preview without changes")
    sort_p.set_defaults(func=lambda args, config: organize.sort_orphans(config, dry_run=args.dry_run))

    full_p = org_sub.add_parser("full", help="Run sync + sort together")
    full_p.add_argument("--dry-run", action="store_true", help="Preview without changes")
    full_p.set_defaults(func=lambda args, config: organize.full_organize(config, dry_run=args.dry_run))

    cfg_p = org_sub.add_parser("config", help="Show or initialize organize config")
    cfg_p.add_argument("--init", action="store_true", help="Reset config to defaults")
    cfg_p.set_defaults(func=lambda args, config: organize.init_config(config) if args.init else organize.show_config(config))

    watch_p = org_sub.add_parser("watch", help="Daemon: auto-sort newly liked songs into playlists")
    watch_p.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Poll interval in seconds (default: 60)",
    )
    watch_p.add_argument(
        "--init",
        action="store_true",
        help="Initialize state file with current liked songs without processing",
    )
    watch_p.set_defaults(func=_run_watch)


def _add_playback_parsers(subparsers) -> None:
    pb_parser = subparsers.add_parser("playback", help="Playback control (Premium)")
    pb_sub = pb_parser.add_subparsers(dest="playback_command", required=True)

    pb_sub.add_parser("current", help="Current playback state").set_defaults(func=lambda _args, config: playback.current(config))
    pb_sub.add_parser("devices", help="List available devices").set_defaults(func=lambda _args, config: playback.devices(config))

    play_p = pb_sub.add_parser("play", help="Play/resume")
    play_p.add_argument("--uri", help="Track URI to play")
    play_p.add_argument("--context", help="Context URI (playlist/album)")
    play_p.add_argument("--device", help="Device ID")
    play_p.set_defaults(func=lambda args, config: playback.play(config, uri=args.uri, context_uri=args.context, device_id=args.device))

    pb_sub.add_parser("pause", help="Pause playback").set_defaults(func=lambda _args, config: playback.pause(config))

    skip_p = pb_sub.add_parser("skip", help="Skip track")
    skip_p.add_argument("--direction", default="next", choices=["next", "previous"])
    skip_p.set_defaults(func=lambda args, config: playback.skip(config, direction=args.direction))

    pb_sub.add_parser("previous", help="Previous track").set_defaults(func=lambda _args, config: playback.skip(config, direction="previous"))

    vol_p = pb_sub.add_parser("volume", help="Set volume")
    vol_p.add_argument("level", type=int, help="Volume 0-100")
    vol_p.add_argument("--device", help="Device ID")
    vol_p.set_defaults(func=lambda args, config: playback.volume(config, level=args.level, device_id=args.device))

    q_p = pb_sub.add_parser("queue", help="Add track to queue")
    q_p.add_argument("--uri", required=True, help="Track URI")
    q_p.add_argument("--device", help="Device ID")
    q_p.set_defaults(func=lambda args, config: playback.queue_add(config, uri=args.uri, device_id=args.device))

    shuf_p = pb_sub.add_parser("shuffle", help="Set shuffle")
    shuf_p.add_argument("state", help="on/off")
    shuf_p.set_defaults(func=lambda args, config: playback.shuffle(config, state=args.state.lower() in ("on", "true", "1")))

    rep_p = pb_sub.add_parser("repeat", help="Set repeat mode")
    rep_p.add_argument("state", choices=["off", "track", "context"])
    rep_p.set_defaults(func=lambda args, config: playback.repeat(config, state=args.state))

    xfer_p = pb_sub.add_parser("transfer", help="Transfer playback to device")
    xfer_p.add_argument("--device-id", required=True)
    xfer_p.add_argument("--play", action="store_true", help="Start playing on transfer")
    xfer_p.set_defaults(func=lambda args, config: playback.transfer(config, device_id=args.device_id, force_play=args.play))


def main():
    parser = argparse.ArgumentParser(prog="spotify", description="Spotify CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_auth_parsers(subparsers)
    _add_playlist_parsers(subparsers)
    _add_search_parser(subparsers)
    _add_organize_parsers(subparsers)
    _add_playback_parsers(subparsers)

    args = parser.parse_args()

    config = Config()

    try:
        result = args.func(args, config)
    except Exception as e:
        result = {"error": type(e).__name__, "message": str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
