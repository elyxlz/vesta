import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

LOOPBACK_PORT = 8097
REDIRECT_URI = f"http://127.0.0.1:{LOOPBACK_PORT}"


def start_auth_flow(credentials_file: Path, scopes: list[str]) -> dict:
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return {"auth_url": auth_url}


def complete_auth_flow(credentials_file: Path, scopes: list[str], code: str, token_file: Path) -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_token(token_file, creds)
    return creds


def run_local_server_flow(credentials_file: Path, scopes: list[str], token_file: Path) -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    creds = flow.run_local_server(port=LOOPBACK_PORT, open_browser=False)
    _save_token(token_file, creds)
    return creds


def get_credentials(token_file: Path, credentials_file: Path, scopes: list[str]) -> Credentials:
    if not token_file.exists():
        raise ValueError("Not authenticated. Run 'google auth login' first.")

    creds = _load_token(token_file, scopes)

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(token_file, creds)
        return creds

    raise ValueError("Token expired and cannot be refreshed. Run 'google auth login' again.")


def get_user_email(creds: Credentials) -> str:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def _save_token(token_file: Path, creds: Credentials) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }
    token_file.write_text(json.dumps(token_data, indent=2))


def _load_token(token_file: Path, scopes: list[str]) -> Credentials:
    data = json.loads(token_file.read_text())
    return Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=scopes,
    )
