"""ElevenLabs TTS provider: `eleven_v4_turbo` on the HTTP streaming call.

Text in square brackets is an instruction to this model, not speech: `[laughs]` or `[whispering]`
changes how the line is said. The provider sends the text as it gets it.
"""

import asyncio
import json
import typing as tp

import aiohttp

from voice.settings import Domain, JsonValue, SettingDef

from . import limit
from .base import TtsError, Usage, Validation, api_key, no_usage, number_in

ELEVENLABS_API = "https://api.elevenlabs.io"
MODEL_ID = "eleven_v4_turbo"
DEFAULT_VOICE_ID = "FGY2WhTYpPnrIDTdsKH5"  # Laura
SYNTHESIS_TIMEOUT_SECS = 120
ERROR_BODY_CHARS = 300
# The waits before each new try of a request that ElevenLabs refused for too many requests at
# once. A 429 for any other reason (the quota) is not tried again.
CONCURRENCY_RETRY_SECS: tuple[float, ...] = (0.25, 0.5, 1.0)
CONCURRENCY_LIMIT_CODE = "concurrent_limit_exceeded"

# Play format -> the ElevenLabs output_format that makes it.
OUTPUT_FORMATS: dict[str, str] = {
    "mp3_22050": "mp3_22050_32",
    "mp3_44100": "mp3_44100_128",
    "pcm_16000": "pcm_16000",
    "pcm_22050": "pcm_22050",
    "pcm_24000": "pcm_24000",
    "ulaw_8000": "ulaw_8000",
    "opus_48000": "opus_48000_96",
}

PREMADE_VOICES: list[dict[str, str]] = [
    {
        "id": "CwhRBWXzGAHq8TQ4Fs17",
        "name": "Roger",
        "description": "Laid-back, casual, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/CwhRBWXzGAHq8TQ4Fs17/58ee3ff5-f6f2-4628-93b8-e38eb31806b0.mp3",
    },
    {
        "id": "EXAVITQu4vr4xnSDxMaL",
        "name": "Sarah",
        "description": "Mature, reassuring, American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/EXAVITQu4vr4xnSDxMaL/01a3e33c-6e99-4ee7-8543-ff2216a32186.mp3",
    },
    {
        "id": "FGY2WhTYpPnrIDTdsKH5",
        "name": "Laura",
        "description": "Enthusiastic, quirky, American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/FGY2WhTYpPnrIDTdsKH5/67341759-ad08-41a5-be6e-de12fe448618.mp3",
    },
    {
        "id": "IKne3meq5aSn9XLyUdCD",
        "name": "Charlie",
        "description": "Deep, confident, Australian male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/IKne3meq5aSn9XLyUdCD/102de6f2-22ed-43e0-a1f1-111fa75c5481.mp3",
    },
    {
        "id": "JBFqnCBsd6RMkjVDRZzb",
        "name": "George",
        "description": "Warm, captivating, British male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/JBFqnCBsd6RMkjVDRZzb/e6206d1a-0721-4787-aafb-06a6e705cac5.mp3",
    },
    {
        "id": "N2lVS1w4EtoT3dr4eOWO",
        "name": "Callum",
        "description": "Husky, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/N2lVS1w4EtoT3dr4eOWO/ac833bd8-ffda-4938-9ebc-b0f99ca25481.mp3",
    },
    {
        "id": "SAz9YHcvj6GT2YYXdXww",
        "name": "River",
        "description": "Relaxed, neutral, informative",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/SAz9YHcvj6GT2YYXdXww/e6c95f0b-2227-491a-b3d7-2249240decb7.mp3",
    },
    {
        "id": "TX3LPaxmHKxFdv7VOQHJ",
        "name": "Liam",
        "description": "Energetic, young American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/TX3LPaxmHKxFdv7VOQHJ/63148076-6363-42db-aea8-31424308b92c.mp3",
    },
    {
        "id": "Xb7hH8MSUJpSbSDYk0k2",
        "name": "Alice",
        "description": "Clear, engaging, British female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/Xb7hH8MSUJpSbSDYk0k2/d10f7534-11f6-41fe-a012-2de1e482d336.mp3",
    },
    {
        "id": "XrExE9yKIg1WjnnlVkGX",
        "name": "Matilda",
        "description": "Knowledgeable, professional, American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/XrExE9yKIg1WjnnlVkGX/b930e18d-6b4d-466e-bab2-0ae97c6d8535.mp3",
    },
    {
        "id": "bIHbv24MWmeRgasZH58o",
        "name": "Will",
        "description": "Relaxed optimist, young American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/bIHbv24MWmeRgasZH58o/8caf8f3d-ad29-4980-af41-53f20c72d7a4.mp3",
    },
    {
        "id": "cgSgspJ2msm6clMCkdW9",
        "name": "Jessica",
        "description": "Playful, bright, young American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/cgSgspJ2msm6clMCkdW9/56a97bf8-b69b-448f-846c-c3a11683d45a.mp3",
    },
    {
        "id": "cjVigY5qzO86Huf0OWal",
        "name": "Eric",
        "description": "Smooth, trustworthy, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/cjVigY5qzO86Huf0OWal/d098fda0-6456-4030-b3d8-63aa048c9070.mp3",
    },
    {
        "id": "iP95p4xoKVk53GoZ742B",
        "name": "Chris",
        "description": "Charming, down-to-earth, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/iP95p4xoKVk53GoZ742B/3f4bde72-cc48-40dd-829f-57fbf906f4d7.mp3",
    },
    {
        "id": "nPczCjzI2devNBz1zQrb",
        "name": "Brian",
        "description": "Deep, resonant, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/nPczCjzI2devNBz1zQrb/2dd3e72c-4fd3-42f1-93ea-abc5d4e5aa1d.mp3",
    },
    {
        "id": "onwK4e9ZLuTAKqWW03F9",
        "name": "Daniel",
        "description": "Steady broadcaster, British male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/onwK4e9ZLuTAKqWW03F9/7eee0236-1a72-4b86-b303-5dcadc007ba9.mp3",
    },
    {
        "id": "pFZP5JQG7iQjIQuC4Bku",
        "name": "Lily",
        "description": "Velvety, British female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/pFZP5JQG7iQjIQuC4Bku/89b68b35-b3dd-4348-a84a-a3c13a3c2b30.mp3",
    },
    {
        "id": "pNInz6obpgDQGcFmaJgB",
        "name": "Adam",
        "description": "Dominant, firm, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/pNInz6obpgDQGcFmaJgB/d6905d7a-dd26-4187-bfff-1bd3a5ea7cac.mp3",
    },
    {
        "id": "pqHfZKP75CvOlQylNhV4",
        "name": "Bill",
        "description": "Wise, mature, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/pqHfZKP75CvOlQylNhV4/d782b3ff-84ba-4029-848c-acf01285524d.mp3",
    },
]


class ElevenLabsTts:
    needs_key = True
    voice_setting = "selected_voice_id"
    formats = frozenset(OUTPUT_FORMATS)
    reply_hint = (
        "this reply can be spoken aloud, and the voice performs text in square brackets as a direction and does not say it "
        "([laughs], [whispers]), so put a word in square brackets only as a direction"
    )

    def settings_schema(self) -> list[SettingDef]:
        return [
            {
                "key": "selected_voice_id",
                "type": "select",
                "label": "voice",
                "description": "select a voice for speech synthesis",
                "default": DEFAULT_VOICE_ID,
                "options": [
                    {"value": v["id"], "label": v["name"], "description": v["description"], "preview": v["preview"]} for v in PREMADE_VOICES
                ],
            },
        ]

    async def synthesize(
        self,
        text: str,
        voice: str,
        audio_format: str,
        creds: dict[str, str],
        _settings: Domain,
        http: aiohttp.ClientSession,
    ) -> tp.AsyncIterator[bytes]:
        url = f"{ELEVENLABS_API}/v1/text-to-speech/{voice}/stream"
        lowered = False
        for attempt in range(len(CONCURRENCY_RETRY_SECS) + 1):
            try:
                async with http.post(
                    url,
                    # ElevenLabs reads the format from the query only. In the body it has no effect.
                    params={"output_format": OUTPUT_FORMATS[audio_format]},
                    headers={"xi-api-key": api_key(creds)},
                    json={"text": text, "model_id": MODEL_ID},
                    timeout=aiohttp.ClientTimeout(total=SYNTHESIS_TIMEOUT_SECS),
                ) as upstream:
                    if upstream.status != 200:
                        body = await upstream.text()
                        # No audio has gone out yet, so a new try is safe.
                        if upstream.status == 429 and is_concurrency_limit(body) and attempt < len(CONCURRENCY_RETRY_SECS):
                            if not lowered:
                                limit.for_provider(self).lower()
                                lowered = True
                            await asyncio.sleep(CONCURRENCY_RETRY_SECS[attempt])
                            continue
                        raise TtsError(f"elevenlabs returned {upstream.status}: {body[:ERROR_BODY_CHARS]}")
                    async for chunk in upstream.content.iter_any():
                        yield chunk
                    return
            except (TimeoutError, aiohttp.ClientError) as e:
                raise TtsError(f"elevenlabs request failed: {e}") from e

    async def usage(self, creds: dict[str, str]) -> Usage:
        return await account_usage(api_key(creds))

    async def validate(self, creds: dict[str, str], _settings: Domain) -> Validation:
        return subscription_validation(await fetch_subscription(api_key(creds)))


def is_concurrency_limit(body: str) -> bool:
    """True for the 429 that means too many requests at once, not an empty quota."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return False
    detail = parsed["detail"] if isinstance(parsed, dict) and "detail" in parsed else None
    if not isinstance(detail, dict):
        return False
    return any(key in detail and detail[key] == CONCURRENCY_LIMIT_CODE for key in ("code", "status"))


def subscription_validation(result: dict[str, JsonValue]) -> Validation:
    """Read a subscription probe as a key check. A key with limited permissions answers
    `missing_permissions` here and still works for its role, so only `invalid_api_key` means an
    invalid key."""
    if "error" not in result:
        return True, None
    body = result["body"] if "body" in result else None
    detail = body["detail"] if isinstance(body, dict) and "detail" in body else None
    status = detail["status"] if isinstance(detail, dict) and "status" in detail else None
    if status == "missing_permissions":
        return True, None
    if status == "invalid_api_key":
        return False, "invalid api key"
    return False, str(result["error"])


async def account_usage(key: str) -> Usage:
    """The credits of the subscription that both ElevenLabs roles use."""
    body = await fetch_subscription(key)
    count, limit = number_in(body, "character_count"), number_in(body, "character_limit")
    if count is None or limit is None:
        return no_usage()
    return {"used": {"amount": count, "unit": "credits"}, "left": {"amount": max(limit - count, 0.0), "unit": "credits"}}


async def fetch_subscription(api_key: str) -> dict[str, JsonValue]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"{ELEVENLABS_API}/v1/user/subscription",
                headers={"xi-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            body: dict[str, JsonValue] = await resp.json()
            if resp.status != 200:
                return {"error": f"status {resp.status}", "body": body}
            return body
    except (TimeoutError, aiohttp.ClientError) as e:
        return {"error": str(e)}
