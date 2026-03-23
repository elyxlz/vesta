#!/usr/bin/env python3
"""
Phase 1: Event Identity Tagger
Watches ~/vesta/notifications/ and enriches each notification JSON
with a stable event_id. Logs assignments to ~/vesta/logs/event-ids.log.

Non-destructive: does NOT change how events are processed.
If this daemon is down, vesta continues exactly as before.
"""

import hashlib
import json
import logging
import pathlib
import time

NOTIFICATIONS_DIR = pathlib.Path.home() / "vesta" / "notifications"
LOG_FILE = pathlib.Path.home() / "vesta" / "logs" / "event-ids.log"
POLL_INTERVAL = 0.3  # seconds


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def compute_event_id(data: dict) -> str:
    """Derive a stable event_id from notification data.

    Priority: use upstream-provided IDs where available.
    Fall back to deterministic hash of stable identifying fields.
    """
    source = data.get("source", "unknown")
    type_ = data.get("type", "unknown")

    # --- WhatsApp message ---
    if source == "whatsapp" and type_ == "message":
        msg_id = data.get("message_id")
        if msg_id:
            return f"wa:msg:{msg_id}"
        key = ":".join([
            data.get("instance", ""),
            data.get("contact_phone", ""),
            data.get("chat_name", ""),
            data.get("message", "")[:64],
        ])
        return f"wa:msg:h:{_hash(key)}"

    # --- WhatsApp reaction ---
    if source == "whatsapp" and type_ == "reaction":
        target = data.get("target_message_id", "")
        emoji = data.get("emoji", "")
        sender = data.get("contact_phone") or data.get("sender", "")
        instance = data.get("instance", "")
        if target:
            return f"wa:react:{target}:{emoji}:{sender}:{instance}"
        key = f"{sender}:{emoji}:{data.get('chat_name', '')}:{instance}"
        return f"wa:react:h:{_hash(key)}"

    # --- Email (Microsoft) ---
    if source in ("email", "microsoft") or type_ == "email":
        email_id = data.get("email_id") or data.get("id")
        if email_id:
            return f"email:{email_id}"
        key = ":".join([
            data.get("sender_address", ""),
            data.get("subject", ""),
            data.get("received_at", ""),
            data.get("account", ""),
        ])
        return f"email:h:{_hash(key)}"

    # --- Calendar ---
    if source == "calendar" or type_ == "calendar":
        cal_id = data.get("event_id") or data.get("id")
        if cal_id:
            return f"cal:{cal_id}"
        key = ":".join([
            data.get("subject", ""),
            data.get("start_time", ""),
            data.get("account", ""),
        ])
        return f"cal:h:{_hash(key)}"

    # --- Reminder ---
    if source == "reminder" or type_ == "reminder":
        rid = data.get("reminder_id")
        if rid:
            return f"reminder:{rid}"
        key = f"{data.get('message', '')}:{data.get('timestamp', '')}"
        return f"reminder:h:{_hash(key)}"

    # --- Fallback: hash of stable fields (exclude timestamp) ---
    stable = {k: v for k, v in data.items() if k not in ("timestamp", "file_path")}
    return f"evt:{source}:{type_}:{_hash(json.dumps(stable, sort_keys=True))}"


def enrich_file(path: pathlib.Path, log: logging.Logger) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)

        # Already tagged — return existing id
        if "event_id" in data:
            return data["event_id"]

        event_id = compute_event_id(data)
        data["event_id"] = event_id

        # Write back enriched JSON (in-place)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return event_id

    except FileNotFoundError:
        # File already consumed by vesta — no problem
        return None
    except Exception as e:
        log.error(f"enrich {path.name}: {e}")
        return None


def main():
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(),
        ],
    )
    log = logging.getLogger("event-tagger")
    log.info("started — watching %s", NOTIFICATIONS_DIR)

    # Seed seen set so we don't re-tag files already present on startup
    seen: set[str] = {f.name for f in NOTIFICATIONS_DIR.glob("*.json")}

    while True:
        try:
            for path in sorted(NOTIFICATIONS_DIR.glob("*.json")):
                if path.name in seen:
                    continue
                seen.add(path.name)
                # Small delay to let the writer finish flushing
                time.sleep(0.05)
                event_id = enrich_file(path, log)
                if event_id:
                    log.info("%s | %s", event_id, path.name)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("stopped")
            break
        except Exception as e:
            log.error("loop error: %s", e)
            time.sleep(1)


if __name__ == "__main__":
    main()
