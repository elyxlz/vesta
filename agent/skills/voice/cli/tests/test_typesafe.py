"""The Jev judge: its thresholds turn probabilities into a verdict, and it never raises."""

import asyncio
import contextlib
import typing as tp

import aiohttp
import pytest
from aiohttp import web
from voice.providers import typesafe
from voice.providers.base import Question, Verdict
from voice.settings import JsonValue

from .fakes import serving

SPEAKING: Question = {"agent_name": "aria", "recent": [], "agent_saying": "It will be sunny.", "user_saying": "wait"}
LISTENING: Question = {"agent_name": "aria", "recent": [], "agent_saying": None, "user_saying": "Friday"}


def _said_to(agent: float, echo: float = 0.0, other: float = 0.0, noise: float = 0.0) -> dict[str, JsonValue]:
    return {"choice": "agent", "probabilities": {"agent": agent, "echo": echo, "other_person": other, "not_speech": noise}}


@pytest.mark.parametrize(
    ("answers", "verdict"),
    [
        ({"said_to": _said_to(0.73)}, {"said_to": "agent", "wants_stop": None}),
        ({"said_to": _said_to(0.5), "wants_stop": {"noul": 0.69}}, {"said_to": "agent", "wants_stop": True}),
        ({"said_to": _said_to(0.9), "wants_stop": {"noul": 0.09}}, {"said_to": "agent", "wants_stop": False}),
        ({"said_to": _said_to(0.49, echo=0.5), "wants_stop": {"noul": 0.2}}, {"said_to": "echo", "wants_stop": False}),
        ({"said_to": _said_to(0.1, other=0.8, noise=0.1)}, {"said_to": "other_person", "wants_stop": None}),
        ({"said_to": _said_to(0.05, noise=0.9)}, {"said_to": "not_speech", "wants_stop": None}),
    ],
)
def test_the_thresholds_turn_the_probabilities_into_a_verdict(answers: dict[str, JsonValue], verdict: Verdict) -> None:
    assert typesafe.verdict_from(tp.cast(tp.Any, answers)) == verdict


@pytest.mark.parametrize(
    "answers", [{}, {"said_to": {}}, {"said_to": {"probabilities": {"agent": 0.2}}}, {"said_to": _said_to(0.9), "wants_stop": {}}]
)
def test_an_answer_with_no_usable_shape_is_no_verdict(answers: dict[str, JsonValue]) -> None:
    assert typesafe.verdict_from(tp.cast(tp.Any, answers)) is None


@contextlib.asynccontextmanager
async def jev(
    monkeypatch: pytest.MonkeyPatch, handler: tp.Callable[[web.Request], tp.Awaitable[web.StreamResponse]]
) -> tp.AsyncIterator[aiohttp.ClientSession]:
    app = web.Application()
    app.router.add_post("/v1/systemone", handler)
    async with serving(app) as client, aiohttp.ClientSession() as http:
        monkeypatch.setattr(typesafe, "JEV_URL", f"http://{client.host}:{client.port}/v1/systemone")
        yield http


def test_a_question_while_the_agent_speaks_asks_both_questions_with_the_pinned_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, JsonValue]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append({"body": await request.json(), "auth": request.headers["Authorization"]})
        return web.json_response({"answers": {"said_to": _said_to(0.9), "wants_stop": {"noul": 0.8}}})

    async def scenario() -> Verdict | None:
        async with jev(monkeypatch, handler) as http:
            return await typesafe.TypesafeJudge().ask(SPEAKING, {"api_key": "k"}, {}, http)

    assert asyncio.run(scenario()) == {"said_to": "agent", "wants_stop": True}
    body = tp.cast(dict[str, tp.Any], seen[0]["body"])
    assert seen[0]["auth"] == "Bearer k"
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == SPEAKING
    assert sorted(body["questions"]) == ["said_to", "wants_stop"]


def test_a_question_while_the_agent_is_silent_asks_only_who_the_words_are_for(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, JsonValue]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(await request.json())
        return web.json_response({"answers": {"said_to": _said_to(0.9)}})

    async def scenario() -> Verdict | None:
        async with jev(monkeypatch, handler) as http:
            return await typesafe.TypesafeJudge().ask(LISTENING, {"api_key": "k"}, {}, http)

    assert asyncio.run(scenario()) == {"said_to": "agent", "wants_stop": None}
    assert sorted(tp.cast(dict[str, tp.Any], seen[0])["questions"]) == ["said_to"]


def test_a_failed_call_is_no_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"error": "boom"}, status=500)

    async def scenario() -> Verdict | None:
        async with jev(monkeypatch, handler) as http:
            return await typesafe.TypesafeJudge().ask(SPEAKING, {"api_key": "k"}, {}, http)

    assert asyncio.run(scenario()) is None


def test_a_late_answer_is_no_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(typesafe, "JEV_TIMEOUT_MS", 20)
    release = asyncio.Event()

    async def handler(_request: web.Request) -> web.Response:
        await release.wait()
        return web.json_response({"answers": {"said_to": _said_to(0.9)}})

    async def scenario() -> Verdict | None:
        async with jev(monkeypatch, handler) as http:
            verdict = await typesafe.TypesafeJudge().ask(LISTENING, {"api_key": "k"}, {}, http)
            release.set()
            return verdict

    assert asyncio.run(scenario()) is None


@pytest.mark.parametrize(
    ("status", "result"), [(200, (True, None)), (401, (False, "invalid api key")), (500, (False, "typesafe returned 500"))]
)
def test_the_check_reads_the_status_of_one_call(monkeypatch: pytest.MonkeyPatch, status: int, result: tuple[bool, str | None]) -> None:
    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"answers": {"said_to": _said_to(0.9)}}, status=status)

    async def scenario() -> tuple[bool, str | None]:
        async with jev(monkeypatch, handler):
            return await typesafe.TypesafeJudge().validate({"api_key": "k"}, {})

    assert asyncio.run(scenario()) == result
