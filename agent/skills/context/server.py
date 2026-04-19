#!/usr/bin/env python3
"""Context window usage + nap controller.

Reads the SDK-authoritative `[USAGE] Context: X% (Y/Z tokens)` line that
core/client.py logs every message cycle, and exposes:

    GET  /          current snapshot + nap config
    POST /nap       manual nap trigger
    GET  /config    nap config only
    POST /config    update nap config (JSON body)

When enabled, a background loop checks thresholds:
  pct >= hard_pct                                   , nap now
  pct >= soft_pct and idle for >= idle_minutes      , nap now

A nap trigger drops `<data_dir>/nap_request`; core's `process_nap_request`
loop picks it up, sets nap_active, queues the nightly_dream prompt. Same
session reset + restart flow as the nightly dreamer, only the restart
reason label differs.
"""
import datetime as dt
import glob
import json
import os
import pathlib as pl
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


AGENT_HOME = pl.Path.home() / "agent"
VESTA_LOG = AGENT_HOME / "logs" / "vesta.log"
HISTORY_LOG = AGENT_HOME / "logs" / "context-status.jsonl"
DATA_DIR = AGENT_HOME / "data"
NAP_TRIGGER = DATA_DIR / "nap_request"
CONFIG_PATH = AGENT_HOME / "data" / "skills" / "context" / "config.json"
SESSIONS_GLOB = str(pl.Path.home() / ".claude" / "projects" / "-root-agent" / "*.jsonl")

HISTORY_LOG.parent.mkdir(parents=True, exist_ok=True)
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

USAGE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) .*?\[USAGE\] Context: "
    r"(?P<pct>[\d.]+)% \((?P<tok>[\d,]+)/(?P<max>[\d,]+) tokens\)"
)

START_TIME = time.time()
DEFAULT_CONFIG = {
    "enabled": True,
    "soft_pct": 50.0,
    "hard_pct": 70.0,
    "idle_minutes": 5,
    "cooldown_minutes": 10,
    # User-idle notification: drop a passive notification once the user has been
    # idle for this many minutes. Set to 0 to disable. Notification is passive
    # (interrupt=false) so it only surfaces when the agent is already active.
    "user_idle_notify_minutes": 20,
}
_last_nap_trigger_ts: float = 0.0
_user_idle_notified: bool = False
_USER_IDLE_MIN_INTERVAL_S: float = 3600.0  # don't re-notify more than once an hour
_USER_IDLE_STAMP = DATA_DIR / "user_idle_last_notified_ts"


def _read_last_idle_notified() -> float:
    try:
        return float(_USER_IDLE_STAMP.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def _write_last_idle_notified(ts: float) -> None:
    try:
        _USER_IDLE_STAMP.write_text(str(ts))
    except OSError:
        pass

NOTIFICATIONS_DIR = pl.Path.home() / "agent" / "notifications"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return {**DEFAULT_CONFIG, **data}
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_CONFIG)


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _parse_usage_line(line: str) -> dict | None:
    m = USAGE_RE.search(line)
    if not m:
        return None
    return {
        "ts": m.group("ts"),
        "pct": float(m.group("pct")),
        "tok": int(m.group("tok").replace(",", "")),
        "max": int(m.group("max").replace(",", "")),
    }


def _latest_usage() -> dict | None:
    if not VESTA_LOG.exists():
        return None
    try:
        with open(VESTA_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 64_000)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return None
    for line in reversed(data.splitlines()):
        parsed = _parse_usage_line(line)
        if parsed:
            return parsed
    return None


def _last_user_activity_seconds() -> float | None:
    """Seconds since the most recent session jsonl file was modified."""
    files = glob.glob(SESSIONS_GLOB)
    if not files:
        return None
    try:
        latest = max(os.path.getmtime(f) for f in files)
    except OSError:
        return None
    return max(0.0, time.time() - latest)


def _container_uptime_seconds() -> int:
    """Uptime of the agent container, not this service.
    Uses ctime of /proc/1 which reflects when the container's PID 1 was created
    (the agent container's own init, not the host boot)."""
    try:
        return int(time.time() - os.stat("/proc/1").st_ctime)
    except OSError:
        return int(time.time() - START_TIME)


def _uptime_str() -> str:
    secs = _container_uptime_seconds()
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _status_from_pct(pct: float, cfg: dict) -> str:
    if pct >= cfg["hard_pct"]:
        return "critical"
    if pct >= cfg["soft_pct"]:
        return "warning"
    return "ok"


def _next_threshold(pct: float, cfg: dict) -> str:
    soft = cfg["soft_pct"]
    hard = cfg["hard_pct"]
    if pct < soft:
        return f"soft @ {soft:.0f}%"
    if pct < hard:
        return f"hard @ {hard:.0f}%"
    return "over hard"


def _log_sample(pct: float, tokens: int) -> None:
    entry = {
        "t": dt.datetime.now().isoformat(timespec="seconds"),
        "pct": round(pct, 2),
        "tokens": tokens,
    }
    try:
        with open(HISTORY_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _timeseries(bucket_minutes: int = 5, limit: int = 24) -> list[dict]:
    """Bucket both context-% samples and SDK turn USAGE lines into the same
    fixed-size time buckets, so the dashboard can render them as aligned
    multi-bar groups under one x-axis.

    Each bucket returns:
      time (HH:MM bucket start), pct (avg context % in window),
      dur_min / dur_avg / dur_max (seconds across all turns in window).
    """
    from datetime import datetime as _dt
    bucket_s = max(60, bucket_minutes * 60)

    def _floor(ts: float) -> float:
        return (ts // bucket_s) * bucket_s

    # --- context % samples
    pct_buckets: dict[float, list[float]] = {}
    if HISTORY_LOG.exists():
        try:
            for line in HISTORY_LOG.read_text().splitlines()[-2000:]:
                try:
                    d = json.loads(line)
                    ts = _dt.fromisoformat(d["t"]).timestamp()
                    pct_buckets.setdefault(_floor(ts), []).append(float(d["pct"]))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except OSError:
            pass

    # --- SDK turns (from USAGE lines)
    dur_buckets: dict[float, list[float]] = {}
    for t in _perf_turns(limit=1000):
        try:
            ts = _dt.fromisoformat(t["ts"]).timestamp()
            dur_buckets.setdefault(_floor(ts), []).append(float(t["duration_s"]))
        except ValueError:
            continue

    keys = sorted(set(pct_buckets.keys()) | set(dur_buckets.keys()))
    if not keys:
        return []

    # Produce a continuous series of 5-min slots from earliest to "now" (floored).
    # This keeps the dashboard chart aligned: every x-tick is a real time slot,
    # empty slots show no duration bars but keep the context % carried forward
    # so the area doesn't collapse to zero during quiet windows.
    start = keys[0]
    end = _floor(time.time())
    stride = bucket_s
    all_keys: list[float] = []
    k = start
    while k <= end:
        all_keys.append(k)
        k += stride

    out: list[dict] = []
    last_pct: float | None = None
    for k in all_keys:
        pcts = pct_buckets.get(k, [])
        durs = dur_buckets.get(k, [])
        if pcts:
            last_pct = sum(pcts) / len(pcts)
        entry: dict = {
            "time": _dt.fromtimestamp(k).strftime("%H:%M"),
            "pct": round(last_pct, 2) if last_pct is not None else None,
        }
        if durs:
            entry["dur_min"] = round(min(durs), 1)
            entry["dur_avg"] = round(sum(durs) / len(durs), 1)
            entry["dur_max"] = round(max(durs), 1)
            entry["turn_count"] = len(durs)
        out.append(entry)
    return out[-limit:]


def _read_history(limit: int = 20) -> list[dict]:
    if not HISTORY_LOG.exists():
        return []
    try:
        lines = HISTORY_LOG.read_text().strip().splitlines()[-limit:]
    except OSError:
        return []
    out: list[dict] = []
    history_stamps: list[str] = []  # full YYYY-MM-DD HH:MM:SS for matching
    for line in lines:
        try:
            d = json.loads(line)
            full_ts = d["t"].replace("T", " ")[:19]
            out.append({"time": d["t"][11:16], "percentage": float(d["pct"])})
            history_stamps.append(full_ts)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    # Enrich each history sample with the duration from the nearest USAGE line
    # (real turn, not interrupt). Match by absolute time within ±90 seconds so
    # the two bar charts can be rendered on the same x-axis with 1:1 alignment.
    if out:
        turns = _perf_turns(limit=500)
        if turns:
            from datetime import datetime as _dt
            def _parse(s: str) -> float:
                try:
                    return _dt.fromisoformat(s).timestamp()
                except ValueError:
                    return 0.0
            turn_ts = [(_parse(t["ts"]), t) for t in turns]
            for i, entry in enumerate(out):
                target = _parse(history_stamps[i])
                if not target:
                    continue
                best = None
                best_diff = 90.0  # seconds window
                for ts_val, t in turn_ts:
                    diff = abs(ts_val - target)
                    if diff <= best_diff:
                        best_diff = diff
                        best = t
                if best is not None:
                    entry["duration_s"] = round(best["duration_s"], 1)
                    entry["out_tok"] = best["out_tok"]
    return out


def _trim_history(max_lines: int = 500) -> None:
    if not HISTORY_LOG.exists():
        return
    try:
        lines = HISTORY_LOG.read_text().strip().splitlines()
        if len(lines) > max_lines:
            HISTORY_LOG.write_text("\n".join(lines[-max_lines:]) + "\n")
    except OSError:
        pass


def _trigger_nap(reason: str) -> bool:
    """Write the nap_request file unless the trigger is already queued
    or the cooldown has not elapsed. Returns True if a new trigger was
    written."""
    global _last_nap_trigger_ts
    cfg = _load_config()
    cooldown = cfg.get("cooldown_minutes", 10) * 60
    now = time.time()
    if NAP_TRIGGER.exists():
        return False
    if now - _last_nap_trigger_ts < cooldown:
        return False
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        NAP_TRIGGER.write_text(f"{dt.datetime.now().isoformat()} {reason}\n")
        _last_nap_trigger_ts = now
        print(f"[context-server] nap triggered: {reason}", flush=True)
        return True
    except OSError as e:
        print(f"[context-server] failed to write nap trigger: {e}", flush=True)
        return False


def _build_snapshot() -> dict:
    cfg = _load_config()
    usage = _latest_usage()
    if not usage:
        pct, tok, max_tok = 0.0, 0, 1_000_000
    else:
        pct = usage["pct"]
        tok = usage["tok"]
        max_tok = usage["max"]
    idle = _last_user_activity_seconds()
    return {
        "percentage": round(pct, 2),
        "tokens": tok,
        "max_tokens": max_tok,
        "nap_status": _status_from_pct(pct, cfg),
        "next_threshold": _next_threshold(pct, cfg),
        "uptime": _uptime_str(),
        "history": _read_history(),
        "timeseries": _timeseries(bucket_minutes=5, limit=24),
        "nap": {
            "config": cfg,
            "idle_seconds": None if idle is None else int(idle),
            "trigger_pending": NAP_TRIGGER.exists(),
        },
    }


def _write_user_idle_notification(idle_seconds: float, threshold_minutes: int) -> None:
    """Drop a passive notification so the agent learns the user has gone idle."""
    try:
        NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
        notif = {
            "source": "context",
            "type": "user_idle",
            "idle_seconds": int(idle_seconds),
            "idle_minutes": int(idle_seconds // 60),
            "threshold_minutes": threshold_minutes,
            "interrupt": False,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        filename = f"{int(time.time() * 1e6)}-context-user_idle.json"
        tmp = NOTIFICATIONS_DIR / f"{filename}.tmp"
        tmp.write_text(json.dumps(notif, indent=2))
        os.replace(tmp, NOTIFICATIONS_DIR / filename)
        print(f"[context-server] user-idle notification written (idle={int(idle_seconds)}s)", flush=True)
    except OSError as e:
        print(f"[context-server] failed to write user-idle notification: {e}", flush=True)


def _check_user_idle(cfg: dict) -> None:
    """Drop a one-shot passive notification when the user crosses the idle
    threshold. The flag resets once the user becomes active again, but a
    minimum inter-notification interval prevents re-firing while the user
    stays idle and the agent's own replies briefly reset the activity mtime."""
    global _user_idle_notified
    minutes = int(cfg.get("user_idle_notify_minutes", 0) or 0)
    if minutes <= 0:
        _user_idle_notified = False
        return
    idle = _last_user_activity_seconds()
    if idle is None:
        return
    threshold_seconds = minutes * 60
    now = time.time()
    last_ts = _read_last_idle_notified()
    if idle >= threshold_seconds:
        if not _user_idle_notified and (now - last_ts) >= _USER_IDLE_MIN_INTERVAL_S:
            _write_user_idle_notification(idle, minutes)
            _user_idle_notified = True
            _write_last_idle_notified(now)
    else:
        _user_idle_notified = False


_USAGE_PERF_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) .*?\[USAGE\] "
    r"in=(?P<in_tok>\d+) out=(?P<out_tok>\d+) "
    r"cache_read=(?P<cr>\d+) cache_write=(?P<cw>\d+) \| "
    r"cost=\$(?P<cost>[\d.]+) \| duration=(?P<dur>[\d.]+)s"
)


def _perf_turns(limit: int = 60) -> list[dict]:
    """Return the last N real agent turns with duration + token stats.

    Skips interrupt cycles (in=0 out=0) and caller can tune the window.
    """
    if not VESTA_LOG.exists():
        return []
    try:
        with open(VESTA_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 512_000)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []

    turns: list[dict] = []
    for line in data.splitlines():
        m = _USAGE_PERF_RE.search(line)
        if not m:
            continue
        in_tok = int(m.group("in_tok"))
        out_tok = int(m.group("out_tok"))
        if in_tok == 0 and out_tok == 0:
            continue  # interrupt cycle, not a real turn
        turns.append({
            "ts": m.group("ts"),
            "in_tok": in_tok,
            "out_tok": out_tok,
            "cache_read": int(m.group("cr")),
            "cache_write": int(m.group("cw")),
            "cost": float(m.group("cost")),
            "duration_s": float(m.group("dur")),
        })
    return turns[-limit:]


_ACTIVITY_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"\[(?P<level>\w+)\] "
    r"(?P<marker>[<>*!]) "
    r"\[(?P<actor>\w+)\] - \[(?P<kind>[A-Z_ ]+)\] ?"
    r"(?P<rest>.*)$"
)


def _activity_feed(limit: int = 30) -> list[dict]:
    """Tail vesta.log, parse recent events into a compact activity feed.

    Excludes cost/usage lines (there's a separate widget for that) and
    drops [ASSISTANT] text that was immediately echoed via `app-chat send`
    or `whatsapp send` (the user already saw it in chat).
    """
    if not VESTA_LOG.exists():
        return []
    try:
        with open(VESTA_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 256_000)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []

    raw = []
    for line in data.splitlines():
        m = _ACTIVITY_LINE_RE.match(line)
        if not m:
            continue
        kind = m.group("kind").strip()
        actor = m.group("actor")
        rest = m.group("rest").strip()
        if kind == "USAGE":
            continue
        if kind == "MESSAGE" and rest.startswith("{"):
            # Raw SDK init payloads, skip.
            continue
        raw.append({
            "ts": m.group("ts"),
            "actor": actor,
            "kind": kind,
            "text": rest,
        })

    # Pair [ASSISTANT] lines with nearby `app-chat send` / `whatsapp send`
    # tool calls. If the assistant text reached a user channel, skip it.
    chatted = set()
    for i, ev in enumerate(raw):
        if ev["kind"] != "ASSISTANT":
            continue
        assistant_text = ev["text"].strip().lower()[:80]
        for j in range(i + 1, min(i + 8, len(raw))):
            nxt = raw[j]
            if nxt["kind"] != "TOOL CALL":
                continue
            t = nxt["text"]
            if "app-chat send" in t or "whatsapp send" in t:
                # crude: if assistant text appears verbatim in the send call, it's
                # clearly a mirror. otherwise still treat as chatted (conservative).
                snippet = assistant_text[:40]
                if snippet and snippet in t.lower():
                    chatted.add(i)
                    break
                chatted.add(i)
                break
            # if another assistant line appears first, break
            if nxt["kind"] == "ASSISTANT":
                break

    out: list[dict] = []
    for i, ev in enumerate(raw):
        if i in chatted:
            continue
        # Trim to avoid huge payloads
        text = ev["text"]
        if len(text) > 400:
            text = text[:400] + "…"
        out.append({
            "ts": ev["ts"],
            "kind": ev["kind"],
            "text": text,
        })

    return out[-limit:]


def _sampler_loop():
    """Every minute: sample history, and auto-trigger nap if thresholds met."""
    last_tok = -1
    while True:
        try:
            usage = _latest_usage()
            if usage and usage["tok"] != last_tok:
                _log_sample(usage["pct"], usage["tok"])
                _trim_history()
                last_tok = usage["tok"]

            cfg = _load_config()
            _check_user_idle(cfg)
            if usage and cfg.get("enabled", True):
                pct = usage["pct"]
                if pct >= cfg["hard_pct"]:
                    _trigger_nap(f"hard threshold ({pct:.1f}% >= {cfg['hard_pct']}%)")
                elif pct >= cfg["soft_pct"]:
                    idle = _last_user_activity_seconds()
                    idle_threshold = cfg["idle_minutes"] * 60
                    if idle is not None and idle >= idle_threshold:
                        _trigger_nap(
                            f"soft threshold ({pct:.1f}% >= {cfg['soft_pct']}%) "
                            f"and idle for {int(idle)}s"
                        )
        except Exception as e:
            print(f"[context-server] sampler error: {e}", flush=True)
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0].strip("/")
        if path in ("", "status"):
            self._send(200, _build_snapshot())
        elif path == "config":
            self._send(200, _load_config())
        elif path == "perf":
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            limit = 60
            for pair in q.split("&"):
                if pair.startswith("limit="):
                    try: limit = max(1, min(500, int(pair.split("=", 1)[1])))
                    except ValueError: pass
            self._send(200, {"turns": _perf_turns(limit)})
        elif path == "activity":
            # Optional ?limit=N
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            limit = 30
            for pair in q.split("&"):
                if pair.startswith("limit="):
                    try: limit = max(1, min(200, int(pair.split("=", 1)[1])))
                    except ValueError: pass
            self._send(200, {"events": _activity_feed(limit)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0].strip("/")
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        if path == "nap":
            ok = _trigger_nap("manual")
            self._send(200 if ok else 409, {"triggered": ok})
            return
        if path == "config":
            try:
                patch = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid json"})
                return
            cfg = _load_config()
            cfg.update({k: v for k, v in patch.items() if k in DEFAULT_CONFIG})
            _save_config(cfg)
            self._send(200, cfg)
            return
        self._send(404, {"error": "not found"})

    def _send(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._send(204, {})


def main():
    port = int(os.environ.get("SKILL_PORT", "8082"))
    if not CONFIG_PATH.exists():
        _save_config(DEFAULT_CONFIG)
    threading.Thread(target=_sampler_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[context-server] listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
