"""Deepgram TTS provider: Aura-2 on the HTTP call.

The voice is the model name, `aura-2-<voice>-<language>`, and each voice speaks one language.
One request takes AURA_MAX_CHARS characters or less, so a longer text is split at sentence ends
and its audio is joined in order.
"""

import re
import typing as tp

import aiohttp

from voice.settings import Domain, JsonValue, SettingDef

from .base import TtsError, Validation, api_key

DEEPGRAM_API = "https://api.deepgram.com"
DEFAULT_VOICE = "aura-2-thalia-en"
AURA_MAX_CHARS = 2000
SYNTHESIS_TIMEOUT_SECS = 120
VALIDATE_TIMEOUT_SECS = 15
VALIDATE_TEXT = "ok"

# Play format -> the query parameters that make it. Aura-2 has no MP3 at 44100 Hz and no PCM at
# 22050 Hz. Opus is left out: a split text is more than one request, and joined Ogg streams do
# not play in every player.
FORMAT_PARAMS: dict[str, dict[str, str]] = {
    "mp3_22050": {"encoding": "mp3"},
    "pcm_16000": {"encoding": "linear16", "container": "none", "sample_rate": "16000"},
    "pcm_24000": {"encoding": "linear16", "container": "none", "sample_rate": "24000"},
    "ulaw_8000": {"encoding": "mulaw", "container": "none", "sample_rate": "8000"},
}

# (model name, voice name, description)
_AURA_VOICES: tuple[tuple[str, str, str], ...] = (
    ("aura-2-amalthea-en", "Amalthea", "Filipino English, feminine: engaging, natural, cheerful"),
    ("aura-2-andromeda-en", "Andromeda", "American English, feminine: casual, expressive, comfortable"),
    ("aura-2-apollo-en", "Apollo", "American English, masculine: confident, comfortable, casual"),
    ("aura-2-arcas-en", "Arcas", "American English, masculine: natural, smooth, clear"),
    ("aura-2-aries-en", "Aries", "American English, masculine: warm, energetic, caring"),
    ("aura-2-asteria-en", "Asteria", "American English, feminine: clear, confident, knowledgeable"),
    ("aura-2-athena-en", "Athena", "American English, feminine: calm, smooth, professional"),
    ("aura-2-atlas-en", "Atlas", "American English, masculine: enthusiastic, confident, friendly"),
    ("aura-2-aurora-en", "Aurora", "American English, feminine: cheerful, expressive, energetic"),
    ("aura-2-callista-en", "Callista", "American English, feminine: clear, energetic, professional"),
    ("aura-2-cora-en", "Cora", "American English, feminine: smooth, melodic, caring"),
    ("aura-2-cordelia-en", "Cordelia", "American English, feminine: approachable, warm, polite"),
    ("aura-2-delia-en", "Delia", "American English, feminine: casual, friendly, breathy"),
    ("aura-2-draco-en", "Draco", "British English, masculine: warm, approachable, baritone"),
    ("aura-2-electra-en", "Electra", "American English, feminine: professional, engaging, knowledgeable"),
    ("aura-2-harmonia-en", "Harmonia", "American English, feminine: empathetic, clear, calm"),
    ("aura-2-helena-en", "Helena", "American English, feminine: caring, natural, friendly, raspy"),
    ("aura-2-hera-en", "Hera", "American English, feminine: smooth, warm, professional"),
    ("aura-2-hermes-en", "Hermes", "American English, masculine: expressive, engaging, professional"),
    ("aura-2-hyperion-en", "Hyperion", "Australian English, masculine: caring, warm, empathetic"),
    ("aura-2-iris-en", "Iris", "American English, feminine: cheerful, positive, approachable"),
    ("aura-2-janus-en", "Janus", "American English, feminine: southern, smooth, trustworthy"),
    ("aura-2-juno-en", "Juno", "American English, feminine: natural, engaging, melodic, breathy"),
    ("aura-2-jupiter-en", "Jupiter", "American English, masculine: expressive, knowledgeable, baritone"),
    ("aura-2-luna-en", "Luna", "American English, feminine: friendly, natural, engaging"),
    ("aura-2-mars-en", "Mars", "American English, masculine: smooth, patient, trustworthy"),
    ("aura-2-minerva-en", "Minerva", "American English, feminine: positive, friendly, natural"),
    ("aura-2-neptune-en", "Neptune", "American English, masculine: professional, patient, polite"),
    ("aura-2-odysseus-en", "Odysseus", "American English, masculine: calm, smooth, professional"),
    ("aura-2-ophelia-en", "Ophelia", "American English, feminine: expressive, enthusiastic, cheerful"),
    ("aura-2-orion-en", "Orion", "American English, masculine: approachable, calm, polite"),
    ("aura-2-orpheus-en", "Orpheus", "American English, masculine: professional, clear, trustworthy"),
    ("aura-2-pandora-en", "Pandora", "British English, feminine: smooth, calm, melodic, breathy"),
    ("aura-2-phoebe-en", "Phoebe", "American English, feminine: energetic, warm, casual"),
    ("aura-2-pluto-en", "Pluto", "American English, masculine: smooth, calm, empathetic, baritone"),
    ("aura-2-saturn-en", "Saturn", "American English, masculine: knowledgeable, confident, baritone"),
    ("aura-2-selene-en", "Selene", "American English, feminine: expressive, engaging, energetic"),
    ("aura-2-thalia-en", "Thalia", "American English, feminine: clear, confident, energetic"),
    ("aura-2-theia-en", "Theia", "Australian English, feminine: expressive, polite, sincere"),
    ("aura-2-vesta-en", "Vesta", "American English, feminine: natural, expressive, patient"),
    ("aura-2-zeus-en", "Zeus", "American English, masculine: deep, trustworthy, smooth"),
    ("aura-2-sirio-es", "Sirio", "Mexican Spanish, masculine: calm, professional, empathetic, baritone"),
    ("aura-2-nestor-es", "Nestor", "Peninsular Spanish, masculine: calm, professional, approachable"),
    ("aura-2-carina-es", "Carina", "Peninsular Spanish, feminine: professional, raspy, energetic, breathy"),
    ("aura-2-celeste-es", "Celeste", "Colombian Spanish, feminine: clear, energetic, positive, friendly"),
    ("aura-2-alvaro-es", "Alvaro", "Peninsular Spanish, masculine: calm, professional, clear"),
    ("aura-2-diana-es", "Diana", "Peninsular Spanish, feminine: professional, confident, expressive"),
    ("aura-2-aquila-es", "Aquila", "Latin American Spanish, masculine: expressive, enthusiastic, confident"),
    ("aura-2-selena-es", "Selena", "Latin American Spanish, feminine: approachable, casual, friendly"),
    ("aura-2-estrella-es", "Estrella", "Mexican Spanish, feminine: approachable, natural, calm"),
    ("aura-2-javier-es", "Javier", "Mexican Spanish, masculine: approachable, professional, friendly"),
    ("aura-2-agustina-es", "Agustina", "Peninsular Spanish, feminine: calm, clear, expressive"),
    ("aura-2-antonia-es", "Antonia", "Argentine Spanish, feminine: approachable, enthusiastic, friendly"),
    ("aura-2-gloria-es", "Gloria", "Colombian Spanish, feminine: casual, clear, expressive, smooth"),
    ("aura-2-luciano-es", "Luciano", "Mexican Spanish, masculine: charismatic, cheerful, energetic"),
    ("aura-2-olivia-es", "Olivia", "Mexican Spanish, feminine: breathy, calm, casual, warm"),
    ("aura-2-silvia-es", "Silvia", "Peninsular Spanish, feminine: charismatic, clear, warm"),
    ("aura-2-valerio-es", "Valerio", "Mexican Spanish, masculine: deep, knowledgeable, polite"),
    ("aura-2-beatrix-nl", "Beatrix", "Dutch, feminine: cheerful, friendly, warm"),
    ("aura-2-daphne-nl", "Daphne", "Dutch, feminine: calm, clear, professional"),
    ("aura-2-cornelia-nl", "Cornelia", "Dutch, feminine: approachable, friendly, polite"),
    ("aura-2-sander-nl", "Sander", "Dutch, masculine: calm, clear, deep"),
    ("aura-2-hestia-nl", "Hestia", "Dutch, feminine: approachable, caring, knowledgeable"),
    ("aura-2-lars-nl", "Lars", "Dutch, masculine: breathy, casual, sincere"),
    ("aura-2-roman-nl", "Roman", "Dutch, masculine: calm, casual, deep"),
    ("aura-2-rhea-nl", "Rhea", "Dutch, feminine: caring, knowledgeable, warm"),
    ("aura-2-leda-nl", "Leda", "Dutch, feminine: caring, comfortable, empathetic"),
    ("aura-2-agathe-fr", "Agathe", "French, feminine: charismatic, cheerful, natural"),
    ("aura-2-hector-fr", "Hector", "French, masculine: confident, empathetic, expressive"),
    ("aura-2-elara-de", "Elara", "German, feminine: calm, clear, natural, patient"),
    ("aura-2-aurelia-de", "Aurelia", "German, feminine: approachable, casual, natural"),
    ("aura-2-lara-de", "Lara", "German, feminine: caring, cheerful, empathetic"),
    ("aura-2-julius-de", "Julius", "German, masculine: casual, cheerful, engaging"),
    ("aura-2-fabian-de", "Fabian", "German, masculine: confident, knowledgeable, polite"),
    ("aura-2-kara-de", "Kara", "German, feminine: caring, empathetic, professional"),
    ("aura-2-viktoria-de", "Viktoria", "German, feminine: charismatic, cheerful, warm"),
    ("aura-2-melia-it", "Melia", "Italian, feminine: clear, comfortable, engaging"),
    ("aura-2-elio-it", "Elio", "Italian, masculine: breathy, calm, professional"),
    ("aura-2-flavio-it", "Flavio", "Italian, masculine: confident, deep, empathetic"),
    ("aura-2-maia-it", "Maia", "Italian, feminine: caring, energetic, expressive"),
    ("aura-2-cinzia-it", "Cinzia", "Italian, feminine: approachable, friendly, warm"),
    ("aura-2-cesare-it", "Cesare", "Italian, masculine: clear, empathetic, natural"),
    ("aura-2-livia-it", "Livia", "Italian, feminine: approachable, cheerful, engaging"),
    ("aura-2-dionisio-it", "Dionisio", "Italian, masculine: confident, friendly, melodic"),
    ("aura-2-demetra-it", "Demetra", "Italian, feminine: calm, comfortable, patient"),
    ("aura-2-uzume-ja", "Uzume", "Japanese, feminine: approachable, clear, polite"),
    ("aura-2-ebisu-ja", "Ebisu", "Japanese, masculine: calm, deep, natural"),
    ("aura-2-fujin-ja", "Fujin", "Japanese, masculine: calm, confident, professional"),
    ("aura-2-izanami-ja", "Izanami", "Japanese, feminine: approachable, clear, polite"),
    ("aura-2-ama-ja", "Ama", "Japanese, feminine: casual, comfortable, confident"),
)

_SENTENCE_END = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")


def split_text(text: str, limit: int = AURA_MAX_CHARS) -> list[str]:
    """Parts of `limit` characters or less, cut at sentence ends. A sentence longer than the
    limit is cut at a space, and a word longer than the limit is cut where the limit falls."""
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text.strip()):
        candidate = f"{current} {sentence}" if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        rest = sentence
        while len(rest) > limit:
            cut = rest.rfind(" ", 0, limit + 1)
            cut = cut if cut > 0 else limit
            parts.append(rest[:cut])
            rest = rest[cut:].lstrip()
        current = rest
    if current:
        parts.append(current)
    return parts


class DeepgramTts:
    needs_key = True
    voice_setting = "aura_voice"
    formats = frozenset(FORMAT_PARAMS)
    reply_hint = ""

    def settings_schema(self) -> list[SettingDef]:
        return [
            {
                "key": "aura_voice",
                "type": "select",
                "label": "voice",
                "description": "select a voice for speech synthesis; each voice speaks one language",
                "default": DEFAULT_VOICE,
                "options": [{"value": model, "label": name, "description": description} for model, name, description in _AURA_VOICES],
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
        params = {"model": voice, **FORMAT_PARAMS[audio_format]}
        headers = {"Authorization": f"Token {api_key(creds)}"}
        for part in split_text(text):
            try:
                async with http.post(
                    f"{DEEPGRAM_API}/v1/speak",
                    params=params,
                    headers=headers,
                    json={"text": part},
                    timeout=aiohttp.ClientTimeout(total=SYNTHESIS_TIMEOUT_SECS),
                ) as upstream:
                    if upstream.status != 200:
                        raise TtsError(f"deepgram returned {upstream.status}: {await _error_message(upstream)}")
                    async for chunk in upstream.content.iter_any():
                        yield chunk
            except (TimeoutError, aiohttp.ClientError) as e:
                raise TtsError(f"deepgram request failed: {e}") from e

    async def subscription(self, _creds: dict[str, str]) -> dict[str, JsonValue]:
        # Deepgram has no character quota, so there is no number to report.
        return {}

    async def validate(self, creds: dict[str, str], _settings: Domain) -> Validation:
        """Synthesize two characters, which tests the one permission that the role needs."""
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{DEEPGRAM_API}/v1/speak",
                    params={"model": DEFAULT_VOICE, **FORMAT_PARAMS["mp3_22050"]},
                    headers={"Authorization": f"Token {api_key(creds)}"},
                    json={"text": VALIDATE_TEXT},
                    timeout=aiohttp.ClientTimeout(total=VALIDATE_TIMEOUT_SECS),
                ) as resp,
            ):
                if resp.status == 200:
                    return True, None
                message = await _error_message(resp)
                return False, "invalid api key" if "INVALID_AUTH" in message else message
        except (TimeoutError, aiohttp.ClientError) as e:
            return False, f"deepgram request failed: {e}"


async def _error_message(resp: aiohttp.ClientResponse) -> str:
    """`err_code: err_msg` from a Deepgram error body, or the status when the body has neither."""
    try:
        body = await resp.json()
    except (aiohttp.ContentTypeError, ValueError):
        return f"status {resp.status}"
    if not isinstance(body, dict):
        return f"status {resp.status}"
    code = body["err_code"] if "err_code" in body else ""
    message = body["err_msg"] if "err_msg" in body else ""
    return f"{code}: {message}".strip(": ") or f"status {resp.status}"
