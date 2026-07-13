import json
import tempfile
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .thunderbird_client import resolve_thunderbird_client

LOOPBACK_PORT = 8097
REDIRECT_URI = f"http://127.0.0.1:{LOOPBACK_PORT}"
VERIFIER_FILE = Path(tempfile.gettempdir()) / "google_auth_verifier.txt"

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_client_config() -> dict:
    """In-memory OAuth client config reusing Thunderbird's published public client.

    This is the zero-BYO default: no ``credentials.json`` and no Google Cloud
    project required. The id/secret come from the dynamic Thunderbird resolver
    (cache-only, hardcoded constant as floor) so an upstream client rotation is
    followed automatically by the daily self-heal.
    """
    client_id, client_secret = resolve_thunderbird_client()
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": ["http://127.0.0.1", "http://localhost"],
        }
    }


def _make_flow(credentials_file: Path, scopes: list[str]) -> InstalledAppFlow:
    """Build the OAuth flow.

    Default: reuse Thunderbird's published public client (no BYO app needed).
    Optional advanced override: if ``credentials_file`` exists it wins, so a user
    running their own verified Google Cloud app can drop its client JSON in and
    keep using it. Absence of the file is NOT an error.
    """
    if credentials_file.exists():
        return InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    return InstalledAppFlow.from_client_config(build_client_config(), scopes)


def start_auth_flow(credentials_file: Path, scopes: list[str]) -> dict:
    flow = _make_flow(credentials_file, scopes)
    flow.redirect_uri = REDIRECT_URI
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    # Save code_verifier so complete_auth_flow can use it
    if flow.code_verifier:
        VERIFIER_FILE.write_text(flow.code_verifier)
    return {"auth_url": auth_url}


def complete_auth_flow(credentials_file: Path, scopes: list[str], code: str, token_file: Path) -> Credentials:
    flow = _make_flow(credentials_file, scopes)
    flow.redirect_uri = REDIRECT_URI
    # Restore code_verifier if available
    if VERIFIER_FILE.exists():
        flow.code_verifier = VERIFIER_FILE.read_text().strip()
        VERIFIER_FILE.unlink(missing_ok=True)
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_token(token_file, creds)
    return creds


def run_local_server_flow(credentials_file: Path, scopes: list[str], token_file: Path) -> Credentials:
    # open_browser=False: sign-in happens in a separately-driven handover browser,
    # not a browser on this (often headless) host. run_local_server prints the
    # consent URL and runs a 127.0.0.1 loopback listener for the redirect.
    flow = _make_flow(credentials_file, scopes)
    creds = flow.run_local_server(port=LOOPBACK_PORT, open_browser=False)
    _save_token(token_file, creds)
    return creds


def get_credentials(token_file: Path, credentials_file: Path, scopes: list[str]) -> Credentials:
    if not token_file.exists():
        raise ValueError("Not authenticated. Run 'google auth login' first.")

    creds = _load_token(token_file, scopes)

    # Refresh when the token is expired OR when we cannot prove it is still valid
    # (expiry unknown, e.g. a token saved before expiry was persisted). Relying on
    # creds.valid alone silently reuses a stale token whose expiry is None.
    if creds.refresh_token and (creds.expiry is None or not creds.valid):
        creds.refresh(Request())
        _save_token(token_file, creds)
        return creds

    if creds.valid:
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
        # Persist expiry so a reloaded Credentials object can tell it is expired
        # and refresh. Without this, expiry is None -> creds.valid is always True
        # -> the stale access token is reused until Google 401s every call ~1h in.
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    token_file.write_text(json.dumps(token_data, indent=2))


def _load_token(token_file: Path, scopes: list[str]) -> Credentials:
    data = json.loads(token_file.read_text())
    creds = Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"] if "refresh_token" in data else None,
        token_uri=data["token_uri"] if "token_uri" in data else "https://oauth2.googleapis.com/token",
        client_id=data["client_id"] if "client_id" in data else None,
        client_secret=data["client_secret"] if "client_secret" in data else None,
        scopes=scopes,
    )
    # Restore expiry so creds.expired / creds.valid reflect reality. google-auth
    # uses a naive UTC datetime here.
    expiry = data.get("expiry")
    if expiry:
        try:
            dt = datetime.fromisoformat(expiry)
            creds.expiry = dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            creds.expiry = None
    return creds
