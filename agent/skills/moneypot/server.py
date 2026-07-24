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
import hmac
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import moneypot as mp

LOCK = threading.Lock()


def _write(fn):
    with LOCK:
        data = mp.load()
        result = fn(data)
        mp.save(data)
        return result


class Handler(BaseHTTPRequestHandler):
    server_version = "moneypot/1.0"

    def log_message(self, _format, *_args):
        return

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        """Allow health checks and credentials matching the app or agent key."""
        if urlparse(self.path).path.rstrip("/") in ("/health", ""):
            return True
        valid = [credential for credential in (self.server.api_key, self.server.agent_token) if credential]
        if not valid:
            return True
        presented = []
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            presented.append(auth[7:].strip())
        for h in ("X-API-Key", "X-Agent-Token"):
            v = self.headers.get(h, "").strip()
            if v:
                presented.append(v)
        return any(hmac.compare_digest(candidate, credential) for candidate in presented for credential in valid)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            d = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise mp.MoneypotError("invalid JSON body") from exc
        if not isinstance(d, dict):
            raise mp.MoneypotError("body must be a JSON object")
        return d

    # -------- routing --------

    def do_GET(self):
        self._dispatch(self._route_get)

    def do_POST(self):
        self._dispatch(self._route_post)

    def do_DELETE(self):
        self._dispatch(self._route_delete)

    def _dispatch(self, route):
        if not self._authed():
            return self._send(401, {"error": "missing or invalid API key"})
        try:
            route()
        except mp.MoneypotError as exc:
            self._send(400, {"error": str(exc)})
        except (KeyError, OSError, TypeError) as exc:
            self.log_error("request failed: %s", exc)
            self._send(500, {"error": "internal server error"})
        return None

    def _route_get(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)
        if path == "/health":
            code, payload = 200, {"ok": True, "service": "moneypot"}
        elif path == "/pots":
            data = mp.load()
            payload = [
                {"id": pid, **{k: v for k, v in p.items() if k != "entries"}, "entries": len(p["entries"])} for pid, p in data["pots"].items()
            ]
            code = 200
        elif match := re.fullmatch(r"/pots/([^/]+)", path):
            data = mp.load()
            code, payload = 200, mp.get_pot(data, match.group(1))
        elif match := re.fullmatch(r"/pots/([^/]+)/entries", path):
            data = mp.load()
            code, payload = 200, mp.get_pot(data, match.group(1))["entries"]
        elif match := re.fullmatch(r"/pots/([^/]+)/balance", path):
            code, payload = 200, mp.balance(mp.load(), match.group(1))
        elif match := re.fullmatch(r"/pots/([^/]+)/contributions", path):
            acct = (q.get("account") or [None])[0]
            if not acct:
                raise mp.MoneypotError("?account= is required")
            code, payload = 200, mp.contributions(mp.load(), match.group(1), acct)
        else:
            code, payload = 404, {"error": f"no route GET {path}"}
        return self._send(code, payload)

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
                    mp.ExpenseRequest(
                        payer=b.get("payer"),
                        amount=b.get("amount"),
                        desc=b.get("desc", ""),
                        currency=b.get("currency"),
                        rate=b.get("rate"),
                        fetch=bool(b.get("fetch")),
                        for_list=b.get("for"),
                        split_map=b.get("split"),
                    ),
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
                    mp.TransferRequest(
                        sender=b.get("from"),
                        recipient=b.get("to"),
                        amount=b.get("amount"),
                        desc=b.get("desc", ""),
                        currency=b.get("currency"),
                        rate=b.get("rate"),
                        fetch=bool(b.get("fetch")),
                    ),
                )
            )
            return self._send(201, e)
        return self._send(404, {"error": f"no route POST {path}"})

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
        return self._send(404, {"error": f"no route DELETE {path}"})


class Server(ThreadingHTTPServer):
    def __init__(self, address, handler, api_key, agent_token):
        super().__init__(address, handler)
        self.api_key = api_key
        self.agent_token = agent_token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument(
        "--api-key",
        default=os.environ.get("MONEYPOT_API_KEY"),
        help="require this key on all routes except /health (also via MONEYPOT_API_KEY). Omit for an open API.",
    )
    args = ap.parse_args()
    api_key = args.api_key or None
    agent_token = os.environ.get("AGENT_TOKEN") or None
    srv = Server((args.host, args.port), Handler, api_key, agent_token)
    mode = "private (credential required)" if api_key or agent_token else "open (no auth configured)"
    print(f"moneypot API on {args.host}:{args.port} - {mode}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
