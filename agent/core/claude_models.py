"""Live Claude model catalog: read the stored OAuth token and list the account's models
from the Anthropic Models API. The single owner of the /v1/models call and its parsing on
the agent side (vestad owns the onboarding copy)."""

import json
import typing as tp

import aiohttp
import pydantic as pyd

from .config import CREDENTIALS_PATH

_MODELS_URL = "https://api.anthropic.com/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"
_OAUTH_BETA = "oauth-2025-04-20"
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


def read_claude_access_token() -> str | None:
    """The stored OAuth access token, or None when unauthenticated/unreadable."""
    if not CREDENTIALS_PATH.is_file():
        return None
    try:
        blob = json.loads(CREDENTIALS_PATH.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(blob, dict) or "claudeAiOauth" not in blob:
        return None
    oauth = blob["claudeAiOauth"]
    if not isinstance(oauth, dict) or "accessToken" not in oauth:
        return None
    token = oauth["accessToken"]
    return token if isinstance(token, str) and token.strip() else None


def parse_models(payload: pyd.JsonValue) -> list[ClaudeModelOption]:
    parsed = _ModelsResponse.model_validate(payload)
    return [{"slug": m.id, "label": m.display_name, "author": "Anthropic"} for m in parsed.data]


async def fetch_claude_models(access_token: str) -> list[ClaudeModelOption]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "anthropic-version": _ANTHROPIC_VERSION,
        "anthropic-beta": _OAUTH_BETA,
    }
    async with (
        aiohttp.ClientSession() as session,
        session.get(_MODELS_URL, headers=headers, timeout=_HTTP_TIMEOUT) as resp,
    ):
        resp.raise_for_status()
        return parse_models(await resp.json())
