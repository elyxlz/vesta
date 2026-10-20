"""The objects the server builds once and hands to every handler through the app."""

import pathlib as pl

import aiohttp
from aiohttp import web

from voice.engine.buffers import PlayBuffer
from voice.engine.detector import Cache

# One client session for calls to the TTS provider and the judge. It keeps its connections
# open between replies, so a call pays for no new handshake.
HTTP = web.AppKey("http", aiohttp.ClientSession)
# Play token -> the audio of that play, for the `/voice/play/<token>` route.
PLAYS = web.AppKey("plays", dict[str, PlayBuffer])
DATA_DIR = web.AppKey("data_dir", pl.Path)
# (model file, its mtime) -> the loaded wake word model, or why it does not load. A loaded model
# keeps no audio state, so every session shares it.
DETECTORS = web.AppKey("detectors", Cache)
