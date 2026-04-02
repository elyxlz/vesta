"""Spotify CLI entry point."""

import argparse
import json
import sys

from .config import Config


def _dispatch_auth(args, config: Config) -> dict:
    from . import auth

    match args.auth_command:
        case "setup":
            return auth.save_credentials(config, args.client_id, args.client_secret)
        case "login":
            return auth.login(config)
        case "callback":
            return auth.handle_callback(config, args.url)
        case "status":
            return auth.status(config)
        case _:
            return {"error": f"unknown auth command: {args.auth_command}"}


def _dispatch_playlists(args, config: Config) -> dict:
    from . import playlists

    match args.playlist_command:
        case "list":
            return playlists.list_playlists(config, limit=args.limit)
        case "show":
            return playlists.show_playlist(config, args.id, limit=args.limit)
        case "create":
            return playlists.create_playlist(
                config,
                name=args.name,
                description=args.description or "",
                public=not args.private,
            )
        case "add":
            uris = [u.strip() for u in args.uris.split(",")]
            return playlists.add_tracks(config, args.id, uris)
        case "remove":
            uris = [u.strip() for u in args.uris.split(",")]
            return playlists.remove_tracks(config, args.id, uris)
        case "liked":
            return playlists.liked_songs(config, limit=args.limit, offset=args.offset)
        case _:
            return {"error": f"unknown playlist command: {args.playlist_command}"}


def _dispatch_search(args, config: Config) -> dict:
    from . import search

    return search.search(
        config,
        query=args.query,
        search_type=args.type,
        limit=args.limit,
    )


def _dispatch_organize(args, config: Config) -> dict:
    from . import organize

    match args.organize_command:
        case "sync":
            return organize.sync_likes(config, dry_run=args.dry_run)
        case "sort":
            return organize.sort_orphans(config, dry_run=args.dry_run)
        case "full":
            return organize.full_organize(config, dry_run=args.dry_run)
        case "config":
            if args.init:
                return organize.init_config(config)
            return organize.show_config(config)
        case "watch":
            if args.init:
                return organize.init_watch(config)
            # Daemon mode — runs forever; handle KeyboardInterrupt for clean exit
            try:
                organize.watch_daemon(config, interval=args.interval)
            except KeyboardInterrupt:
                from . import organize as _org
                _org._log("Watch daemon stopped by user.")
                sys.exit(0)
            return {}  # unreachable
        case _:
            return {"error": f"unknown organize command: {args.organize_command}"}


def _dispatch_playback(args, config: Config) -> dict:
    from . import playback

    match args.playback_command:
        case "current":
            return playback.current(config)
        case "devices":
            return playback.devices(config)
        case "play":
            return playback.play(
                config,
                uri=args.uri,
                context_uri=args.context,
                device_id=args.device,
            )
        case "pause":
            return playback.pause(config)
        case "skip":
            return playback.skip(config, direction=args.direction)
        case "previous":
            return playback.skip(config, direction="previous")
        case "volume":
            return playback.volume(config, level=args.level, device_id=args.device)
        case "queue":
            return playback.queue_add(config, uri=args.uri, device_id=args.device)
        case "shuffle":
            return playback.shuffle(config, state=args.state.lower() in ("on", "true", "1"))
        case "repeat":
            return playback.repeat(config, state=args.state)
        case "transfer":
            return playback.transfer(config, device_id=args.device_id, force_play=args.play)
        case _:
            return {"error": f"unknown playback command: {args.playback_command}"}


def main():
    parser = argparse.ArgumentParser(prog="spotify", description="Spotify CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- auth ---
    auth_parser = subparsers.add_parser("auth", help="Authentication")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    setup_p = auth_sub.add_parser("setup", help="Save Spotify app credentials")
    setup_p.add_argument("--client-id", required=True)
    setup_p.add_argument("--client-secret", required=True)

    auth_sub.add_parser("login", help="Start OAuth login flow")

    cb_p = auth_sub.add_parser("callback", help="Handle OAuth callback")
    cb_p.add_argument("--url", required=True, help="The full redirect URL after authorization")

    auth_sub.add_parser("status", help="Check auth status")

    # --- playlists ---
    pl_parser = subparsers.add_parser("playlists", help="Playlist management")
    pl_sub = pl_parser.add_subparsers(dest="playlist_command", required=True)

    list_p = pl_sub.add_parser("list", help="List your playlists")
    list_p.add_argument("--limit", type=int, default=50)

    show_p = pl_sub.add_parser("show", help="Show playlist tracks")
    show_p.add_argument("--id", required=True, help="Playlist ID or URI")
    show_p.add_argument("--limit", type=int, default=50)

    create_p = pl_sub.add_parser("create", help="Create a playlist")
    create_p.add_argument("--name", required=True)
    create_p.add_argument("--description", default="")
    create_p.add_argument("--private", action="store_true")

    add_p = pl_sub.add_parser("add", help="Add tracks to playlist")
    add_p.add_argument("--id", required=True, help="Playlist ID")
    add_p.add_argument("--uris", required=True, help="Comma-separated track URIs/IDs")

    rm_p = pl_sub.add_parser("remove", help="Remove tracks from playlist")
    rm_p.add_argument("--id", required=True, help="Playlist ID")
    rm_p.add_argument("--uris", required=True, help="Comma-separated track URIs/IDs")

    liked_p = pl_sub.add_parser("liked", help="Show liked/saved songs")
    liked_p.add_argument("--limit", type=int, default=50)
    liked_p.add_argument("--offset", type=int, default=0)

    # --- search ---
    search_p = subparsers.add_parser("search", help="Search Spotify")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--type", default="track", help="track, album, artist, or comma-separated")
    search_p.add_argument("--limit", type=int, default=10)

    # --- organize ---
    org_parser = subparsers.add_parser("organize", help="Library organization")
    org_sub = org_parser.add_subparsers(dest="organize_command", required=True)

    sync_p = org_sub.add_parser("sync", help="Like all tracks from own playlists")
    sync_p.add_argument("--dry-run", action="store_true", help="Preview without changes")

    sort_p = org_sub.add_parser("sort", help="Sort orphan liked songs into playlists by genre")
    sort_p.add_argument("--dry-run", action="store_true", help="Preview without changes")

    full_p = org_sub.add_parser("full", help="Run sync + sort together")
    full_p.add_argument("--dry-run", action="store_true", help="Preview without changes")

    cfg_p = org_sub.add_parser("config", help="Show or initialize organize config")
    cfg_p.add_argument("--init", action="store_true", help="Reset config to defaults")

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

    # --- playback ---
    pb_parser = subparsers.add_parser("playback", help="Playback control (Premium)")
    pb_sub = pb_parser.add_subparsers(dest="playback_command", required=True)

    pb_sub.add_parser("current", help="Current playback state")
    pb_sub.add_parser("devices", help="List available devices")

    play_p = pb_sub.add_parser("play", help="Play/resume")
    play_p.add_argument("--uri", help="Track URI to play")
    play_p.add_argument("--context", help="Context URI (playlist/album)")
    play_p.add_argument("--device", help="Device ID")

    pb_sub.add_parser("pause", help="Pause playback")

    skip_p = pb_sub.add_parser("skip", help="Skip track")
    skip_p.add_argument("--direction", default="next", choices=["next", "previous"])

    pb_sub.add_parser("previous", help="Previous track")

    vol_p = pb_sub.add_parser("volume", help="Set volume")
    vol_p.add_argument("level", type=int, help="Volume 0-100")
    vol_p.add_argument("--device", help="Device ID")

    q_p = pb_sub.add_parser("queue", help="Add track to queue")
    q_p.add_argument("--uri", required=True, help="Track URI")
    q_p.add_argument("--device", help="Device ID")

    shuf_p = pb_sub.add_parser("shuffle", help="Set shuffle")
    shuf_p.add_argument("state", help="on/off")

    rep_p = pb_sub.add_parser("repeat", help="Set repeat mode")
    rep_p.add_argument("state", choices=["off", "track", "context"])

    xfer_p = pb_sub.add_parser("transfer", help="Transfer playback to device")
    xfer_p.add_argument("--device-id", required=True)
    xfer_p.add_argument("--play", action="store_true", help="Start playing on transfer")

    # --- dispatch ---
    args = parser.parse_args()

    config = Config()

    try:
        match args.command:
            case "auth":
                result = _dispatch_auth(args, config)
            case "playlists":
                result = _dispatch_playlists(args, config)
            case "search":
                result = _dispatch_search(args, config)
            case "organize":
                result = _dispatch_organize(args, config)
            case "playback":
                result = _dispatch_playback(args, config)
            case _:
                result = {"error": f"unknown command: {args.command}"}
    except Exception as e:
        result = {"error": type(e).__name__, "message": str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
