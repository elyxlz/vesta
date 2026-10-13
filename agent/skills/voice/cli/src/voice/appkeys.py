"""The objects the server builds once and hands to every handler through the app."""

import pathlib as pl

import aiohttp
from aiohttp import web

from voice.engine.buffers import PlayBuffer

# One client session for calls to the TTS provider and the judge, kept open so a call pays for
# no new connection.
HTTP = web.AppKey("http", aiohttp.ClientSession)
# Play token -> the audio of that play, for the `/voice/play/<token>` route.
PLAYS = web.AppKey("plays", dict[str, PlayBuffer])
DATA_DIR = web.AppKey("data_dir", pl.Path)
