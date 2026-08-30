import base64
import json
import urllib.parse

import pydantic as pyd
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from core import claude_models
from core import provider_setup as setup


def _provider_app() -> web.Application:
    app = web.Application()
    setup.register_routes(app)
    return app


def _jwt(claims: dict[str, pyd.JsonValue]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"chatgpt_account_id": "direct"}, "direct"),
        ({"https://api.openai.com/auth.chatgpt_account_id": "namespaced"}, "namespaced"),
        ({"https://api.openai.com/auth": {"chatgpt_account_id": "nested"}}, "nested"),
        ({"organizations": [{"id": "organization"}]}, "organization"),
    ],
)
def test_openai_account_id_claim_shapes(claims: dict[str, pyd.JsonValue], expected: str):
    assert setup._account_id_from_jwt(_jwt(claims)) == expected


def test_openai_account_id_rejects_malformed_jwt():
    assert setup._account_id_from_jwt("not-a-jwt") is None


@pytest.mark.anyio
async def test_claude_setup_is_pkce_scoped_and_one_shot(monkeypatch):
    exchanges: list[dict[str, str]] = []

    async def exchange(request: web.Request) -> web.Response:
        exchanges.append(await request.json())
        return web.json_response(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 7200,
                "scope": "user:profile user:inference",
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/oauth/token", exchange)
    async with TestServer(upstream) as upstream_server:
        monkeypatch.setattr(setup, "_CLAUDE_TOKEN_URL", str(upstream_server.make_url("/oauth/token")))
        async with TestClient(TestServer(_provider_app())) as client:
            start = await client.post("/providers/claude/oauth/start")
            start_body = await start.json()
            query = urllib.parse.parse_qs(urllib.parse.urlparse(start_body["auth_url"]).query)
            assert query["code_challenge_method"] == ["S256"]
            assert len(query["code_challenge"][0]) == 43

            complete = await client.post(
                "/providers/claude/oauth/complete",
                json={"session_id": start_body["session_id"], "code": f"auth-code#{query['state'][0]}"},
            )
            assert complete.status == 200
            credentials = json.loads((await complete.json())["credentials"])["claudeAiOauth"]
            assert credentials["accessToken"] == "access"
            assert credentials["refreshToken"] == "refresh"
            assert credentials["scopes"] == ["user:profile", "user:inference"]
            assert exchanges[0]["code"] == "auth-code"

            replay = await client.post(
                "/providers/claude/oauth/complete",
                json={"session_id": start_body["session_id"], "code": "auth-code"},
            )
            assert replay.status == 400


@pytest.mark.anyio
async def test_claude_setup_rejects_wrong_state_before_exchange(monkeypatch):
    async with TestClient(TestServer(_provider_app())) as client:
        start_body = await (await client.post("/providers/claude/oauth/start")).json()
        complete = await client.post(
            "/providers/claude/oauth/complete",
            json={"session_id": start_body["session_id"], "code": "auth-code#wrong"},
        )
        assert complete.status == 400
        assert "state mismatch" in (await complete.json())["error"]


@pytest.mark.anyio
async def test_claude_models_uses_portable_credentials(monkeypatch):
    async def models(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer access"
        assert request.query["limit"] == "1000"
        return web.json_response({"data": [{"id": "claude-opus-5", "display_name": "Claude Opus 5"}]})

    upstream = web.Application()
    upstream.router.add_get("/v1/models", models)
    async with TestServer(upstream) as upstream_server:
        monkeypatch.setattr(claude_models, "_MODELS_URL", str(upstream_server.make_url("/v1/models")))
        async with TestClient(TestServer(_provider_app())) as client:
            response = await client.post(
                "/providers/claude/models",
                json={"credentials": json.dumps({"claudeAiOauth": {"accessToken": "access"}})},
            )
            assert response.status == 200
            assert await response.json() == [{"slug": "claude-opus-5", "label": "Claude Opus 5", "author": "Anthropic"}]


@pytest.mark.anyio
async def test_openai_pending_session_completes_without_restarting(monkeypatch):
    poll_responses = iter(
        [
            web.Response(status=403),
            web.json_response({"authorization_code": "authorization", "code_verifier": "verifier"}),
        ]
    )

    async def start(_request: web.Request) -> web.Response:
        return web.json_response({"device_auth_id": "device", "user_code": "USER-CODE"})

    async def poll(_request: web.Request) -> web.Response:
        return next(poll_responses)

    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        assert form["code"] == "authorization"
        return web.json_response(
            {
                "id_token": _jwt({"chatgpt_account_id": "account"}),
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/api/accounts/deviceauth/usercode", start)
    upstream.router.add_post("/api/accounts/deviceauth/token", poll)
    upstream.router.add_post("/oauth/token", token)
    async with TestServer(upstream) as upstream_server:
        monkeypatch.setattr(setup, "_OPENAI_ISSUER", str(upstream_server.make_url("")).rstrip("/"))
        app = _provider_app()
        async with TestClient(TestServer(app)) as client:
            started = await (await client.post("/providers/openai/oauth/start")).json()
            assert started["user_code"] == "USER-CODE"

            pending = await client.post("/providers/openai/oauth/complete", json={"session_id": started["session_id"]})
            assert pending.status == 409
            assert started["session_id"] in app[setup.PROVIDER_SETUP_STATE].openai_sessions

            complete = await client.post("/providers/openai/oauth/complete", json={"session_id": started["session_id"]})
            assert complete.status == 200
            credentials = json.loads((await complete.json())["credentials"])
            assert credentials["accountId"] == "account"
            assert started["session_id"] not in app[setup.PROVIDER_SETUP_STATE].openai_sessions


@pytest.mark.anyio
async def test_openrouter_projects_top_models_and_rejects_bad_key(monkeypatch):
    async def models(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "data": {
                    "models": [
                        {
                            "slug": "vendor/model",
                            "short_name": "Model",
                            "author": "vendor",
                            "author_display_name": "Vendor",
                            "context_length": 1_000_000,
                            "endpoint": {
                                "pricing": {
                                    "prompt": "0.000001",
                                    "completion": "0.000002",
                                    "input_cache_read": "0.0000001",
                                }
                            },
                        }
                    ]
                }
            }
        )

    async def invalid_key(_request: web.Request) -> web.Response:
        return web.Response(status=401)

    upstream = web.Application()
    upstream.router.add_get("/models", models)
    upstream.router.add_get("/key", invalid_key)
    async with TestServer(upstream) as upstream_server:
        monkeypatch.setattr(setup, "_OPENROUTER_TOP_MODELS_URL", str(upstream_server.make_url("/models")))
        monkeypatch.setattr(setup, "_OPENROUTER_KEY_INFO_URL", str(upstream_server.make_url("/key")))
        async with TestClient(TestServer(_provider_app())) as client:
            response = await client.get("/providers/openrouter/models/top")
            assert await response.json() == [
                {
                    "slug": "vendor/model",
                    "label": "Model",
                    "author": "Vendor",
                    "context_length": 1_000_000,
                    "input_price": 1.0,
                    "output_price": 2.0,
                    "cache_read_price": 0.09999999999999999,
                }
            ]
            invalid = await client.post("/providers/openrouter/validate-key", json={"key": "bad"})
            assert invalid.status == 400


def test_expired_provider_sessions_are_pruned():
    state = setup.ProviderSetupState(
        claude_sessions={"expired": setup._ClaudeAuthSession("verifier", "state", 1.0)},
        openai_sessions={"fresh": setup._OpenAIAuthSession("device", "code", 500.0)},
    )
    setup._clean_expired(state, now=1000.0)
    assert state.claude_sessions == {}
    assert list(state.openai_sessions) == ["fresh"]
