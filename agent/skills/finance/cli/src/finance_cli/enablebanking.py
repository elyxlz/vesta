"""Enable Banking API client with RS256 JWT auth."""

import json
import sys
import uuid
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt as pyjwt

BASE_URL = "https://api.enablebanking.com"
CALLBACK_PORT = 7866
CALLBACK_PATH = "/callback"
REDIRECT_URL = f"https://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"

# Consent valid for 90 days by default
CONSENT_DAYS = 90

# Bank to connect — set to your bank's ASPSP name and country code.
# For EU banks use the country of the licensed entity (e.g. "LT" for Revolut Bank UAB).
# Run `finance auth login` to browse available ASPSPs via the Enable Banking portal.
ASPSP_NAME = "YourBank"
ASPSP_COUNTRY = "GB"


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_jwt(app_id: str, key_path: str) -> str:
    """Generate a fresh RS256 JWT for API authentication."""
    pem = Path(key_path).read_bytes()
    iat = int(datetime.now(UTC).timestamp())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": iat,
        "exp": iat + 3600,
    }
    token = pyjwt.encode(
        payload,
        pem,
        algorithm="RS256",
        headers={"kid": app_id},
    )
    return token


def _headers(conf: dict) -> dict:
    token = _make_jwt(conf["app_id"], conf["key_path"])
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Low-level request helpers
# ---------------------------------------------------------------------------


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    if resp.is_error:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        print(
            json.dumps(
                {
                    "error": f"Enable Banking API error ({context})",
                    "status": resp.status_code,
                    "body": body,
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def _get(conf: dict, path: str, params: dict | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    resp = httpx.get(url, headers=_headers(conf), params=params, timeout=30)
    _raise_for_status(resp, f"GET {path}")
    return resp.json()


def _post(conf: dict, path: str, body: dict) -> Any:
    url = f"{BASE_URL}{path}"
    resp = httpx.post(url, headers=_headers(conf), json=body, timeout=30)
    _raise_for_status(resp, f"POST {path}")
    return resp.json()


def _delete(conf: dict, path: str) -> Any:
    url = f"{BASE_URL}{path}"
    resp = httpx.delete(url, headers=_headers(conf), timeout=30)
    _raise_for_status(resp, f"DELETE {path}")
    # Some endpoints return empty body on success
    if resp.content:
        return resp.json()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------


def initiate_auth(conf: dict) -> tuple[str, str]:
    """
    POST /auth to start the bank authorization flow.
    Returns (auth_url, state).

    Edit ASPSP_NAME and ASPSP_COUNTRY at the top of this file to match your bank.
    Use the Enable Banking portal to find available ASPSPs for your country.
    """
    state = str(uuid.uuid4())
    valid_until = (datetime.now(UTC) + timedelta(days=CONSENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": ASPSP_NAME, "country": ASPSP_COUNTRY},
        "state": state,
        "redirect_url": REDIRECT_URL,
        "psu_type": "personal",
    }
    data = _post(conf, "/auth", body)
    auth_url = data.get("url", "")
    if not auth_url:
        print(
            json.dumps({"error": "No URL in /auth response", "response": data}),
            file=sys.stderr,
        )
        sys.exit(1)
    return auth_url, state


def exchange_code(conf: dict, code: str) -> dict:
    """
    POST /sessions with the code received from the OAuth callback.
    Returns session data including session_id and accounts list.
    """
    data = _post(conf, "/sessions", {"code": code})
    return data


def get_session(conf: dict) -> dict:
    """GET /sessions/{session_id} — fetch current session details."""
    session_id = conf["session_id"]
    return _get(conf, f"/sessions/{session_id}")


def revoke_session(conf: dict) -> dict:
    """DELETE /sessions/{session_id}."""
    session_id = conf["session_id"]
    return _delete(conf, f"/sessions/{session_id}")


# ---------------------------------------------------------------------------
# Account & balance endpoints
# ---------------------------------------------------------------------------


def list_aspsps(conf: dict, country: str = "GB") -> list[dict]:
    """GET /aspsps — list available banks."""
    data = _get(conf, "/aspsps", params={"country": country, "psu_type": "personal"})
    if isinstance(data, list):
        return data
    return data.get("aspsps", data)


def get_balances(conf: dict, account_uid: str) -> list[dict]:
    """GET /accounts/{uid}/balances."""
    data = _get(conf, f"/accounts/{account_uid}/balances")
    if isinstance(data, list):
        return data
    return data.get("balances", [data])


def get_transactions(
    conf: dict,
    account_uid: str,
    date_from: str,
    date_to: str | None = None,
) -> list[dict]:
    """
    GET /accounts/{uid}/transactions with full pagination.
    date_from / date_to are YYYY-MM-DD strings.
    """
    params: dict = {"date_from": date_from}
    if date_to:
        params["date_to"] = date_to

    all_txns: list[dict] = []

    while True:
        data = _get(conf, f"/accounts/{account_uid}/transactions", params=params)

        if isinstance(data, list):
            # Some implementations return a plain list
            all_txns.extend(data)
            break

        txns = data.get("transactions", [])
        all_txns.extend(txns)

        continuation_key = data.get("continuation_key")
        if not continuation_key:
            break

        # Subsequent pages use continuation_key instead of date params
        params = {"continuation_key": continuation_key}

    return all_txns


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def aggregate_by_category(transactions: list[dict]) -> dict:
    """
    Group transactions by merchant/category, summing debit amounts.
    Enable Banking transaction objects typically have:
      - credit_debit_indicator: "DBIT" or "CRDT"
      - transaction_amount.amount (string)
      - transaction_amount.currency
      - remittance_information (merchant name / description)
      - creditor_name
      - bank_transaction_code.proprietary.code (category hint)
    """
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}

    for tx in transactions:
        indicator = tx.get("credit_debit_indicator", "DBIT")
        if indicator == "CRDT":
            # Income / credit — skip for spending summary
            continue

        amt_obj = tx.get("transaction_amount") or {}
        try:
            amount = float(amt_obj.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0

        # Try to derive a category label
        category = _extract_category(tx)

        totals[category] = totals.get(category, 0.0) + amount
        counts[category] = counts.get(category, 0) + 1

    summary = []
    for cat in sorted(totals, key=lambda c: totals[c], reverse=True):
        summary.append(
            {
                "category": cat,
                "total": round(totals[cat], 2),
                "count": counts[cat],
            }
        )

    return {
        "categories": summary,
        "grand_total": round(sum(totals.values()), 2),
        "transaction_count": sum(counts.values()),
    }


def _extract_category(tx: dict) -> str:
    """Best-effort category extraction from an Enable Banking transaction."""
    # Try proprietary bank code (e.g. "PURCHASE", "TRANSFER", etc.)
    btc = tx.get("bank_transaction_code") or {}
    proprietary = btc.get("proprietary") or {}
    code = proprietary.get("code", "")
    if code:
        return code.title()

    # Fall back to creditor name
    creditor = tx.get("creditor_name", "")
    if creditor:
        return creditor

    # Remittance information as last resort
    remittance = tx.get("remittance_information")
    if isinstance(remittance, list) and remittance:
        return remittance[0]
    if isinstance(remittance, str) and remittance:
        return remittance

    return "Other"


# ---------------------------------------------------------------------------
# Local HTTPS callback server (Enable Banking requires https:// redirect URLs)
# ---------------------------------------------------------------------------


def _generate_self_signed_cert() -> tuple[str, str]:
    """Generate a temporary self-signed cert for the localhost callback server."""
    import tempfile
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    cert_file.close()

    key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    key_file.write(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_file.close()

    return cert_file.name, key_file.name


def wait_for_callback(port: int = CALLBACK_PORT) -> str:
    """
    Spin up a minimal HTTPS server on *port*, wait for a single GET /callback
    request, extract the `code` query parameter, return it.
    Uses a self-signed cert for localhost (browser will show warning but works).
    """
    import os
    import ssl
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received_code: list[str] = []

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            if "error" in qs:
                error = qs["error"][0]
                desc = qs.get("error_description", [""])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Error: {error} — {desc}".encode())
                print(
                    json.dumps({"error": f"Auth error: {error}", "description": desc}),
                    file=sys.stderr,
                )
                sys.exit(1)

            if "code" not in qs:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"No code parameter in callback.")
                return

            received_code.append(qs["code"][0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2><p>You can close this tab and return to the terminal.</p></body></html>"
            )

        def log_message(self, format, *args):  # noqa: A002
            # Suppress default request logging
            pass

    cert_path, key_path = _generate_self_signed_cert()
    try:
        server = HTTPServer(("localhost", port), CallbackHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        server.handle_request()  # blocks until one request is received
        server.server_close()
    finally:
        os.unlink(cert_path)
        os.unlink(key_path)

    if not received_code:
        print(json.dumps({"error": "No authorization code received"}), file=sys.stderr)
        sys.exit(1)

    return received_code[0]
