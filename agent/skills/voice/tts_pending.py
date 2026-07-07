"""Short-lived id -> text store backing the native-audio TTS stream route.

The app streams TTS through a native ``<audio>`` element (a GET it can
authenticate with ``?token=``) instead of feeding a POST body into MediaSource,
so playback starts at the first byte and streams progressively on every webview
(Android's System WebView would otherwise fall back to buffering the whole clip
then dumping it). See issue #466. ``POST /tts/prepare`` registers the text and
returns an id; ``GET /tts/stream/{id}`` resolves it back and synthesizes.

Entries live until their TTL so a media element that reopens the stream within
the window still resolves; expired ids are pruned lazily on each access.
"""

import secrets

DEFAULT_TTL_SECS = 120.0

# id -> (text, expiry_monotonic)
PendingStore = dict[str, tuple[str, float]]


def prune_expired(store: PendingStore, now: float) -> None:
    for key in [k for k, (_text, expiry) in store.items() if expiry <= now]:
        del store[key]


def register(store: PendingStore, text: str, now: float, ttl: float = DEFAULT_TTL_SECS) -> str:
    prune_expired(store, now)
    token = secrets.token_urlsafe(16)
    store[token] = (text, now + ttl)
    return token


def resolve(store: PendingStore, token: str, now: float) -> str | None:
    prune_expired(store, now)
    if token not in store:
        return None
    return store[token][0]
