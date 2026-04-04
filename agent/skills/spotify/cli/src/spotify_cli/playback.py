"""Playback control (requires Spotify Premium)."""

from .config import Config
from .auth import get_client


def _format_track(track: dict | None) -> dict | None:
    if not track:
        return None
    return {
        "id": track.get("id"),
        "name": track.get("name"),
        "artists": ", ".join(a["name"] for a in track.get("artists", [])),
        "album": track.get("album", {}).get("name"),
        "duration_ms": track.get("duration_ms"),
        "uri": track.get("uri"),
    }


def current(config: Config) -> dict:
    """Get current playback state."""
    sp = get_client(config)
    playback = sp.current_playback()

    if not playback:
        return {"status": "nothing_playing"}

    device = playback.get("device", {})
    track = _format_track(playback.get("item"))

    return {
        "is_playing": playback.get("is_playing", False),
        "track": track,
        "progress_ms": playback.get("progress_ms"),
        "device": {
            "id": device.get("id"),
            "name": device.get("name"),
            "type": device.get("type"),
            "volume": device.get("volume_percent"),
        },
        "shuffle": playback.get("shuffle_state"),
        "repeat": playback.get("repeat_state"),
    }


def devices(config: Config) -> dict:
    """List available playback devices."""
    sp = get_client(config)
    result = sp.devices()
    devs = [
        {
            "id": d["id"],
            "name": d["name"],
            "type": d["type"],
            "is_active": d["is_active"],
            "volume": d.get("volume_percent"),
        }
        for d in result.get("devices", [])
    ]
    return {"devices": devs}


def play(
    config: Config,
    uri: str | None = None,
    context_uri: str | None = None,
    device_id: str | None = None,
) -> dict:
    """Start or resume playback."""
    sp = get_client(config)

    kwargs: dict = {}
    if device_id:
        kwargs["device_id"] = device_id
    if uri:
        kwargs["uris"] = [uri]
    elif context_uri:
        kwargs["context_uri"] = context_uri

    try:
        sp.start_playback(**kwargs)
        return {"status": "playing"}
    except Exception as e:
        err = str(e)
        if "NO_ACTIVE_DEVICE" in err or "Not found" in err:
            return {"error": "no_active_device", "message": "No active Spotify device found. Open Spotify on a device first."}
        if "PREMIUM_REQUIRED" in err or "403" in err:
            return {"error": "premium_required", "message": "Playback control requires Spotify Premium."}
        raise


def pause(config: Config) -> dict:
    """Pause playback."""
    sp = get_client(config)
    try:
        sp.pause_playback()
        return {"status": "paused"}
    except Exception as e:
        if "NO_ACTIVE_DEVICE" in str(e):
            return {"error": "no_active_device", "message": "No active Spotify device found."}
        raise


def skip(config: Config, direction: str = "next") -> dict:
    """Skip to next or previous track."""
    sp = get_client(config)
    try:
        if direction == "previous":
            sp.previous_track()
        else:
            sp.next_track()
        return {"status": "skipped", "direction": direction}
    except Exception as e:
        if "NO_ACTIVE_DEVICE" in str(e):
            return {"error": "no_active_device", "message": "No active Spotify device found."}
        raise


def volume(config: Config, level: int, device_id: str | None = None) -> dict:
    """Set playback volume (0-100)."""
    sp = get_client(config)
    level = max(0, min(100, level))
    try:
        sp.volume(level, device_id=device_id)
        return {"status": "volume_set", "volume": level}
    except Exception as e:
        if "NO_ACTIVE_DEVICE" in str(e):
            return {"error": "no_active_device", "message": "No active Spotify device found."}
        raise


def queue_add(config: Config, uri: str, device_id: str | None = None) -> dict:
    """Add a track to the playback queue."""
    sp = get_client(config)
    try:
        sp.add_to_queue(uri=uri, device_id=device_id)
        return {"status": "queued", "uri": uri}
    except Exception as e:
        if "NO_ACTIVE_DEVICE" in str(e):
            return {"error": "no_active_device", "message": "No active Spotify device found."}
        raise


def shuffle(config: Config, state: bool) -> dict:
    """Set shuffle on or off."""
    sp = get_client(config)
    try:
        sp.shuffle(state)
        return {"status": "shuffle_set", "shuffle": state}
    except Exception as e:
        if "NO_ACTIVE_DEVICE" in str(e):
            return {"error": "no_active_device", "message": "No active Spotify device found."}
        raise


def repeat(config: Config, state: str = "off") -> dict:
    """Set repeat mode: off, track, or context."""
    sp = get_client(config)
    try:
        sp.repeat(state)
        return {"status": "repeat_set", "repeat": state}
    except Exception as e:
        if "NO_ACTIVE_DEVICE" in str(e):
            return {"error": "no_active_device", "message": "No active Spotify device found."}
        raise


def transfer(config: Config, device_id: str, force_play: bool = False) -> dict:
    """Transfer playback to a specific device."""
    sp = get_client(config)
    sp.transfer_playback(device_id=device_id, force_play=force_play)
    return {"status": "transferred", "device_id": device_id}
