"""TypeSafe judge provider: Jev answers who the words are for, and if the user wants a stop.

Jev returns a probability for each answer. This module owns the model, the two questions, the
thresholds that turn the probabilities into a Verdict, and the timeout. A call has no retry: the
next live text is the retry.
"""

import logging

import aiohttp

from voice.settings import Domain, SettingDef

from .base import Question, Validation, Verdict

logger = logging.getLogger("voice.typesafe")

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"
JEV_TIMEOUT_MS = 600
VALIDATE_TIMEOUT_SECS = 10
# `said_to` is `agent` at this probability or more. An echo of the agent's own voice gives the
# `agent` answer at most 0.49, and words said to the agent give 0.73 or more.
AGENT_MIN = 0.5
# `wants_stop` is true at this probability or more. A stop gives 0.69 or more, and a
# backchannel ("mhm", "yeah") gives 0.09 or less.
STOP_MIN = 0.5

SAID_TO_QUESTION = {
    "type": "choice",
    "instructions": (
        "`user_saying` is text that a speech recognizer made from the microphone of the user's device. "
        "It can also hold other voices or sounds. Who are the words in `user_saying` said to?"
    ),
    "criteria": {
        "agent": "Words said to `agent_name`: a question, request, answer, reply, or comment directed at `agent_name`.",
        "echo": (
            "Words that appear in `agent_saying`, in the same order, with no other words added: `agent_name`'s own "
            "voice picked up by the microphone. Never choose this when `agent_saying` is null."
        ),
        "other_person": "Real words said to someone other than `agent_name`: a person in the room, a phone call, or a TV, radio, or video.",
        "not_speech": (
            "No real words: only a sound tag such as (music) or [laughter], only a filler sound (um, uh, hmm), "
            "or a string that is not a real phrase."
        ),
    },
}
WANTS_STOP_QUESTION = {
    "type": "noul",
    "instructions": (
        "`agent_name` is saying `agent_saying` aloud, and at the same time the user said `user_saying`. "
        "Does the user want `agent_name` to stop talking?"
    ),
    "criteria": {
        "true": (
            "They ask `agent_name` to stop or wait, correct `agent_name`, disagree, ask a question, answer a question "
            "that `agent_saying` asks, or start a new subject."
        ),
        "false": "They only show that they listen or agree (mhm, yeah, ok, right, I see, laughter), and `agent_saying` asks them no question.",
    },
}
NOT_AGENT = ("echo", "other_person", "not_speech")


def verdict_from(answers: dict[str, dict[str, dict[str, float] | float | str]]) -> Verdict | None:
    """Turn Jev's answers into a Verdict, or None when the answer has no usable shape."""
    try:
        probabilities = answers["said_to"]["probabilities"]
        if not isinstance(probabilities, dict):
            return None
        said_to = "agent" if probabilities["agent"] >= AGENT_MIN else max(NOT_AGENT, key=lambda option: probabilities[option])
        wants_stop: bool | None = None
        if "wants_stop" in answers:
            stop = answers["wants_stop"]["noul"]
            if not isinstance(stop, int | float):
                return None
            wants_stop = stop >= STOP_MIN
    except (KeyError, TypeError):
        return None
    return {"said_to": said_to, "wants_stop": wants_stop}


class TypesafeJudge:
    name = "typesafe"
    needs_key = True

    def settings_schema(self) -> list[SettingDef]:
        return []

    async def ask(self, question: Question, creds: dict[str, str], _settings: Domain, http: aiohttp.ClientSession) -> Verdict | None:
        questions = {"said_to": SAID_TO_QUESTION}
        if question["agent_saying"] is not None:
            questions["wants_stop"] = WANTS_STOP_QUESTION
        try:
            async with http.post(
                JEV_URL,
                json={"state": question, "model": JEV_MODEL, "questions": questions},
                headers={"Authorization": f"Bearer {_api_key(creds)}"},
                timeout=aiohttp.ClientTimeout(total=JEV_TIMEOUT_MS / 1000),
            ) as resp:
                if resp.status != 200:
                    logger.warning("jev returned %s", resp.status)
                    return None
                body = await resp.json()
        except (TimeoutError, aiohttp.ClientError, ValueError) as e:
            logger.warning("jev call failed: %s", e)
            return None
        return verdict_from(body["answers"]) if isinstance(body, dict) and "answers" in body else None

    async def validate(self, creds: dict[str, str], _settings: Domain) -> Validation:
        probe: Question = {"agent_name": "agent", "recent": [], "agent_saying": None, "user_saying": "hello"}
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    JEV_URL,
                    json={"state": probe, "model": JEV_MODEL, "questions": {"said_to": SAID_TO_QUESTION}},
                    headers={"Authorization": f"Bearer {_api_key(creds)}"},
                    timeout=aiohttp.ClientTimeout(total=VALIDATE_TIMEOUT_SECS),
                ) as resp,
            ):
                if resp.status in (401, 403):
                    return False, "invalid api key"
                if resp.status != 200:
                    return False, f"typesafe returned {resp.status}"
        except (TimeoutError, aiohttp.ClientError) as e:
            return False, f"typesafe request failed: {e}"
        return True, None


def _api_key(creds: dict[str, str]) -> str:
    return creds["api_key"] if "api_key" in creds else ""
