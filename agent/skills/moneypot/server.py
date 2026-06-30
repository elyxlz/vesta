#!/usr/bin/env python3
"""moneypot HTTP API - a thin JSON wrapper over the moneypot service layer.

Stdlib only. Shares the same ~/agent/data/moneypot.json as the CLI. Mutations are
serialized with a lock so concurrent requests don't clobber the file.

Run:  python3 server.py --port 8080
Then register the port with vestad to expose it (see SETUP.md).

Endpoints
  GET    /health
  GET    /pots                                list pots (summaries)
  POST   /pots                                {id, name?, currency?, members:[...]}
  GET    /pots/{id}                           full pot
  DELETE /pots/{id}                           delete pot
  GET    /pots/{id}/entries                   entry history
  POST   /pots/{id}/members                   {name}
  POST   /pots/{id}/expenses                  {payer, amount, desc?, currency?, rate?, fetch?, for?:[...], split?:{Name:amt}}
  POST   /pots/{id}/transfers                 {from, to, amount, desc?, currency?, rate?, fetch?}
  DELETE /pots/{id}/entries/{eid}             delete entry
  GET    /pots/{id}/balance                   balances + settle-up
  GET    /pots/{id}/contributions?account=X   joint-account view
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import moneypot as mp

LOCK = threading.Lock()

# When set (via --api-key or MONEYPOT_API_KEY), every request except /health must
# present a valid credential. Two credentials are accepted: the app key, and the
# vestad agent token (AGENT_TOKEN) so the request is reachable through vestad
# (e.g. the dashboard) without sharing the app key. When no app key is set, the
# API is open. Headers checked: Authorization: Bearer, X-API-Key, X-Agent-Token.
API_KEY = None
AGENT_TOKEN = None


def _read(data, fn):
    with LOCK:
        return fn(mp.load())


def _write(fn):
    with LOCK:
        data = mp.load()
        result = fn(data)
        mp.save(data)
        return result


class Handler(BaseHTTPRequestHandler):
    server_version = "moneypot/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        """True if allowed: no key configured, or a credential matching the app
        key or the vestad agent token."""
        if not API_KEY:
            return True
        if urlparse(self.path).path.rstrip("/") in ("/health", ""):
            return True
        valid = {k for k in (API_KEY, AGENT_TOKEN) if k}
        presented = set()
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            presented.add(auth[7:].strip())
        for h in ("X-API-Key", "X-Agent-Token"):
            v = self.headers.get(h, "").strip()
            if v:
                presented.add(v)
        return bool(presented & valid)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            raise mp.MoneypotError("invalid JSON body")
        if not isinstance(d, dict):
            raise mp.MoneypotError("body must be a JSON object")
        return d

    # -------- routing --------

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "missing or invalid API key"})
        try:
            self._route_get()
        except mp.MoneypotError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa
            self._send(500, {"error": str(e)})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "missing or invalid API key"})
        try:
            self._route_post()
        except mp.MoneypotError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa
            self._send(500, {"error": str(e)})

    def do_DELETE(self):
        if not self._authed():
            return self._send(401, {"error": "missing or invalid API key"})
        try:
            self._route_delete()
        except mp.MoneypotError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa
            self._send(500, {"error": str(e)})

    def _route_get(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)
        if path == "/health":
            return self._send(200, {"ok": True, "service": "moneypot"})
        if path == "/pots":
            data = mp.load()
            return self._send(
                200,
                [
                    {"id": pid, **{k: v for k, v in p.items() if k != "entries"}, "entries": len(p["entries"])}
                    for pid, p in data["pots"].items()
                ],
            )
        m = re.fullmatch(r"/pots/([^/]+)", path)
        if m:
            data = mp.load()
            return self._send(200, mp.get_pot(data, m.group(1)))
        m = re.fullmatch(r"/pots/([^/]+)/entries", path)
        if m:
            data = mp.load()
            return self._send(200, mp.get_pot(data, m.group(1))["entries"])
        m = re.fullmatch(r"/pots/([^/]+)/balance", path)
        if m:
            return self._send(200, mp.balance(mp.load(), m.group(1)))
        m = re.fullmatch(r"/pots/([^/]+)/contributions", path)
        if m:
            acct = (q.get("account") or [None])[0]
            if not acct:
                raise mp.MoneypotError("?account= is required")
            return self._send(200, mp.contributions(mp.load(), m.group(1), acct))
        self._send(404, {"error": f"no route GET {path}"})

    def _route_post(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        b = self._body()
        if path == "/pots":
            pot = _write(lambda d: mp.create_pot(d, b.get("id"), b.get("name"), b.get("currency", "GBP"), b.get("members")))
            return self._send(201, pot)
        m = re.fullmatch(r"/pots/([^/]+)/members", path)
        if m:
            pid = m.group(1)
            _write(lambda d: mp.add_member(d, pid, b.get("name")))
            return self._send(201, {"ok": True})
        m = re.fullmatch(r"/pots/([^/]+)/expenses", path)
        if m:
            pid = m.group(1)
            e = _write(
                lambda d: mp.add_expense(
                    d,
                    pid,
                    b.get("payer"),
                    b.get("amount"),
                    b.get("desc", ""),
                    b.get("currency"),
                    b.get("rate"),
                    bool(b.get("fetch")),
                    b.get("for"),
                    b.get("split"),
                )
            )
            return self._send(201, e)
        m = re.fullmatch(r"/pots/([^/]+)/transfers", path)
        if m:
            pid = m.group(1)
            e = _write(
                lambda d: mp.add_transfer(
                    d,
                    pid,
                    b.get("from"),
                    b.get("to"),
                    b.get("amount"),
                    b.get("desc", ""),
                    b.get("currency"),
                    b.get("rate"),
                    bool(b.get("fetch")),
                )
            )
            return self._send(201, e)
        self._send(404, {"error": f"no route POST {path}"})

    def _route_delete(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        m = re.fullmatch(r"/pots/([^/]+)/entries/(\d+)", path)
        if m:
            pid, eid = m.group(1), int(m.group(2))
            _write(lambda d: mp.remove_entry(d, pid, eid))
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"/pots/([^/]+)", path)
        if m:
            pid = m.group(1)

            def _del(d):
                mp.get_pot(d, pid)
                del d["pots"][pid]

            _write(_del)
            return self._send(200, {"ok": True})
        self._send(404, {"error": f"no route DELETE {path}"})


def main():
    global API_KEY, AGENT_TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument(
        "--api-key",
        default=os.environ.get("MONEYPOT_API_KEY"),
        help="require this key on all routes except /health (also via MONEYPOT_API_KEY). Omit for an open API.",
    )
    args = ap.parse_args()
    API_KEY = args.api_key or None
    AGENT_TOKEN = os.environ.get("AGENT_TOKEN") or None  # also accepted when an app key is set
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    mode = "private (api key required)" if API_KEY else "open (no auth)"
    print(f"moneypot API on {args.host}:{args.port} - {mode}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
