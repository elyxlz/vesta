"""Authentication commands for Microsoft CLI."""

import json

from . import auth
from .config import Config
from .settings import MicrosoftSettings


def list_accounts(config: Config) -> list[dict[str, str]]:
    settings = MicrosoftSettings()
    return [{"email": acc.username, "account_id": acc.account_id} for acc in auth.list_accounts(config.cache_file, settings=settings)]


def authenticate_account(config: Config) -> dict[str, str]:
    settings = MicrosoftSettings()
    app = auth.get_app(config.cache_file, settings=settings)
    flow = app.initiate_device_flow(scopes=config.scopes)

    if "user_code" not in flow:
        error_msg = flow["error_description"] if "error_description" in flow else "Unknown error"
        raise Exception(f"Failed to get device code: {error_msg}")

    verification_url = (
        flow["verification_uri"]
        if "verification_uri" in flow
        else (flow["verification_url"] if "verification_url" in flow else "https://microsoft.com/devicelogin")
    )

    return {
        "status": "authentication_required",
        "instructions": "To authenticate a new Microsoft account:",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": "Sign in with the Microsoft account you want to add",
        "step4": "After authenticating, use 'microsoft auth complete' to finish",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow["expires_in"] if "expires_in" in flow else 900,
        "_flow_cache": json.dumps(flow),
    }


def complete_authentication(config: Config, *, flow_cache: str) -> dict[str, str]:
    settings = MicrosoftSettings()

    try:
        flow = json.loads(flow_cache)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Invalid flow cache data")

    app = auth.get_app(config.cache_file, settings=settings)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {
                "status": "pending",
                "message": "Authentication is still pending.",
            }
        raise Exception(f"Authentication failed: {error_msg}")

    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(config.cache_file, content=cache.serialize())

    accounts = app.get_accounts()
    if accounts:
        for account in accounts:
            claims = result["id_token_claims"] if "id_token_claims" in result else {}
            if (account["username"] if "username" in account else "").lower() == (
                claims["preferred_username"] if "preferred_username" in claims else ""
            ).lower():
                return {
                    "status": "success",
                    "username": account["username"],
                    "account_id": account["home_account_id"],
                    "message": f"Successfully authenticated {account['username']}",
                }
        account = accounts[-1]
        return {
            "status": "success",
            "username": account["username"],
            "account_id": account["home_account_id"],
            "message": f"Successfully authenticated {account['username']}",
        }

    return {"status": "error", "message": "Authentication succeeded but no account was found"}
