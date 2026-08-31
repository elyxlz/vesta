"""Live Claude model catalog: read OAuth tokens and list models from the Anthropic API."""

import typing as tp

import aiohttp
import pydantic as pyd

from .config import read_claude_oauth
from .provider import ANTHROPIC_API_URL, OAUTH_BETA_HEADER

_MODELS_URL = f"{ANTHROPIC_API_URL}/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"
# The Models API paginates (default page 20); ask for its maximum so the catalog is one page.
_MODELS_PAGE_LIMIT = "1000"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)


class ClaudeModelOption(tp.TypedDict):
    slug: str
    label: str
    author: str


class _Model(pyd.BaseModel):
    id: str
    display_name: str


class _ModelsResponse(pyd.BaseModel):
    data: list[_Model]


class _OAuthInner(pyd.BaseModel):
    access_token: str = pyd.Field(alias="accessToken", min_length=1)


class _OAuthBlob(pyd.BaseModel):
    claude_ai_oauth: _OAuthInner = pyd.Field(alias="claudeAiOauth")


def parse_claude_access_token(credentials: str) -> str:
    """Extract an access token from the portable Claude OAuth credentials blob."""
    return _OAuthBlob.model_validate_json(credentials).claude_ai_oauth.access_token


def read_claude_access_token() -> str | None:
    """The stored OAuth access token, or None when unauthenticated/unreadable. Delegates to
    config.py's read_claude_oauth, the one owner of parsing CREDENTIALS_PATH."""
    oauth = read_claude_oauth()
    if oauth is None or oauth.access_token is None or not oauth.access_token.strip():
        return None
    return oauth.access_token


def parse_models(payload: pyd.JsonValue) -> list[ClaudeModelOption]:
    parsed = _ModelsResponse.model_validate(payload)
    return [{"slug": m.id, "label": m.display_name, "author": "Anthropic"} for m in parsed.data]


async def fetch_claude_models(access_token: str) -> list[ClaudeModelOption]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "anthropic-version": _ANTHROPIC_VERSION,
        "anthropic-beta": OAUTH_BETA_HEADER,
    }
    async with (
        aiohttp.ClientSession() as session,
        session.get(_MODELS_URL, headers=headers, params={"limit": _MODELS_PAGE_LIMIT}, timeout=_HTTP_TIMEOUT) as resp,
    ):
        resp.raise_for_status()
        return parse_models(await resp.json())
