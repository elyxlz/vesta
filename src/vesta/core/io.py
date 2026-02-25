import asyncio
import errno
import os
import types
import typing as tp

import aioconsole

import vesta.models as vm
from vesta import logger

SignalHandler = tp.Callable[[int, types.FrameType | None], None]


async def output_line(text: str, *, is_tool: bool = False) -> None:
    if not text or not text.strip():
        return
    if is_tool:
        logger.tool(text)
    else:
        logger.output(text)


async def input_handler(queue: asyncio.Queue, *, state: vm.State) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput("")
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            logger.user(user_msg.strip())
            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
            if state.shutdown_event:
                state.shutdown_event.set()
            break
        except asyncio.CancelledError:
            break
        except BlockingIOError:
            await asyncio.sleep(0.1)
            continue
        except OSError as e:
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                await asyncio.sleep(0.1)
                continue
            else:
                raise


def make_signal_handler(state: vm.State) -> SignalHandler:
    def handler(signum: int, frame: types.FrameType | None) -> None:
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            if state.shutdown_event:
                state.shutdown_event.set()
        elif state.shutdown_count > 2:
            os._exit(0)

    return handler
