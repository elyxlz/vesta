import json
import time
from base64 import b64encode

import httpx

from .config import Config

TOKEN_URL = "https://zoom.us/oauth/token"


def get_token(config: Config) -> str:
    cached = _load_cached_token(config)
    if cached:
        return cached

    creds = config.load_credentials()
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]
    account_id = creds["account_id"]

    basic = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = httpx.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}"},
        data={"grant_type": "account_credentials", "account_id": account_id},
    )
    resp.raise_for_status()
    data = resp.json()

    token = data["access_token"]
    expires_at = time.time() + data["expires_in"] - 60

    config.token_cache_file.write_text(json.dumps({"access_token": token, "expires_at": expires_at}))
    return token


def _load_cached_token(config: Config) -> str | None:
    try:
        data = json.loads(config.token_cache_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if time.time() >= data["expires_at"]:
        return None
    return data["access_token"]
