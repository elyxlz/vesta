#!/usr/bin/env python3
"""Walking guide daemon — polls GPS, detects movement, drops notifications for nearby historical sites."""

import argparse
import json
import math
import os
import pathlib
import sys
import time
import urllib.request

SENT_FILE = pathlib.Path("/tmp/walking-guide-sent.txt")
PID_FILE = pathlib.Path("/tmp/walking-guide.pid")
NOTIFICATIONS_DIR = pathlib.Path.home() / "vesta" / "notifications"

# Loaded from environment
HASS_TOKEN = os.environ.get("HASS_TOKEN", "")
HASS_URL = os.environ.get("HASS_URL", "")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two GPS coordinates."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_location(entity: str) -> tuple[float, float] | None:
    """Fetch lat/lon from Home Assistant device tracker."""
    url = f"{HASS_URL}/api/states/{entity}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            attrs = data.get("attributes", {})
            lat = attrs.get("latitude")
            lon = attrs.get("longitude")
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] HA error: {e}", file=sys.stderr)
    return None


def drop_notification(lat: float, lon: float, phone: str) -> None:
    """Write a notification JSON for the agent to pick up and research."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    notif = {
        "source": "system",
        "type": "walking_guide",
        "message": (
            f"[Walking guide] User is at coordinates {lat:.6f}, {lon:.6f}. "
            f"Look up historical places of interest within 200 meters of these coordinates "
            f"and send a casual WhatsApp message to {phone} about anything interesting nearby. "
            f"Check {SENT_FILE} for places already mentioned — don't repeat them. "
            f"After sending, append the place names to that file. "
            f"If nothing notable is nearby, skip silently."
        ),
        "timestamp": ts,
    }
    fname = f"walking-guide-{int(time.time())}.json"
    (NOTIFICATIONS_DIR / fname).write_text(json.dumps(notif))
    print(f"[{time.strftime('%H:%M:%S')}] Notification dropped: {lat:.6f}, {lon:.6f}")


def run(phone: str, entity: str, interval: int, threshold: float) -> None:
    """Main polling loop."""
    print(f"Walking guide started: entity={entity}, interval={interval}s, threshold={threshold}m, phone={phone}")

    if not SENT_FILE.exists():
        SENT_FILE.write_text("")

    PID_FILE.write_text(str(os.getpid()))

    last_lat: float | None = None
    last_lon: float | None = None

    try:
        while True:
            loc = get_location(entity)
            if loc is None:
                print(f"[{time.strftime('%H:%M:%S')}] No location available, retrying...")
                time.sleep(interval)
                continue

            lat, lon = loc

            if last_lat is None or last_lon is None:
                print(f"[{time.strftime('%H:%M:%S')}] Initial position: {lat:.6f}, {lon:.6f}")
                drop_notification(lat, lon, phone)
                last_lat, last_lon = lat, lon
            else:
                dist = haversine(last_lat, last_lon, lat, lon)
                if dist >= threshold:
                    print(f"[{time.strftime('%H:%M:%S')}] Moved {dist:.0f}m to {lat:.6f}, {lon:.6f}")
                    drop_notification(lat, lon, phone)
                    last_lat, last_lon = lat, lon
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] Stationary ({dist:.0f}m < {threshold:.0f}m threshold)")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nWalking guide stopped.")
    finally:
        PID_FILE.unlink(missing_ok=True)


def stop() -> None:
    """Stop a running walking guide daemon."""
    import signal

    if not PID_FILE.exists():
        print("No walking guide is running.")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped walking guide (PID {pid})")
    except ProcessLookupError:
        print(f"Process {pid} not found (already stopped)")
    PID_FILE.unlink(missing_ok=True)


def _load_env() -> None:
    """Load HA credentials from /etc/environment if not already set."""
    global HASS_TOKEN, HASS_URL
    if HASS_TOKEN:
        return
    env_file = pathlib.Path("/etc/environment")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip()
    HASS_TOKEN = os.environ.get("HASS_TOKEN", "")
    HASS_URL = os.environ.get("HASS_URL", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Walking tour guide daemon")
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the walking guide")
    start_p.add_argument("--phone", required=True, help="WhatsApp number to send messages to")
    start_p.add_argument("--entity", required=True, help="HA device tracker entity (e.g. device_tracker.my_phone)")
    start_p.add_argument("--interval", type=int, default=120, help="Polling interval in seconds (default: 120)")
    start_p.add_argument("--threshold", type=float, default=50.0, help="Movement threshold in meters (default: 50)")

    sub.add_parser("stop", help="Stop the walking guide")

    args = parser.parse_args()

    if args.command == "start":
        _load_env()

        if not HASS_TOKEN:
            print("Error: HASS_TOKEN not found. Set it in environment or /etc/environment.", file=sys.stderr)
            sys.exit(1)

        if not HASS_URL:
            print("Error: HASS_URL not found. Set it in environment or /etc/environment.", file=sys.stderr)
            sys.exit(1)

        run(args.phone, args.entity, args.interval, args.threshold)

    elif args.command == "stop":
        stop()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
