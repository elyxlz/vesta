"""Playlist operations."""

import spotipy

from .config import Config
from .auth import get_client


def list_playlists(config: Config, limit: int = 50) -> dict:
    """List current user's playlists."""
    sp = get_client(config)
    results = sp.current_user_playlists(limit=limit)

    playlists = []
    while results:
        for item in results["items"]:
            playlists.append({
                "id": item["id"],
                "name": item["name"],
                "tracks": item["tracks"]["total"],
                "public": item["public"],
                "owner": item["owner"]["display_name"],
                "uri": item["uri"],
            })
        results = sp.next(results) if results.get("next") else None

    return {"playlists": playlists, "total": len(playlists)}


def show_playlist(config: Config, playlist_id: str, limit: int = 50) -> dict:
    """Show playlist details and tracks."""
    sp = get_client(config)
    playlist = sp.playlist(playlist_id)

    tracks = []
    results = sp.playlist_items(playlist_id, limit=limit)
    while results:
        for item in results["items"]:
            track = item.get("track")
            if not track:
                continue
            tracks.append({
                "id": track.get("id"),
                "name": track.get("name"),
                "artists": ", ".join(a["name"] for a in track.get("artists", [])),
                "album": track.get("album", {}).get("name"),
                "duration_ms": track.get("duration_ms"),
                "uri": track.get("uri"),
            })
        results = sp.next(results) if results.get("next") else None

    return {
        "id": playlist["id"],
        "name": playlist["name"],
        "description": playlist.get("description", ""),
        "owner": playlist["owner"]["display_name"],
        "public": playlist["public"],
        "total_tracks": playlist["tracks"]["total"],
        "tracks": tracks,
        "uri": playlist["uri"],
    }


def create_playlist(
    config: Config,
    name: str,
    description: str = "",
    public: bool = True,
) -> dict:
    """Create a new playlist."""
    sp = get_client(config)
    user_id = sp.current_user()["id"]

    result = sp.user_playlist_create(
        user=user_id,
        name=name,
        public=public,
        description=description,
    )

    return {
        "status": "created",
        "id": result["id"],
        "name": result["name"],
        "uri": result["uri"],
        "url": result["external_urls"].get("spotify", ""),
    }


def add_tracks(config: Config, playlist_id: str, track_uris: list[str]) -> dict:
    """Add tracks to a playlist."""
    sp = get_client(config)
    sp.playlist_add_items(playlist_id, track_uris)
    return {
        "status": "added",
        "playlist_id": playlist_id,
        "tracks_added": len(track_uris),
    }


def remove_tracks(config: Config, playlist_id: str, track_uris: list[str]) -> dict:
    """Remove tracks from a playlist."""
    sp = get_client(config)
    sp.playlist_remove_all_occurrences_of_items(playlist_id, track_uris)
    return {
        "status": "removed",
        "playlist_id": playlist_id,
        "tracks_removed": len(track_uris),
    }


def liked_songs(config: Config, limit: int = 50, offset: int = 0) -> dict:
    """Get user's liked/saved songs."""
    sp = get_client(config)
    results = sp.current_user_saved_tracks(limit=limit, offset=offset)

    tracks = []
    for item in results["items"]:
        track = item["track"]
        tracks.append({
            "id": track.get("id"),
            "name": track.get("name"),
            "artists": ", ".join(a["name"] for a in track.get("artists", [])),
            "album": track.get("album", {}).get("name"),
            "added_at": item.get("added_at"),
            "uri": track.get("uri"),
        })

    return {
        "tracks": tracks,
        "total": results["total"],
        "offset": offset,
        "limit": limit,
    }
