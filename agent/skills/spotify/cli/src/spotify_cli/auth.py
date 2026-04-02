"""Spotify OAuth authentication.

Uses spotipy's SpotifyOAuth with CacheFileHandler for token persistence.
Credentials (client_id, client_secret) stored in ~/.spotify/credentials.json.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler

from .config import Config


def _load_credentials(config: Config) -> tuple[str, str]:
    """Load client_id and client_secret from credentials file."""
    creds_file = config.credentials_file
    if not creds_file.exists():
        print(
            json.dumps(
                {
                    "error": "no_credentials",
                    "message": "No credentials found. Run: spotify auth setup --client-id <ID> --client-secret <SECRET>",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    data = json.loads(creds_file.read_text())
    client_id = data.get("client_id", "")
    client_secret = data.get("client_secret", "")
    if not client_id or not client_secret:
        print(
            json.dumps(
                {
                    "error": "invalid_credentials",
                    "message": "credentials.json missing client_id or client_secret",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    return client_id, client_secret


def save_credentials(config: Config, client_id: str, client_secret: str) -> dict:
    """Save Spotify app credentials to disk."""
    config.ensure_dirs()
    data = {"client_id": client_id, "client_secret": client_secret}
    config.credentials_file.write_text(json.dumps(data, indent=2))
    config.credentials_file.chmod(0o600)
    return {"status": "saved", "path": str(config.credentials_file)}


def get_auth_manager(config: Config) -> SpotifyOAuth:
    """Create a SpotifyOAuth manager with cached tokens."""
    client_id, client_secret = _load_credentials(config)
    config.ensure_dirs()

    cache_handler = CacheFileHandler(cache_path=str(config.token_cache))

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=config.redirect_uri,
        scope=config.scopes,
        cache_handler=cache_handler,
        open_browser=False,
    )


def get_client(config: Config) -> spotipy.Spotify:
    """Get an authenticated Spotify client. Exits if not authed."""
    auth_manager = get_auth_manager(config)

    # Check for cached token
    token_info = auth_manager.cache_handler.get_cached_token()
    if not token_info:
        print(
            json.dumps(
                {
                    "error": "not_authenticated",
                    "message": "No token found. Run: spotify auth login",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    # Refresh if expired
    if auth_manager.is_token_expired(token_info):
        token_info = auth_manager.refresh_access_token(token_info["refresh_token"])

    return spotipy.Spotify(auth_manager=auth_manager)


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback code."""

    auth_code: str | None = None

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        if code:
            _CallbackHandler.auth_code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>authenticated! you can close this tab.</h2></body></html>")
        else:
            error = query.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>error: {error}</h2></body></html>".encode())

    def log_message(self, format, *args):
        pass  # suppress logs


def login(config: Config) -> dict:
    """Run the OAuth login flow. Returns auth URL for the user to visit."""
    auth_manager = get_auth_manager(config)
    auth_url = auth_manager.get_authorize_url()

    return {
        "status": "awaiting_auth",
        "auth_url": auth_url,
        "message": "Open this URL to authorize, then run: spotify auth callback --url <redirect_url>",
    }


def handle_callback(config: Config, callback_url: str) -> dict:
    """Process the OAuth callback URL after user authorizes."""
    auth_manager = get_auth_manager(config)

    query = parse_qs(urlparse(callback_url).query)
    code = query.get("code", [None])[0]

    if not code:
        return {"error": "no_code", "message": "No authorization code found in callback URL"}

    token_info = auth_manager.get_access_token(code, as_dict=True)

    if not token_info:
        return {"error": "token_failed", "message": "Failed to get access token"}

    # Get user info
    sp = spotipy.Spotify(auth_manager=auth_manager)
    user = sp.current_user()

    return {
        "status": "authenticated",
        "user": user.get("display_name", "unknown"),
        "user_id": user.get("id", "unknown"),
        "email": user.get("email", ""),
    }


def status(config: Config) -> dict:
    """Check authentication status."""
    try:
        client_id, _ = _load_credentials(config)
    except SystemExit:
        return {"status": "no_credentials", "message": "No Spotify app credentials configured"}

    auth_manager = get_auth_manager(config)
    token_info = auth_manager.cache_handler.get_cached_token()

    if not token_info:
        return {"status": "not_authenticated", "client_id": client_id}

    expired = auth_manager.is_token_expired(token_info)

    try:
        sp = get_client(config)
        user = sp.current_user()
        return {
            "status": "authenticated",
            "client_id": client_id,
            "user": user.get("display_name"),
            "user_id": user.get("id"),
            "token_expired": expired,
        }
    except Exception as e:
        return {
            "status": "token_error",
            "client_id": client_id,
            "token_expired": expired,
            "error": str(e),
        }
