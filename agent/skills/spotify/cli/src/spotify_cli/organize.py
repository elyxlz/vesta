"""Spotify library organization — sync likes & genre-sort orphans."""

import json
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

from .config import Config
from .auth import get_client


ORGANIZE_CONFIG = Path.home() / ".spotify" / "organize.json"
WATCH_STATE_FILE = Path.home() / ".spotify" / "watch_state.json"
NOTIFICATIONS_DIR = Path.home() / "vesta" / "notifications"

# Default skip list — playlists too ambiguous or personal for auto-sorting.
# Customize this in ~/.spotify/organize.json after running: spotify organize config --init
DEFAULT_SKIP = [
    "Listen later",
    "Queue",
    "Inbox",
]

# Default genre rules: keywords → target playlist name.
# Customize these in ~/.spotify/organize.json after running: spotify organize config --init
# Each rule maps a list of genre keywords to a playlist name you own.
# Songs whose artist genres contain any keyword will be added to that playlist.
DEFAULT_GENRE_RULES = [
    {
        "keywords": ["idm", "intelligent dance", "glitch", "drill and bass",
                     "breakcore", "leftfield", "electronica"],
        "playlist": "IDM",
    },
    {
        "keywords": ["house", "techno", "tech house", "deep house", "minimal techno",
                     "acid house", "trance", "progressive house", "electro house",
                     "big room", "chicago house", "detroit techno", "uk garage",
                     "garage house", "eurodance", "dance", "nu-disco", "disco house"],
        "playlist": "House & Techno",
    },
    {
        "keywords": ["ambient", "drone", "dark ambient", "space ambient", "new age",
                     "atmospheric", "chillout", "downtempo", "lo-fi", "lo fi"],
        "playlist": "Ambient",
    },
    {
        "keywords": ["jazz", "bossa nova", "smooth jazz", "bebop", "hard bop",
                     "cool jazz", "modal jazz", "free jazz", "swing", "big band",
                     "nu jazz", "jazz fusion"],
        "playlist": "Jazz",
    },
    {
        "keywords": ["blues", "delta blues", "chicago blues", "electric blues",
                     "soul blues", "rhythm and blues", "swamp blues"],
        "playlist": "Blues",
    },
    {
        "keywords": ["funk", "soul", "neo soul", "p funk", "g funk", "classic soul",
                     "northern soul", "blue-eyed soul", "rnb", "r&b",
                     "contemporary r&b"],
        "playlist": "Funk & Soul",
    },
    {
        "keywords": ["hip hop", "rap", "trap", "underground hip hop",
                     "east coast hip hop", "west coast rap", "southern hip hop",
                     "conscious hip hop", "boom bap", "gangsta rap", "dirty south",
                     "memphis rap"],
        "playlist": "Hip Hop",
    },
    {
        "keywords": ["grunge", "noise rock", "post-grunge", "hardcore", "heavy metal",
                     "metal", "punk", "post-punk", "hard rock", "stoner rock",
                     "doom metal", "sludge metal"],
        "playlist": "Heavy",
    },
    {
        "keywords": ["rock", "alternative", "indie rock", "indie pop", "indie",
                     "psychedelic rock", "classic rock", "garage rock", "surf",
                     "power pop", "britpop", "shoegaze", "dream pop", "post-rock",
                     "art rock", "folk rock"],
        "playlist": "Rock",
    },
    {
        "keywords": ["folk", "singer-songwriter", "acoustic", "country", "americana",
                     "bluegrass", "roots", "chamber folk", "anti-folk"],
        "playlist": "Folk",
    },
    {
        "keywords": ["classical", "piano", "neo-classical", "neoclassical",
                     "contemporary classical", "post-romantic", "minimalism",
                     "modern classical", "chamber music"],
        "playlist": "Classical",
    },
    {
        "keywords": ["mpb", "brazilian", "samba", "pagode", "axe", "baile funk",
                     "forro", "tropicalia", "bossa"],
        "playlist": "Brazilian",
    },
    {
        "keywords": ["electronic", "synth-pop", "new wave", "electropop"],
        "playlist": "Electronic",
    },
]


def _load_config() -> dict:
    """Load organize config, creating defaults if missing."""
    if ORGANIZE_CONFIG.exists():
        with open(ORGANIZE_CONFIG) as f:
            return json.load(f)
    return {"skip_playlists": DEFAULT_SKIP, "genre_rules": DEFAULT_GENRE_RULES}


def _save_config(cfg: dict) -> None:
    """Save organize config to disk."""
    ORGANIZE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(ORGANIZE_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _get_own_playlists(sp) -> dict[str, str]:
    """Fetch all playlists owned by the current user. Returns {name: id}."""
    user_id = sp.current_user()["id"]
    own = {}
    offset = 0
    while True:
        resp = sp.current_user_playlists(limit=50, offset=offset)
        for item in resp.get("items", []):
            if item["owner"]["id"] == user_id:
                own[item["name"]] = item["id"]
        total = resp.get("total", 0)
        offset += 50
        if offset >= total:
            break
        time.sleep(0.1)
    return own


def _get_playlist_tracks(sp, playlist_id: str) -> list[tuple]:
    """Return [(track_id, track_uri, track_name, [artist_ids])] for a playlist."""
    tracks = []
    offset = 0
    while True:
        resp = sp.playlist_items(
            playlist_id,
            limit=100,
            offset=offset,
            fields="items(track(id,uri,name,artists)),next,total",
        )
        for item in resp.get("items", []):
            t = item.get("track")
            if not t or not t.get("id"):
                continue
            tracks.append((
                t["id"],
                t["uri"],
                t["name"],
                [a["id"] for a in t.get("artists", []) if a.get("id")],
            ))
        total = resp.get("total", 0)
        offset += 100
        if offset >= total:
            break
        time.sleep(0.1)
    return tracks


def _paginate_saved(sp) -> list[dict]:
    """Paginate through all liked/saved tracks."""
    results = []
    offset = 0
    while True:
        resp = sp.current_user_saved_tracks(limit=50, offset=offset)
        items = resp.get("items", [])
        results.extend(items)
        total = resp.get("total", 0)
        offset += 50
        if offset >= total:
            break
        time.sleep(0.1)
    return results


def _match_genre(genres: list[str], rules: list[dict]) -> str | None:
    """Match artist genres against rules, return target playlist name or None."""
    genres_lower = [g.lower() for g in genres]
    for rule in rules:
        for kw in rule["keywords"]:
            for g in genres_lower:
                if kw in g:
                    return rule["playlist"]
    return None


def _match_all_genres(genres: list[str], rules: list[dict]) -> list[str]:
    """Match artist genres against rules, return ALL matching playlist names."""
    genres_lower = [g.lower() for g in genres]
    matched = []
    seen = set()
    for rule in rules:
        playlist = rule["playlist"]
        if playlist in seen:
            continue
        for kw in rule["keywords"]:
            for g in genres_lower:
                if kw in g:
                    matched.append(playlist)
                    seen.add(playlist)
                    break
            if playlist in seen:
                break
    return matched


def _load_watch_state() -> dict:
    """Load the watch daemon state file."""
    if WATCH_STATE_FILE.exists():
        with open(WATCH_STATE_FILE) as f:
            return json.load(f)
    return {"known_liked_ids": [], "last_poll": None}


def _save_watch_state(state: dict) -> None:
    """Save the watch daemon state file."""
    WATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCH_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _write_notification(data: dict) -> None:
    """Write a notification JSON file to the notifications directory."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    data.setdefault("source", "spotify")
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = NOTIFICATIONS_DIR / f"spotify_liked_{ts}.json"
    with open(filename, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _log(msg: str) -> None:
    """Log to stderr with timestamp."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


# ── Public commands ──────────────────────────────────────────────────────────


def init_config(config: Config) -> dict:
    """Initialize organize config with defaults."""
    cfg = {"skip_playlists": DEFAULT_SKIP, "genre_rules": DEFAULT_GENRE_RULES}
    _save_config(cfg)
    return {
        "status": "initialized",
        "path": str(ORGANIZE_CONFIG),
        "skip_playlists": len(cfg["skip_playlists"]),
        "genre_rules": len(cfg["genre_rules"]),
    }


def show_config(config: Config) -> dict:
    """Show current organize config."""
    cfg = _load_config()
    return {
        "path": str(ORGANIZE_CONFIG),
        "skip_playlists": cfg.get("skip_playlists", []),
        "genre_rules": [
            {"playlist": r["playlist"], "keyword_count": len(r["keywords"])}
            for r in cfg.get("genre_rules", [])
        ],
    }


def sync_likes(config: Config, dry_run: bool = False) -> dict:
    """Like all tracks from own playlists that aren't liked yet."""
    sp = get_client(config)
    own_playlists = _get_own_playlists(sp)

    # Collect all tracks from own playlists
    playlist_track_ids = set()
    per_playlist = {}
    for pname, pid in own_playlists.items():
        tracks = _get_playlist_tracks(sp, pid)
        ids = {t[0] for t in tracks}
        playlist_track_ids.update(ids)
        per_playlist[pname] = len(tracks)
        time.sleep(0.1)

    # Collect all liked songs
    liked_items = _paginate_saved(sp)
    liked_ids = set()
    for item in liked_items:
        t = item.get("track")
        if t and t.get("id"):
            liked_ids.add(t["id"])

    to_like = list(playlist_track_ids - liked_ids)

    if dry_run:
        return {
            "status": "dry_run",
            "own_playlists": len(own_playlists),
            "playlist_tracks": len(playlist_track_ids),
            "liked_tracks": len(liked_ids),
            "would_like": len(to_like),
        }

    added = 0
    if to_like:
        for batch in _chunks(to_like, 20):
            sp._put("me/tracks", payload={"ids": batch})
            added += len(batch)
            time.sleep(0.3)

    return {
        "status": "done",
        "own_playlists": len(own_playlists),
        "playlist_tracks": len(playlist_track_ids),
        "liked_before": len(liked_ids),
        "newly_liked": added,
    }


def sort_orphans(config: Config, dry_run: bool = False) -> dict:
    """Sort orphan liked songs into playlists based on genre rules."""
    sp = get_client(config)
    cfg = _load_config()
    rules = cfg.get("genre_rules", DEFAULT_GENRE_RULES)
    skip = set(cfg.get("skip_playlists", DEFAULT_SKIP))

    own_playlists = _get_own_playlists(sp)

    # Build name → id mapping for rule targets (only playlists that exist)
    name_to_id = {}
    for r in rules:
        pname = r["playlist"]
        if pname in own_playlists:
            name_to_id[pname] = own_playlists[pname]

    # Collect all tracks from own playlists
    playlist_track_ids = set()
    playlist_existing = {}  # pid → set of track ids (for dedup, non-skip only)
    for pname, pid in own_playlists.items():
        tracks = _get_playlist_tracks(sp, pid)
        ids = {t[0] for t in tracks}
        playlist_track_ids.update(ids)
        if pname not in skip:
            playlist_existing[pid] = ids
        time.sleep(0.1)

    # Collect liked songs
    liked_items = _paginate_saved(sp)
    liked_info = {}  # id → (uri, name, [artist_ids])
    for item in liked_items:
        t = item.get("track")
        if not t or not t.get("id"):
            continue
        liked_info[t["id"]] = (
            t["uri"],
            t["name"],
            [a["id"] for a in t.get("artists", []) if a.get("id")],
        )

    # Find orphans (liked but not in any own playlist)
    orphan_ids = [tid for tid in liked_info if tid not in playlist_track_ids]

    # Get artist genres
    all_artist_ids = set()
    for tid in orphan_ids:
        _, _, artist_ids = liked_info[tid]
        all_artist_ids.update(artist_ids)

    artist_genres = {}
    for batch in _chunks(list(all_artist_ids), 50):
        resp = sp.artists(batch)
        for a in resp.get("artists", []):
            if a:
                artist_genres[a["id"]] = a.get("genres", [])
        time.sleep(0.2)

    # Match orphans to playlists
    additions = {}  # playlist_name → [(track_id, track_uri, track_name)]
    unmatched = []

    for tid in orphan_ids:
        turi, tname, artist_ids = liked_info[tid]
        genres = []
        for aid in artist_ids:
            genres.extend(artist_genres.get(aid, []))

        match = _match_genre(genres, rules)
        if not match or match not in name_to_id:
            unmatched.append({"name": tname, "genres": genres[:5]})
            continue

        pid = name_to_id[match]
        if tid in playlist_existing.get(pid, set()):
            continue

        if match not in additions:
            additions[match] = []
        additions[match].append((tid, turi, tname))

    if dry_run:
        return {
            "status": "dry_run",
            "orphan_tracks": len(orphan_ids),
            "would_sort": sum(len(v) for v in additions.values()),
            "unmatched": len(unmatched),
            "breakdown": {k: len(v) for k, v in additions.items()},
            "unmatched_sample": unmatched[:20],
        }

    # Apply additions
    sorted_count = 0
    breakdown = {}
    for pname, tracks in additions.items():
        pid = name_to_id[pname]
        uris = [t[1] for t in tracks]
        for batch in _chunks(uris, 100):
            sp.playlist_add_items(pid, batch)
            time.sleep(0.3)
        sorted_count += len(tracks)
        breakdown[pname] = [t[2] for t in tracks]

    return {
        "status": "done",
        "orphan_tracks": len(orphan_ids),
        "sorted": sorted_count,
        "unmatched": len(unmatched),
        "breakdown": {k: len(v) for k, v in breakdown.items()},
        "unmatched_sample": unmatched[:20],
    }


def full_organize(config: Config, dry_run: bool = False) -> dict:
    """Run both sync + sort in sequence."""
    sync_result = sync_likes(config, dry_run=dry_run)
    sort_result = sort_orphans(config, dry_run=dry_run)
    return {
        "status": "dry_run" if dry_run else "done",
        "sync": sync_result,
        "sort": sort_result,
    }


def init_watch(config: Config) -> dict:
    """Initialize the watch state file by snapshotting current liked songs (no processing)."""
    sp = get_client(config)
    _log("Initializing watch state — fetching current liked songs...")

    resp = sp.current_user_saved_tracks(limit=50, offset=0)
    liked_ids = []
    total = resp.get("total", 0)
    offset = 0
    while True:
        for item in resp.get("items", []):
            t = item.get("track")
            if t and t.get("id"):
                liked_ids.append(t["id"])
        offset += 50
        if offset >= total:
            break
        time.sleep(0.1)
        resp = sp.current_user_saved_tracks(limit=50, offset=offset)

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {
        "known_liked_ids": liked_ids,
        "last_poll": now,
    }
    _save_watch_state(state)

    _log(f"Watch state initialized with {len(liked_ids)} known liked songs.")
    return {
        "status": "initialized",
        "path": str(WATCH_STATE_FILE),
        "known_liked_ids": len(liked_ids),
        "last_poll": now,
    }


def watch_daemon(config: Config, interval: int = 60) -> None:
    """Run the watch daemon — polls liked songs and notifies on new likes."""
    _log(f"Starting watch daemon (poll interval: {interval}s)")
    _log(f"State file: {WATCH_STATE_FILE}")
    _log(f"Notifications dir: {NOTIFICATIONS_DIR}")

    # Auto-init if state file doesn't exist
    state = _load_watch_state()
    if not state.get("known_liked_ids") and state.get("last_poll") is None:
        _log("No state file found — initializing (snapshotting current liked songs, no processing)...")
        init_watch(config)
        state = _load_watch_state()
        _log(f"Initialized with {len(state['known_liked_ids'])} known songs. Watching for new likes...")

    while True:
        try:
            _poll_cycle(config, state)
        except Exception as e:
            _log(f"Error during poll cycle: {type(e).__name__}: {e}")

        _log(f"Sleeping {interval}s until next poll...")
        time.sleep(interval)


def _poll_cycle(config: Config, state: dict) -> None:
    """Single poll cycle: fetch recent liked songs, detect new ones, notify."""
    sp = get_client(config)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    _log("Polling liked songs (most recent 20)...")
    resp = sp.current_user_saved_tracks(limit=20, offset=0)
    recent_items = resp.get("items", [])

    known_ids = set(state.get("known_liked_ids", []))
    new_items = []
    for item in recent_items:
        t = item.get("track")
        if t and t.get("id") and t["id"] not in known_ids:
            new_items.append(item)

    if not new_items:
        _log("No new liked songs.")
        state["last_poll"] = now
        _save_watch_state(state)
        return

    _log(f"Found {len(new_items)} new liked song(s) — notifying...")

    for item in new_items:
        t = item.get("track")
        if not t or not t.get("id"):
            continue
        track_id = t["id"]
        track_name = t["name"]
        artist_ids = [a["id"] for a in t.get("artists", []) if a.get("id")]
        artist_name = t["artists"][0]["name"] if t.get("artists") else "Unknown"

        _log(f"New like: {track_name} by {artist_name}")

        # Get artist genres for context
        genres = []
        if artist_ids:
            try:
                time.sleep(0.2)
                resp_artists = sp.artists(artist_ids[:50])
                for a in resp_artists.get("artists", []):
                    if a:
                        genres.extend(a.get("genres", []))
            except Exception as e:
                _log(f"  Warning: could not fetch genres: {e}")

        genre_str = ", ".join(genres[:10]) if genres else "none"
        message = f'Liked "{track_name}" by {artist_name} (genres: {genre_str})'
        notification = {
            "type": "spotify",
            "timestamp": now,
            "message": message,
            "data": {
                "track_name": track_name,
                "artist": artist_name,
                "track_id": track_id,
                "track_uri": t.get("uri", ""),
                "genres": genres[:10],
            },
        }
        _write_notification(notification)
        _log("  Notification written.")

        known_ids.add(track_id)

    state["known_liked_ids"] = list(known_ids)
    state["last_poll"] = now
    _save_watch_state(state)
    _log(f"State updated — {len(known_ids)} total known liked IDs.")
