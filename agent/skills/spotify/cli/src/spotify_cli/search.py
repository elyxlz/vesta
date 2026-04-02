"""Spotify search."""

from .config import Config
from .auth import get_client


def search(
    config: Config,
    query: str,
    search_type: str = "track",
    limit: int = 10,
) -> dict:
    """Search Spotify for tracks, albums, or artists."""
    sp = get_client(config)
    results = sp.search(q=query, type=search_type, limit=limit)

    output: dict = {"query": query, "type": search_type}

    if "tracks" in results:
        output["tracks"] = [
            {
                "id": t["id"],
                "name": t["name"],
                "artists": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": t.get("album", {}).get("name"),
                "duration_ms": t.get("duration_ms"),
                "uri": t["uri"],
                "url": t["external_urls"].get("spotify", ""),
            }
            for t in results["tracks"]["items"]
        ]

    if "albums" in results:
        output["albums"] = [
            {
                "id": a["id"],
                "name": a["name"],
                "artists": ", ".join(ar["name"] for ar in a.get("artists", [])),
                "release_date": a.get("release_date"),
                "total_tracks": a.get("total_tracks"),
                "uri": a["uri"],
                "url": a["external_urls"].get("spotify", ""),
            }
            for a in results["albums"]["items"]
        ]

    if "artists" in results:
        output["artists"] = [
            {
                "id": ar["id"],
                "name": ar["name"],
                "genres": ar.get("genres", []),
                "followers": ar.get("followers", {}).get("total", 0),
                "popularity": ar.get("popularity"),
                "uri": ar["uri"],
                "url": ar["external_urls"].get("spotify", ""),
            }
            for ar in results["artists"]["items"]
        ]

    return output
