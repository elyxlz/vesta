#!/usr/bin/env python3
"""Weather forecast tool using Windy Point Forecast API + HA auto-location."""

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
import urllib.request

WINDY_API_KEY = os.environ["WINDY_API_KEY"] if "WINDY_API_KEY" in os.environ else ""
WINDY_URL = "https://api.windy.com/api/point-forecast/v2"

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def wind_dir(u: float, v: float) -> str:
    """Convert u/v wind components to compass direction."""
    angle = (math.degrees(math.atan2(-u, -v)) + 360) % 360
    idx = int((angle + 11.25) / 22.5) % 16
    return COMPASS[idx]


def wind_speed(u: float, v: float) -> float:
    """Convert u/v wind components to speed in km/h."""
    return math.sqrt(u**2 + v**2) * 3.6


def kelvin_to_c(k: float) -> float:
    return k - 273.15


def get_ha_location() -> tuple[float, float, str] | None:
    """Get current location from Home Assistant."""
    try:
        result = subprocess.run(["ha", "location"], capture_output=True, text=True, timeout=10, env={**os.environ})
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        if "latitude" in data and "longitude" in data:
            lat = data["latitude"]
            lon = data["longitude"]
            tz = guess_timezone(lat, lon)
            return (lat, lon, tz)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def guess_timezone(lat: float, lon: float) -> str:
    """Simple timezone guess based on coordinates."""
    if 49 < lat < 61 and -8 < lon < 2:
        return "Europe/London"
    if 36 < lat < 47 and 6 < lon < 19:
        return "Europe/Rome"
    if 36 < lat < 44 and -10 < lon < 4:
        return "Europe/Madrid"
    if 25 < lat < 50 and -125 < lon < -66:
        return "America/New_York"
    return "UTC"


def fetch_forecast(lat: float, lon: float) -> dict:
    """Fetch forecast from Windy API."""
    payload = json.dumps(
        {
            "lat": lat,
            "lon": lon,
            "model": "gfs",
            "parameters": ["temp", "precip", "wind", "rh"],
            "levels": ["surface"],
            "key": WINDY_API_KEY,
        }
    ).encode()

    req = urllib.request.Request(
        WINDY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def format_forecast(data: dict, hours: int, tz_name: str, location_label: str) -> str:
    """Format forecast data into a readable summary."""
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(tz_name)
    except (ImportError, KeyError):
        tz = dt.UTC

    timestamps = data["ts"] if "ts" in data else []
    temps = data["temp-surface"] if "temp-surface" in data else []
    precips = data["past3hprecip-surface"] if "past3hprecip-surface" in data else []
    wind_us = data["wind_u-surface"] if "wind_u-surface" in data else []
    wind_vs = data["wind_v-surface"] if "wind_v-surface" in data else []
    rhs = data["rh-surface"] if "rh-surface" in data else []

    now = dt.datetime.now(dt.UTC)
    lines = [f"Weather forecast for {location_label}:"]
    lines.append("")

    count = 0
    rain_total = 0.0
    temp_min = float("inf")
    temp_max = float("-inf")
    hourly_lines = []

    for i, ts_ms in enumerate(timestamps):
        ts = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.UTC)
        if ts < now - dt.timedelta(hours=1):
            continue
        if count >= hours // 3 + 1:
            break

        local_ts = ts.astimezone(tz)
        temp_c = kelvin_to_c(temps[i]) if i < len(temps) else None
        precip = precips[i] if i < len(precips) else 0
        wu = wind_us[i] if i < len(wind_us) else 0
        wv = wind_vs[i] if i < len(wind_vs) else 0
        rh = rhs[i] if i < len(rhs) else None

        ws = wind_speed(wu, wv)
        wd = wind_dir(wu, wv)
        rain_total += precip or 0

        if temp_c is not None:
            temp_min = min(temp_min, temp_c)
            temp_max = max(temp_max, temp_c)

        time_str = local_ts.strftime("%H:%M")
        parts = [f"{time_str}"]
        if temp_c is not None:
            parts.append(f"{temp_c:.0f}°C")
        if precip and precip > 0.1:
            parts.append(f"rain {precip:.1f}mm")
        parts.append(f"wind {ws:.0f}km/h {wd}")
        if rh is not None:
            parts.append(f"humidity {rh:.0f}%")

        hourly_lines.append("  ".join(parts))
        count += 1

    summary_parts = []
    if temp_min != float("inf"):
        if abs(temp_max - temp_min) < 1.5:
            summary_parts.append(f"~{temp_max:.0f}°C")
        else:
            summary_parts.append(f"{temp_min:.0f}–{temp_max:.0f}°C")

    if rain_total > 0.5:
        summary_parts.append(f"rain expected ({rain_total:.1f}mm total)")
    else:
        summary_parts.append("no significant rain")

    lines.append("Summary: " + ", ".join(summary_parts))
    lines.append("")
    lines.extend(hourly_lines)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Weather forecast")
    parser.add_argument("--lat", type=float, help="Latitude")
    parser.add_argument("--lon", type=float, help="Longitude")
    parser.add_argument("--hours", type=int, default=12, help="Forecast hours (default: 12)")
    args = parser.parse_args()

    if not WINDY_API_KEY:
        print("Error: WINDY_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    lat, lon, tz_name, label = None, None, "UTC", "current location"

    if args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
        tz_name = guess_timezone(lat, lon)
        label = f"{lat:.2f}, {lon:.2f}"
    else:
        loc = get_ha_location()
        if loc:
            lat, lon, tz_name = loc
            label = f"your location ({lat:.2f}, {lon:.2f})"
        else:
            print("Could not detect location from Home Assistant. Use --lat/--lon.", file=sys.stderr)
            sys.exit(1)

    try:
        data = fetch_forecast(lat, lon)
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_forecast(data, args.hours, tz_name, label))


if __name__ == "__main__":
    main()
