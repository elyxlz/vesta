import msal
import pathlib as pl
from typing import NamedTuple
from .settings import MicrosoftSettings


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


def get_app(cache_file: pl.Path, *, settings: MicrosoftSettings) -> msal.PublicClientApplication:
    if not settings.microsoft_mcp_client_id:
        raise ValueError("MICROSOFT_MCP_CLIENT_ID is required")

    authority = f"https://login.microsoftonline.com/{settings.microsoft_mcp_tenant_id}"

    cache = msal.SerializableTokenCache()
    cache_content = _read_cache(cache_file)
    if cache_content:
        cache.deserialize(cache_content)

    app = msal.PublicClientApplication(settings.microsoft_mcp_client_id, authority=authority, token_cache=cache)

    return app


def get_token(cache_file: pl.Path, scopes: list[str], settings: MicrosoftSettings, *, account_id: str | None = None) -> str:
    app = get_app(cache_file, settings=settings)

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
        _write_cache(cache_file, content=cache.serialize())

    return result["access_token"]


def list_accounts(cache_file: pl.Path, *, settings: MicrosoftSettings) -> list[Account]:
    app = get_app(cache_file, settings=settings)
    seen_usernames = set()
    accounts = []
    for a in app.get_accounts():
        username = a["username"]
        if username not in seen_usernames:
            seen_usernames.add(username)
            accounts.append(Account(username=username, account_id=a["home_account_id"]))
    return accounts


def get_account_id_by_email(email: str, cache_file: pl.Path, *, settings: MicrosoftSettings) -> str:
    """Map email address to account_id. Raises ValueError if email not found."""
    accounts = list_accounts(cache_file, settings=settings)
    email_lower = email.lower()
    for account in accounts:
        if account.username.lower() == email_lower:
            return account.account_id

    if accounts:
        available = ", ".join([f"'{acc.username}'" for acc in accounts])
        raise ValueError(f"No account found with email '{email}'. Available accounts: {available}. Use list_accounts() to see all.")
    else:
        raise ValueError(f"No account found with email '{email}'. No accounts are authenticated. Use authenticate_account() to add an account.")


def authenticate_new_account(cache_file: pl.Path, scopes: list[str], *, settings: MicrosoftSettings) -> Account | None:
    """Authenticate a new account interactively"""
    app = get_app(cache_file, settings=settings)

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
        _write_cache(cache_file, content=cache.serialize())

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
