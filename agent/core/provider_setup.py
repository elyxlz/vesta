"""Provider setup HTTP flows owned by each running agent."""

import base64
import dataclasses as dc
import hashlib
import json
import secrets
import time
import urllib.parse

import aiohttp
import pydantic as pyd
from aiohttp import web

from . import claude_models

_SESSION_TTL_SECONDS = 600
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

_CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_CLAUDE_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
_CLAUDE_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLAUDE_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
_CLAUDE_SCOPES = "org:create_api_key user:profile user:inference"
_CLAUDE_DEFAULT_EXPIRES_SECONDS = 28_800

_OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_OPENAI_ISSUER = "https://auth.openai.com"
_OPENAI_DEFAULT_EXPIRES_SECONDS = 3_600

_OPENROUTER_TOP_MODELS_URL = "https://openrouter.ai/api/frontend/models/find?order=top-weekly"
_OPENROUTER_KEY_INFO_URL = "https://openrouter.ai/api/v1/key"
_OPENROUTER_TOP_MODELS_LIMIT = 20
_TOKENS_PER_PRICE_UNIT = 1_000_000.0


@dc.dataclass(frozen=True)
class _ClaudeAuthSession:
    code_verifier: str
    state: str
    created: float


@dc.dataclass(frozen=True)
class _OpenAIAuthSession:
    device_auth_id: str
    user_code: str
    created: float


@dc.dataclass
class ProviderSetupState:
    claude_sessions: dict[str, _ClaudeAuthSession] = dc.field(default_factory=dict)
    openai_sessions: dict[str, _OpenAIAuthSession] = dc.field(default_factory=dict)


PROVIDER_SETUP_STATE = web.AppKey("provider_setup_state", ProviderSetupState)


class _ClaudeCompleteBody(pyd.BaseModel):
    session_id: str = pyd.Field(min_length=1)
    code: str = pyd.Field(min_length=1)


class _ClaudeModelsBody(pyd.BaseModel):
    credentials: str = pyd.Field(min_length=1)


class _OpenAICompleteBody(pyd.BaseModel):
    session_id: str = pyd.Field(min_length=1)


class _DeviceInit(pyd.BaseModel):
    device_auth_id: str = pyd.Field(min_length=1)
    user_code: str = pyd.Field(min_length=1)


class _DevicePoll(pyd.BaseModel):
    authorization_code: str = pyd.Field(min_length=1)
    code_verifier: str = pyd.Field(min_length=1)


class _TokenResponse(pyd.BaseModel):
    id_token: str | None = None
    access_token: str
    refresh_token: str
    expires_in: int | None = pyd.Field(default=None, ge=0)


class _OpenRouterPricing(pyd.BaseModel):
    prompt: str | None = None
    completion: str | None = None
    input_cache_read: str | None = None


class _OpenRouterEndpoint(pyd.BaseModel):
    pricing: _OpenRouterPricing | None = None


class _OpenRouterModel(pyd.BaseModel):
    slug: str
    short_name: str | None = None
    name: str | None = None
    author: str
    author_display_name: str | None = None
    context_length: int | None = None
    endpoint: _OpenRouterEndpoint | None = None


class _OpenRouterData(pyd.BaseModel):
    models: list[_OpenRouterModel]


class _OpenRouterResponse(pyd.BaseModel):
    data: _OpenRouterData


class _ValidateKeyBody(pyd.BaseModel):
    key: str = pyd.Field(min_length=1)


class _SetupError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def _validated_body[BodyT: pyd.BaseModel](request: web.Request, model: type[BodyT]) -> BodyT | web.Response:
    try:
        body = await request.json()
        return model.model_validate(body)
    except (json.JSONDecodeError, TypeError, pyd.ValidationError):
        return _error(400, "invalid request body")


def _clean_expired(state: ProviderSetupState, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    state.claude_sessions = {
        session_id: session for session_id, session in state.claude_sessions.items() if current - session.created <= _SESSION_TTL_SECONDS
    }
    state.openai_sessions = {
        session_id: session for session_id, session in state.openai_sessions.items() if current - session.created <= _SESSION_TTL_SECONDS
    }


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _start_claude_auth_flow() -> tuple[str, str, str]:
    code_verifier = _base64url(secrets.token_bytes(32))
    code_challenge = _base64url(hashlib.sha256(code_verifier.encode()).digest())
    auth_state = _base64url(secrets.token_bytes(32))
    query = urllib.parse.urlencode(
        {
            "code": "true",
            "client_id": _CLAUDE_CLIENT_ID,
            "redirect_uri": _CLAUDE_REDIRECT_URI,
            "response_type": "code",
            "scope": _CLAUDE_SCOPES,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": auth_state,
        }
    )
    return f"{_CLAUDE_AUTHORIZE_URL}?{query}", code_verifier, auth_state


async def claude_oauth_start(request: web.Request) -> web.Response:
    state = request.app[PROVIDER_SETUP_STATE]
    _clean_expired(state)
    auth_url, code_verifier, auth_state = _start_claude_auth_flow()
    session_id = secrets.token_hex(16)
    state.claude_sessions[session_id] = _ClaudeAuthSession(code_verifier, auth_state, time.monotonic())
    return web.json_response({"auth_url": auth_url, "session_id": session_id})


def _claude_code_and_state(code: str, expected_state: str) -> tuple[str, str]:
    if "#" not in code:
        return code, expected_state
    auth_code, pasted_state = code.split("#", 1)
    return auth_code, pasted_state


async def _exchange_claude_credentials(payload: dict[str, str]) -> str:
    try:
        async with (
            aiohttp.ClientSession() as client,
            client.post(
                _CLAUDE_TOKEN_URL,
                headers={"User-Agent": "axios/1.13.6"},
                json=payload,
                timeout=_HTTP_TIMEOUT,
            ) as response,
        ):
            response_text = await response.text()
    except TimeoutError as exc:
        raise _SetupError(400, "token exchange timed out") from exc
    except aiohttp.ClientError as exc:
        raise _SetupError(400, f"token exchange request failed: {exc}") from exc

    try:
        token_data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise _SetupError(400, f"token exchange failed: {response_text}") from exc
    if not isinstance(token_data, dict):
        raise _SetupError(400, "token exchange returned an invalid response")
    if "error" in token_data:
        error = token_data["error"]
        description = token_data["error_description"] if "error_description" in token_data else error
        raise _SetupError(400, f"auth failed: {error}: {description}")
    if "access_token" not in token_data or not isinstance(token_data["access_token"], str):
        raise _SetupError(400, "no access_token in response")

    expires_in = token_data["expires_in"] if "expires_in" in token_data else _CLAUDE_DEFAULT_EXPIRES_SECONDS
    if not isinstance(expires_in, int):
        expires_in = _CLAUDE_DEFAULT_EXPIRES_SECONDS
    oauth: dict[str, pyd.JsonValue] = {
        "accessToken": token_data["access_token"],
        "expiresAt": int(time.time() * 1000) + expires_in * 1000,
    }
    if "refresh_token" in token_data and isinstance(token_data["refresh_token"], str):
        oauth["refreshToken"] = token_data["refresh_token"]
    if "scope" in token_data and isinstance(token_data["scope"], str):
        oauth["scopes"] = token_data["scope"].split()
    return json.dumps({"claudeAiOauth": oauth}, separators=(",", ":"))


async def claude_oauth_complete(request: web.Request) -> web.Response:
    parsed = await _validated_body(request, _ClaudeCompleteBody)
    if isinstance(parsed, web.Response):
        return parsed
    body = parsed
    state = request.app[PROVIDER_SETUP_STATE]
    _clean_expired(state)
    session = state.claude_sessions.pop(body.session_id, None)
    if session is None:
        return _error(400, "invalid or expired auth session")

    auth_code, pasted_state = _claude_code_and_state(body.code, session.state)
    if pasted_state != session.state:
        return _error(400, "state mismatch: possible CSRF, please retry auth")
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "state": pasted_state,
        "client_id": _CLAUDE_CLIENT_ID,
        "redirect_uri": _CLAUDE_REDIRECT_URI,
        "code_verifier": session.code_verifier,
    }
    try:
        credentials = await _exchange_claude_credentials(payload)
    except _SetupError as exc:
        return _error(exc.status, exc.message)
    return web.json_response({"credentials": credentials})


async def claude_models_handler(request: web.Request) -> web.Response:
    parsed = await _validated_body(request, _ClaudeModelsBody)
    if isinstance(parsed, web.Response):
        return parsed
    body = parsed
    try:
        access_token = claude_models.parse_claude_access_token(body.credentials)
    except (json.JSONDecodeError, pyd.ValidationError):
        return _error(400, "credentials blob is not valid claude oauth json")
    try:
        models = await claude_models.fetch_claude_models(access_token)
    except aiohttp.ClientResponseError as exc:
        if exc.status == 401:
            return _error(400, "claude credentials rejected by anthropic")
        return _error(502, f"anthropic returned HTTP {exc.status}")
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        return _error(502, f"anthropic request failed: {exc}")
    return web.json_response(models)


async def openai_oauth_start(request: web.Request) -> web.Response:
    state = request.app[PROVIDER_SETUP_STATE]
    _clean_expired(state)
    try:
        async with (
            aiohttp.ClientSession() as client,
            client.post(
                f"{_OPENAI_ISSUER}/api/accounts/deviceauth/usercode",
                json={"client_id": _OPENAI_CLIENT_ID},
                timeout=_HTTP_TIMEOUT,
            ) as response,
        ):
            status = response.status
            response_text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        return _error(502, f"device login start failed: {exc}")
    if status < 200 or status >= 300:
        return _error(502, f"OpenAI returned {status}: {response_text}")
    try:
        init = _DeviceInit.model_validate_json(response_text)
    except pyd.ValidationError as exc:
        return _error(502, f"invalid device login response: {exc}")

    session_id = secrets.token_hex(16)
    state.openai_sessions[session_id] = _OpenAIAuthSession(init.device_auth_id, init.user_code, time.monotonic())
    return web.json_response({"auth_url": f"{_OPENAI_ISSUER}/codex/device", "user_code": init.user_code, "session_id": session_id})


async def _poll_openai_device(session: _OpenAIAuthSession) -> _DevicePoll:
    try:
        async with (
            aiohttp.ClientSession() as client,
            client.post(
                f"{_OPENAI_ISSUER}/api/accounts/deviceauth/token",
                json={"device_auth_id": session.device_auth_id, "user_code": session.user_code},
                timeout=_HTTP_TIMEOUT,
            ) as response,
        ):
            status = response.status
            response_text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise _SetupError(502, f"device login check failed: {exc}") from exc
    if status in {403, 404}:
        raise _SetupError(409, "authorization is still pending")
    if status < 200 or status >= 300:
        raise _SetupError(502, f"OpenAI returned {status}: {response_text}")
    try:
        return _DevicePoll.model_validate_json(response_text)
    except pyd.ValidationError as exc:
        raise _SetupError(502, f"invalid device login response: {exc}") from exc


async def _exchange_openai_tokens(poll: _DevicePoll) -> _TokenResponse:
    form = {
        "grant_type": "authorization_code",
        "code": poll.authorization_code,
        "redirect_uri": f"{_OPENAI_ISSUER}/deviceauth/callback",
        "client_id": _OPENAI_CLIENT_ID,
        "code_verifier": poll.code_verifier,
    }
    try:
        async with (
            aiohttp.ClientSession() as client,
            client.post(f"{_OPENAI_ISSUER}/oauth/token", data=form, timeout=_HTTP_TIMEOUT) as response,
        ):
            status = response.status
            response_text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise _SetupError(502, f"token exchange failed: {exc}") from exc
    if status < 200 or status >= 300:
        raise _SetupError(502, f"OpenAI returned {status}: {response_text}")
    try:
        tokens = _TokenResponse.model_validate_json(response_text)
    except pyd.ValidationError as exc:
        raise _SetupError(502, f"invalid token response: {exc}") from exc
    if not tokens.access_token.strip() or not tokens.refresh_token.strip() or tokens.expires_in == 0:
        raise _SetupError(502, "OpenAI returned incomplete credentials")
    return tokens


async def openai_oauth_complete(request: web.Request) -> web.Response:
    parsed = await _validated_body(request, _OpenAICompleteBody)
    if isinstance(parsed, web.Response):
        return parsed
    body = parsed
    state = request.app[PROVIDER_SETUP_STATE]
    _clean_expired(state)
    session = state.openai_sessions.get(body.session_id)
    if session is None:
        return _error(400, "invalid or expired OpenAI auth session")

    try:
        poll = await _poll_openai_device(session)
        tokens = await _exchange_openai_tokens(poll)
    except _SetupError as exc:
        return _error(exc.status, exc.message)

    state.openai_sessions.pop(body.session_id, None)
    expires_in = tokens.expires_in if tokens.expires_in is not None else _OPENAI_DEFAULT_EXPIRES_SECONDS
    account_id = _account_id_from_jwt(tokens.id_token or "") or _account_id_from_jwt(tokens.access_token)
    credentials = json.dumps(
        {
            "access": tokens.access_token,
            "refresh": tokens.refresh_token,
            "expires": int(time.time() * 1000) + expires_in * 1000,
            "accountId": account_id,
        },
        separators=(",", ":"),
    )
    return web.json_response({"credentials": credentials})


def _jwt_claims(token: str) -> dict[str, pyd.JsonValue] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = pyd.TypeAdapter(dict[str, pyd.JsonValue]).validate_json(base64.urlsafe_b64decode(payload))
    except (ValueError, pyd.ValidationError):
        return None
    return claims


def _string_field(values: dict[str, pyd.JsonValue], key: str) -> str | None:
    if key not in values:
        return None
    value = values[key]
    if isinstance(value, str):
        return value
    return None


def _account_id_from_jwt(token: str) -> str | None:
    claims = _jwt_claims(token)
    if claims is None:
        return None
    for key in ("chatgpt_account_id", "https://api.openai.com/auth.chatgpt_account_id"):
        account_id = _string_field(claims, key)
        if account_id is not None:
            return account_id
    auth_key = "https://api.openai.com/auth"
    auth = claims[auth_key] if auth_key in claims else None
    if isinstance(auth, dict):
        account_id = _string_field(auth, "chatgpt_account_id")
        if account_id is not None:
            return account_id
    if "organizations" in claims and isinstance(claims["organizations"], list) and claims["organizations"]:
        organization = claims["organizations"][0]
        if isinstance(organization, dict):
            return _string_field(organization, "id")
    return None


def _price_per_million(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw) * _TOKENS_PER_PRICE_UNIT
    except ValueError:
        return None


def _openrouter_model(model: _OpenRouterModel) -> dict[str, pyd.JsonValue]:
    pricing = model.endpoint.pricing if model.endpoint is not None else None
    return {
        "slug": model.slug,
        "label": model.short_name or model.name or model.slug,
        "author": model.author_display_name or model.author,
        "context_length": model.context_length,
        "input_price": _price_per_million(pricing.prompt if pricing is not None else None),
        "output_price": _price_per_million(pricing.completion if pricing is not None else None),
        "cache_read_price": _price_per_million(pricing.input_cache_read if pricing is not None else None),
    }


async def openrouter_top_models(_request: web.Request) -> web.Response:
    try:
        async with (
            aiohttp.ClientSession() as client,
            client.get(_OPENROUTER_TOP_MODELS_URL, timeout=_HTTP_TIMEOUT) as response,
        ):
            status = response.status
            response_text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        return _error(502, f"openrouter request failed: {exc}")
    if status < 200 or status >= 300:
        return _error(502, f"openrouter returned HTTP {status}")
    try:
        parsed = _OpenRouterResponse.model_validate_json(response_text)
    except pyd.ValidationError as exc:
        return _error(502, f"openrouter response parse failed: {exc}")
    models = [_openrouter_model(model) for model in parsed.data.models[:_OPENROUTER_TOP_MODELS_LIMIT]]
    return web.json_response(models)


async def openrouter_validate_key(request: web.Request) -> web.Response:
    parsed = await _validated_body(request, _ValidateKeyBody)
    if isinstance(parsed, web.Response):
        return parsed
    body = parsed
    try:
        async with (
            aiohttp.ClientSession() as client,
            client.get(
                _OPENROUTER_KEY_INFO_URL,
                headers={"Authorization": f"Bearer {body.key}"},
                timeout=_HTTP_TIMEOUT,
            ) as response,
        ):
            status = response.status
    except (aiohttp.ClientError, TimeoutError) as exc:
        return _error(502, f"openrouter request failed: {exc}")
    if status == 401:
        return _error(400, "invalid API key")
    if status < 200 or status >= 300:
        return _error(502, f"openrouter returned HTTP {status}")
    return web.json_response({"ok": True})


def register_routes(app: web.Application) -> None:
    app[PROVIDER_SETUP_STATE] = ProviderSetupState()
    app.router.add_post("/providers/claude/oauth/start", claude_oauth_start)
    app.router.add_post("/providers/claude/oauth/complete", claude_oauth_complete)
    app.router.add_post("/providers/claude/models", claude_models_handler)
    app.router.add_post("/providers/openai/oauth/start", openai_oauth_start)
    app.router.add_post("/providers/openai/oauth/complete", openai_oauth_complete)
    app.router.add_get("/providers/openrouter/models/top", openrouter_top_models)
    app.router.add_post("/providers/openrouter/validate-key", openrouter_validate_key)
