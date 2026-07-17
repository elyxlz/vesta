import pathlib as pl
from typing import NamedTuple

import msal

from .settings import get_settings


class Account(NamedTuple):
    username: str
    account_id: str


def _read_cache(cache_file: pl.Path) -> str | None:
    try:
        return cache_file.read_text()
    except FileNotFoundError:
        return None


def _write_cache(cache_file: pl.Path, *, content: str) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(content)


def _run_device_flow(app: msal.PublicClientApplication, scopes: list[str], cache_file: pl.Path) -> dict:
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise Exception(f"Failed to get device code: {flow['error_description'] if 'error_description' in flow else 'Unknown error'}")

    verification_uri = (
        (flow["verification_uri"] if "verification_uri" in flow else None)
        or (flow["verification_url"] if "verification_url" in flow else None)
        or "https://microsoft.com/devicelogin"
    )
    print(f"\nTo authenticate:\n1. Visit {verification_uri}\n2. Enter code: {flow['user_code']}")

    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        raise Exception(f"Auth failed: {result['error_description'] if 'error_description' in result else result['error']}")

    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        _write_cache(cache_file, content=cache.serialize())

    return result


def get_app(cache_file: pl.Path, client_id: str | None = None) -> msal.PublicClientApplication:
    settings = get_settings()
    authority = f"https://login.microsoftonline.com/{settings.microsoft_mcp_tenant_id}"

    cache = msal.SerializableTokenCache()
    cache_content = _read_cache(cache_file)
    if cache_content:
        cache.deserialize(cache_content)

    return msal.PublicClientApplication(client_id or settings.microsoft_mcp_client_id, authority=authority, token_cache=cache)


def get_token_silent(cache_file: pl.Path, scopes: list[str], *, account_id: str | None = None, client_id: str | None = None) -> str | None:
    """Acquire a token from the cache without ever prompting; return None if none is available.

    Used by the OWA REST fallback: after a device-flow `owa-login`, MSAL holds the refresh
    token, so a fresh access token is minted silently on each call with no browser and no
    re-auth (the cache is persisted on rotation, same as get_token)."""
    app = get_app(cache_file, client_id)
    accounts = app.get_accounts()
    account = next((a for a in accounts if a["home_account_id"] == account_id), None) if account_id else (accounts[0] if accounts else None)
    if account is None:
        return None
    result = app.acquire_token_silent(scopes, account=account)
    if not result:
        return None
    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        _write_cache(cache_file, content=cache.serialize())
    return result["access_token"]


def account_in_cache(cache_file: pl.Path, account_email: str, *, client_id: str | None = None) -> bool:
    """Local, network-free check: is this account present in the MSAL cache?"""
    app = get_app(cache_file, client_id)
    return any((a["username"] or "").lower() == account_email.lower() for a in app.get_accounts())


def get_token(cache_file: pl.Path, scopes: list[str], *, account_id: str | None = None) -> str:
    app = get_app(cache_file)

    accounts = app.get_accounts()
    account = next((a for a in accounts if a["home_account_id"] == account_id), None) if account_id else (accounts[0] if accounts else None)

    result = app.acquire_token_silent(scopes, account=account)

    if not result:
        result = _run_device_flow(app, scopes, cache_file)
    else:
        # Persist the cache after a silent acquisition. MSAL rotates the refresh
        # token in-memory on refresh; if we never write it back, the on-disk token
        # is never renewed, so its 90-day inactivity clock never advances and it
        # eventually dies with AADSTS700082 even under constant daemon polling.
        cache = app.token_cache
        if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
            _write_cache(cache_file, content=cache.serialize())

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


def get_account_id_by_email(email: str, cache_file: pl.Path) -> str:
    """Map email address to account_id. Raises ValueError if email not found."""
    accounts = list_accounts(cache_file)
    email_lower = email.lower()
    for account in accounts:
        if account.username.lower() == email_lower:
            return account.account_id

    if accounts:
        available = ", ".join([f"'{acc.username}'" for acc in accounts])
        raise ValueError(f"No account found with email '{email}'. Available accounts: {available}. Use list_accounts() to see all.")
    raise ValueError(f"No account found with email '{email}'. No accounts are authenticated. Use authenticate_account() to add an account.")


def authenticate_new_account(cache_file: pl.Path, scopes: list[str]) -> Account | None:
    """Authenticate a new account interactively"""
    app = get_app(cache_file)
    result = _run_device_flow(app, scopes, cache_file)

    # Get the newly added account
    accounts = app.get_accounts()
    if accounts:
        # Find the account that matches the token we just got
        for account in accounts:
            claims = result["id_token_claims"] if "id_token_claims" in result else {}
            if (account["username"] if "username" in account else "").lower() == (
                claims["preferred_username"] if "preferred_username" in claims else ""
            ).lower():
                return Account(username=account["username"], account_id=account["home_account_id"])
        # If exact match not found, return the last account
        account = accounts[-1]
        return Account(username=account["username"], account_id=account["home_account_id"])

    return None
