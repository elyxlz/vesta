#!/usr/bin/env python3
"""Twitter/X monitoring daemon via Nitter RSS.

Usage:
    python3 monitor.py serve --notifications-dir ~/vesta/notifications
    python3 monitor.py follow @FAOClimate
    python3 monitor.py unfollow @FAOClimate
    python3 monitor.py list
"""

import argparse
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, UTC
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.tiekoetter.com",
    "https://nitter.privacyredirect.com",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

DATA_DIR = Path.home() / "vesta" / "data" / "twitter"
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"

POLL_INTERVAL = 20 * 60  # 20 minutes
MAX_SEEN = 2000  # cap seen GUIDs to avoid unbounded growth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("twitter.monitor")

# ---------------------------------------------------------------------------
# Config file (list of handles)
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"handles": []}


def _save_config(config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.replace(CONFIG_FILE)


# ---------------------------------------------------------------------------
# State file (seen tweet GUIDs)
# ---------------------------------------------------------------------------


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"seen_guids": [], "last_check": None}


def _save_state(state: dict) -> None:
    # Keep seen_guids bounded
    seen = state.get("seen_guids", [])
    if len(seen) > MAX_SEEN:
        state["seen_guids"] = seen[-MAX_SEEN:]
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------------------
# Nitter RSS fetcher
# ---------------------------------------------------------------------------


def _fetch_rss(handle: str) -> list[dict]:
    """Fetch recent tweets for a handle. Returns list of tweet dicts."""
    # Strip leading @ if present
    username = handle.lstrip("@")
    for base in NITTER_INSTANCES:
        url = f"{base}/{username}/rss"
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                logger.debug(f"{base}: HTTP {resp.status_code} for {handle}")
                continue
            if "<item>" not in resp.text:
                logger.debug(f"{base}: no items in response for {handle}")
                continue
            return _parse_rss(resp.text, handle)
        except Exception as e:
            logger.debug(f"{base}: error fetching {handle}: {e}")
            continue
    logger.warning(f"All nitter instances failed for {handle}")
    return []


def _parse_rss(xml_text: str, handle: str) -> list[dict]:
    """Parse nitter RSS XML into tweet dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"XML parse error for {handle}: {e}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    tweets = []
    for item in channel.findall("item"):
        guid_el = item.find("guid")
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")

        raw_guid = guid_el.text if guid_el is not None else None
        if not raw_guid:
            continue
        # Normalize: extract status ID from URL-style GUIDs like
        # https://nitter.net/user/status/12345#m  →  "12345"
        # This ensures consistent dedup regardless of nitter instance or fragment
        m = re.search(r"/status/(\d+)", raw_guid)
        guid = m.group(1) if m else raw_guid.rstrip("#m").rstrip("/")

        title = title_el.text if title_el is not None else ""
        link = link_el.text if link_el is not None else ""
        pub_date = pub_el.text if pub_el is not None else ""

        tweets.append(
            {
                "guid": guid,
                "handle": handle,
                "text": title,
                "url": link,
                "published": pub_date,
            }
        )

    return tweets


# ---------------------------------------------------------------------------
# Notification writer
# ---------------------------------------------------------------------------


def _write_notification(notif_dir: Path, tweet: dict) -> None:
    notif_dir.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "twitter",
        "type": "tweet",
        "handle": tweet["handle"],
        "content": tweet["text"],
        "url": tweet["url"],
        "published": tweet["published"],
        "timestamp": datetime.now(UTC).isoformat(),
        "event_id": f"twitter:tweet:{tweet['guid']}",
    }
    ts_us = int(time.time() * 1e6)
    filename = f"{ts_us}-twitter-tweet.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)


# ---------------------------------------------------------------------------
# Monitor loop
# ---------------------------------------------------------------------------


def _parse_pub_date(pub_date: str) -> "datetime | None":
    """Parse RSS pubDate string to datetime, or None on failure."""
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(pub_date)
    except Exception:
        return None


def _poll_once(handles: list[str], notif_dir: Path, state: dict, seed_only: bool = False) -> int:
    """Poll all handles. Returns number of new tweets found."""
    from datetime import timedelta

    seen = set(state.get("seen_guids", []))
    new_guids = list(seen)
    new_count = 0

    # Only notify about tweets published after last_check (with 30min buffer for clock skew)
    # This prevents old tweets that escape GUID dedup from generating noise
    last_check_str = state.get("last_check")
    if last_check_str and not seed_only:
        try:
            last_check_dt = datetime.fromisoformat(last_check_str)
            # Add buffer: notify if published within POLL_INTERVAL + 30min before last check
            min_pub_dt = last_check_dt - timedelta(seconds=POLL_INTERVAL + 1800)
        except Exception:
            min_pub_dt = None
    else:
        min_pub_dt = None

    for handle in handles:
        try:
            tweets = _fetch_rss(handle)
            for tweet in tweets:
                guid = tweet["guid"]
                if guid in seen:
                    continue
                new_guids.append(guid)
                seen.add(guid)

                # Age check: skip notifying about old tweets even if GUID is new
                if not seed_only and min_pub_dt is not None:
                    pub_dt = _parse_pub_date(tweet.get("published", ""))
                    if pub_dt is not None and pub_dt < min_pub_dt:
                        logger.debug(f"Skipping old tweet from {handle} ({tweet['published']}): {tweet['text'][:60]}")
                        continue

                new_count += 1
                if not seed_only:
                    _write_notification(notif_dir, tweet)
                    logger.info(f"New tweet from {handle}: {tweet['text'][:80]}")
            if tweets:
                logger.debug(
                    f"{handle}: fetched {len(tweets)} tweets, {sum(1 for t in tweets if t['guid'] not in (set(state.get('seen_guids', [])) - set(new_guids)))} new"
                )
        except Exception as e:
            logger.error(f"Error polling {handle}: {e}")

        # Small delay between handles to be polite
        time.sleep(0.5)

    state["seen_guids"] = new_guids
    return new_count


def serve(notif_dir: Path) -> None:
    """Main monitor loop."""
    logger.info(f"Twitter monitor starting. Poll interval: {POLL_INTERVAL}s")
    first_run = True

    while True:
        config = _load_config()
        handles = config.get("handles", [])

        if not handles:
            logger.info("No handles configured. Sleeping...")
        else:
            state = _load_state()

            if first_run:
                logger.info(f"First run — seeding {len(handles)} handles without notifying")
                _poll_once(handles, notif_dir, state, seed_only=True)
                first_run = False
                logger.info(f"Seeded {len(state.get('seen_guids', []))} tweet GUIDs")
            else:
                logger.info(f"Polling {len(handles)} handles...")
                count = _poll_once(handles, notif_dir, state)
                logger.info(f"Poll complete: {count} new tweets")

            state["last_check"] = datetime.now(UTC).isoformat()
            _save_state(state)

        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_follow(args: argparse.Namespace) -> None:
    config = _load_config()
    handles = config.get("handles", [])
    handle = args.handle if args.handle.startswith("@") else f"@{args.handle}"
    if handle.lower() in [h.lower() for h in handles]:
        print(f"Already following {handle}")
        return
    handles.append(handle)
    config["handles"] = handles
    _save_config(config)
    print(f"Now following {handle} ({len(handles)} total)")


def cmd_unfollow(args: argparse.Namespace) -> None:
    config = _load_config()
    handles = config.get("handles", [])
    handle = args.handle if args.handle.startswith("@") else f"@{args.handle}"
    new_handles = [h for h in handles if h.lower() != handle.lower()]
    if len(new_handles) == len(handles):
        print(f"Not following {handle}")
        return
    config["handles"] = new_handles
    _save_config(config)
    print(f"Unfollowed {handle} ({len(new_handles)} remaining)")


def cmd_list(args: argparse.Namespace) -> None:
    config = _load_config()
    handles = config.get("handles", [])
    if not handles:
        print("No handles configured")
        return
    print(f"Following {len(handles)} accounts:")
    for h in sorted(handles, key=str.lower):
        print(f"  {h}")


def cmd_serve(args: argparse.Namespace) -> None:
    notif_dir = Path(args.notifications_dir).expanduser()
    serve(notif_dir)


def cmd_test(args: argparse.Namespace) -> None:
    """Fetch and print recent tweets from a handle (for testing)."""
    handle = args.handle
    print(f"Fetching tweets for {handle}...")
    tweets = _fetch_rss(handle)
    if not tweets:
        print("No tweets fetched (all instances failed?)")
        return
    print(f"Got {len(tweets)} tweets:")
    for t in tweets[:5]:
        print(f"\n  [{t['published']}]")
        print(f"  {t['text'][:120]}")
        print(f"  {t['url']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitter/X monitor via Nitter RSS")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the monitor daemon")
    p_serve.add_argument("--notifications-dir", required=True, help="Directory to write notification JSON files")
    p_serve.set_defaults(func=cmd_serve)

    p_follow = sub.add_parser("follow", help="Add a handle to monitor")
    p_follow.add_argument("handle", help="Twitter handle (e.g. @FAOClimate)")
    p_follow.set_defaults(func=cmd_follow)

    p_unfollow = sub.add_parser("unfollow", help="Remove a handle from monitoring")
    p_unfollow.add_argument("handle", help="Twitter handle")
    p_unfollow.set_defaults(func=cmd_unfollow)

    p_list = sub.add_parser("list", help="List followed handles")
    p_list.set_defaults(func=cmd_list)

    p_test = sub.add_parser("test", help="Fetch and print recent tweets from a handle")
    p_test.add_argument("handle", help="Twitter handle to test")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
