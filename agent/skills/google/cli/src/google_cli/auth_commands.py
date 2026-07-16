from . import auth
from .config import Config


def authenticate_account(config: Config) -> dict:
    flow_data = auth.start_auth_flow(config.credentials_file, config.scopes)
    return {
        "status": "authentication_required",
        "auth_url": flow_data["auth_url"],
        "message": (
            "Open the URL above in a browser and authorize.\n"
            "The browser will redirect to a local URL - copy the 'code' parameter from the URL.\n"
            "Then run: google auth complete --code <code>"
        ),
    }


def run_local_auth(config: Config) -> dict:
    try:
        creds = auth.run_local_server_flow(config.credentials_file, config.scopes, config.token_file)
        email = auth.get_user_email(creds)
        return {"status": "success", "email": email}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def complete_authentication(config: Config, *, code: str) -> dict:
    try:
        creds = auth.complete_auth_flow(config.credentials_file, config.scopes, code, config.token_file)
        email = auth.get_user_email(creds)
        return {"status": "success", "email": email}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_accounts(config: Config) -> list[dict]:
    if not config.token_file.exists():
        return []

    try:
        creds = auth.get_credentials(config.token_file, config.scopes)
        email = auth.get_user_email(creds)
        return [{"email": email}]
    except Exception:
        return []
