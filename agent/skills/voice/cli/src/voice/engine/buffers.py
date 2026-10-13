"""The audio of one play: synthesis writes it, and each reader gets it from the first byte.

Synthesis starts when `speak` arrives, before any client asks for the audio, so the buffer is
what lets a reader that comes later, or a second reader, get the whole play.
"""

import asyncio
import dataclasses as dc
import typing as tp


@dc.dataclass
class PlayBuffer:
    audio_format: str
    chunks: list[bytes] = dc.field(default_factory=list)
    # Synthesis is over: all the audio is in `chunks`, or it failed.
    done: bool = False
    error: str | None = None
    changed: asyncio.Condition = dc.field(default_factory=asyncio.Condition)


async def fill(buffer: PlayBuffer, audio: tp.AsyncIterator[bytes]) -> None:
    """Copy `audio` into the buffer. An error of `audio` propagates after the buffer is marked."""
    try:
        async for chunk in audio:
            async with buffer.changed:
                buffer.chunks.append(chunk)
                buffer.changed.notify_all()
    except Exception as e:
        buffer.error = str(e)
        raise
    finally:
        async with buffer.changed:
            buffer.done = True
            buffer.changed.notify_all()


async def first_chunk(buffer: PlayBuffer) -> bool:
    """Wait until the buffer has audio or is over. False means that it ended with no audio."""
    async with buffer.changed:
        await buffer.changed.wait_for(lambda: bool(buffer.chunks) or buffer.done)
    return bool(buffer.chunks)


async def read(buffer: PlayBuffer) -> tp.AsyncIterator[bytes]:
    """The audio from the first byte, following synthesis until it is over."""
    index = 0
    while True:
        async with buffer.changed:
            await buffer.changed.wait_for(lambda i=index: i < len(buffer.chunks) or buffer.done)
            if index >= len(buffer.chunks):
                return
            chunk = buffer.chunks[index]
        index += 1
        yield chunk
