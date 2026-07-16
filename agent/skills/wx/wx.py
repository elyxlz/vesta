#!/usr/bin/env python3
"""No-key weather via open-meteo (no API key required).
Usage: wx [location]   (default London). Prints a one-line human summary."""

import sys
import json
import urllib.request
import urllib.parse

WMO = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm w/ hail",
    99: "thunderstorm w/ hail",
}

# Minimal geocode table for common spots; else use open-meteo geocoding.
PLACES = {
    "london": (51.5074, -0.1278),
}


def geocode(name):
    key = name.strip().lower()
    if key in PLACES:
        return PLACES[key]
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name, "count": 1})
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.load(r)
    if "results" not in d or not d["results"]:
        raise SystemExit(f"could not geocode '{name}'")
    res = d["results"][0]
    return res["latitude"], res["longitude"]


def main():
    place = sys.argv[1] if len(sys.argv) > 1 else "London"
    lat, lon = geocode(place)
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "auto",
        "forecast_days": 1,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.load(r)
    cur = d["current"]
    day = d["daily"]
    now_desc = WMO[cur["weather_code"]] if cur["weather_code"] in WMO else "mixed"
    day_desc = WMO[day["weather_code"][0]] if day["weather_code"][0] in WMO else "mixed"
    lo = round(day["temperature_2m_min"][0])
    hi = round(day["temperature_2m_max"][0])
    pop = day["precipitation_probability_max"][0]
    now_t = round(cur["temperature_2m"])
    wind = round(cur["wind_speed_10m"])
    print(f"{place}: now {now_t}C {now_desc}, today {lo}-{hi}C {day_desc}, rain chance {pop}%, wind {wind} km/h")


if __name__ == "__main__":
    main()
