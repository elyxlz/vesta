import os
import msal
import pathlib as pl
from typing import NamedTuple


class Account(NamedTuple):
    username: str
    account_id: str


def _read_cache(cache_file: pl.Path) -> str | None:
    try:
        return cache_file.read_text()
    except FileNotFoundError:
        return None


def _write_cache(cache_file: pl.Path, content: str) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(content)


def get_app(cache_file: pl.Path) -> msal.PublicClientApplication:
    client_id = os.getenv("MICROSOFT_MCP_CLIENT_ID")
    if not client_id:
        raise ValueError("MICROSOFT_MCP_CLIENT_ID environment variable is required")

    tenant_id = os.getenv("MICROSOFT_MCP_TENANT_ID", "common")
    authority = f"https://login.microsoftonline.com/{tenant_id}"

    cache = msal.SerializableTokenCache()
    cache_content = _read_cache(cache_file)
    if cache_content:
        cache.deserialize(cache_content)

    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    return app


def get_token(cache_file: pl.Path, scopes: list[str], account_id: str | None = None) -> str:
    app = get_app(cache_file)

    accounts = app.get_accounts()
    account = next((a for a in accounts if a["home_account_id"] == account_id), None) if account_id else (accounts[0] if accounts else None)

    result = app.acquire_token_silent(scopes, account=account)

    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise Exception(f"Failed to get device code: {flow.get('error_description', 'Unknown error')}")
        verification_uri = flow.get("verification_uri") or flow.get("verification_url") or "https://microsoft.com/devicelogin"
        print(f"\nTo authenticate:\n1. Visit {verification_uri}\n2. Enter code: {flow['user_code']}")
        result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        raise Exception(f"Auth failed: {result.get('error_description', result['error'])}")

    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        _write_cache(cache_file, cache.serialize())

    return result["access_token"]


def list_accounts(cache_file: pl.Path) -> list[Account]:
    app = get_app(cache_file)
    seen_usernames = set()
    accounts = []
    for a in app.get_accounts():
        username = a["username"]
        if username not in seen_usernames:
            seen_usernames.add(username)
            accounts.append(Account(username=username, account_id=a["home_account_id"]))
    return accounts


def authenticate_new_account(cache_file: pl.Path, scopes: list[str]) -> Account | None:
    """Authenticate a new account interactively"""
    app = get_app(cache_file)

    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise Exception(f"Failed to get device code: {flow.get('error_description', 'Unknown error')}")

    print("\nTo authenticate:")
    print(f"1. Visit: {flow.get('verification_uri', flow.get('verification_url', 'https://microsoft.com/devicelogin'))}")
    print(f"2. Enter code: {flow['user_code']}")
    print("3. Sign in with your Microsoft account")
    print("\nWaiting for authentication...")

    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        raise Exception(f"Auth failed: {result.get('error_description', result['error'])}")

    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        _write_cache(cache_file, cache.serialize())

    # Get the newly added account
    accounts = app.get_accounts()
    if accounts:
        # Find the account that matches the token we just got
        for account in accounts:
            if account.get("username", "").lower() == result.get("id_token_claims", {}).get("preferred_username", "").lower():
                return Account(username=account["username"], account_id=account["home_account_id"])
        # If exact match not found, return the last account
        account = accounts[-1]
        return Account(username=account["username"], account_id=account["home_account_id"])

    return None
