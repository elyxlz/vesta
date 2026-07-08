"""ElevenLabs TTS provider — HTTP streaming."""

import typing as tp

import aiohttp
from aiohttp import web

import logging

logger = logging.getLogger("voice.elevenlabs")

ELEVENLABS_API = "https://api.elevenlabs.io"
MODEL_ID = "eleven_flash_v2_5"
OUTPUT_FORMAT = "mp3_22050_32"
DEFAULT_VOICE_ID = "FGY2WhTYpPnrIDTdsKH5"  # Laura

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
    name = "elevenlabs"

    def settings_schema(self) -> list[dict]:
        return [
            {
                "key": "selected_voice_id",
                "type": "select",
                "label": "voice",
                "description": "select a voice for speech synthesis",
                "default": DEFAULT_VOICE_ID,
                "options": [
                    {"value": v["id"], "label": v["name"], "description": v.get("description", ""), "preview": v.get("preview", "")}
                    for v in PREMADE_VOICES
                ],
            },
        ]

    async def speak(
        self,
        text: str,
        voice_id: str,
        creds: dict[str, str],
        request: web.Request,
    ) -> web.StreamResponse:
        api_key = creds.get("api_key", "")
        url = f"{ELEVENLABS_API}/v1/text-to-speech/{voice_id}/stream"
        payload = {"text": text, "model_id": MODEL_ID, "output_format": OUTPUT_FORMAT}

        session = aiohttp.ClientSession()
        try:
            upstream = await session.post(
                url,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            )
        except (TimeoutError, aiohttp.ClientError) as e:
            await session.close()
            logger.error(f"elevenlabs request failed: {e}")
            return web.json_response({"error": f"elevenlabs request failed: {e}"}, status=502)

        if upstream.status != 200:
            body_text = await upstream.text()
            upstream.release()
            await session.close()
            return web.json_response({"error": f"elevenlabs returned {upstream.status}", "body": body_text[:500]}, status=upstream.status)

        response = web.StreamResponse(status=200, headers={"Content-Type": "audio/mpeg"})
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
        finally:
            upstream.release()
            await session.close()
        return response

    def premade_voices(self) -> list[dict]:
        return list(PREMADE_VOICES)

    async def subscription(self, creds: dict[str, str]) -> dict:
        api_key = creds.get("api_key", "")
        return await _fetch_subscription(api_key)

    async def validate(self, api_key: str) -> tuple[bool, str | None]:
        result = await _fetch_subscription(api_key)
        if "error" in result:
            msg = result["error"]
            if "401" in str(msg):
                return False, "invalid api key"
            return False, str(msg)
        return True, None


async def _fetch_subscription(api_key: str) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ELEVENLABS_API}/v1/user/subscription",
                headers={"xi-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body: tp.Any = await resp.json()
                if resp.status != 200:
                    return {"error": f"status {resp.status}", "body": body}
                return body
    except (TimeoutError, aiohttp.ClientError) as e:
        return {"error": str(e)}
