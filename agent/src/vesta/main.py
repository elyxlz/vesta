"""Vesta main entry point and orchestration."""

import asyncio
import datetime as dt
import errno
import json
import os
import signal
import types
import typing as tp

import aioconsole
from rich import print_json

import vesta.models as vm
from vesta import logger
from vesta.api import start_ws_server
from vesta.core.history import open_history
from vesta.core.init import get_memory_path
from vesta.core.loops import message_processor, monitor_loop, queue_greeting

SignalHandler = tp.Callable[[int, types.FrameType | None], None]


async def input_handler(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State) -> None:
    while not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput("")
            if state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            logger.user(user_msg.strip())
            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
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


def _make_signal_handler(state: vm.State, *, allow_force_exit: bool = False) -> SignalHandler:
    def handler(signum: int, frame: types.FrameType | None) -> None:
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            state.graceful_shutdown.set()
        elif allow_force_exit and state.shutdown_count > 2:
            os._exit(0)
        else:
            state.shutdown_event.set()

    return handler


async def context_monitor(
    state: vm.State, config: vm.VestaConfig, queue: asyncio.Queue[tuple[str, bool]]
) -> None:
    """Periodically check SDK context usage and log it.

    Nap escalation (requires nap + transcript skills):
    - At 50%+: inject a system message asking the agent to request a nap every 5 minutes.
    - At 80%+: inject a system message telling the agent to nap immediately.
    """
    INTERVAL = 600  # 10 minutes — normal reporting interval
    NAP_ASK_INTERVAL = 300  # 5 minutes — re-ask interval once over threshold
    NAP_ASK_THRESHOLD = 50.0
    NAP_FORCE_THRESHOLD = 80.0
    nap_asking = False
    nap_forced = False

    try:
        while not state.shutdown_event.is_set():
            interval = NAP_ASK_INTERVAL if nap_asking else INTERVAL
            try:
                await asyncio.wait_for(state.shutdown_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

            client = state.client
            if not client:
                continue

            try:
                usage = await client.get_context_usage()
                total = usage.get("totalTokens", 0)
                max_tok = usage.get("maxTokens", 1)
                pct = usage.get("percentage", total / max_tok * 100 if max_tok else 0)
                auto_threshold = usage.get("autoCompactThreshold", 0)
                model = usage.get("model", "unknown")

                categories = usage.get("categories", [])
                cat_parts = []
                for cat in sorted(categories, key=lambda c: c.get("tokens", 0), reverse=True):
                    name = cat.get("name", "?")
                    tokens = cat.get("tokens", 0)
                    if tokens > 0:
                        cat_parts.append(f"{name}={tokens:,}")
                cat_summary = ", ".join(cat_parts[:5])

                log_line = (
                    f"[context] {pct:.1f}% ({total:,}/{max_tok:,}) "
                    f"model={model} compact_at={auto_threshold:,} | {cat_summary}"
                )
                logger.info(log_line)

                full_data = {
                    "percentage": round(pct, 1),
                    "totalTokens": total,
                    "maxTokens": max_tok,
                    "autoCompactThreshold": auto_threshold,
                    "model": model,
                    "categories": categories,
                }
                logger.debug(f"[context_full] {json.dumps(full_data, default=str)}")

                state.event_bus.emit({
                    "type": "assistant",
                    "text": f"[context] {pct:.1f}% used ({total:,}/{max_tok:,} tokens)",
                    "source": "context_monitor",
                })

                # --- Nap escalation ---
                if pct >= NAP_FORCE_THRESHOLD and not nap_forced:
                    nap_forced = True
                    logger.info(f"[nap] Context at {pct:.1f}% — forcing nap")
                    await queue.put((
                        f"[System: context monitor] Context usage is at {pct:.1f}% — past 80% threshold. "
                        "Run the nap skill NOW. Do not ask permission — proceed immediately.",
                        False,
                    ))
                elif pct >= NAP_ASK_THRESHOLD and not nap_forced:
                    if not nap_asking:
                        nap_asking = True
                    logger.info(f"[nap] Context at {pct:.1f}% — asking permission")
                    await queue.put((
                        f"[System: context monitor] Context usage is at {pct:.1f}%. "
                        "Ask the user if you can take a nap. Include the percentage. "
                        "If they say wait, hold. You'll be asked again in 5 minutes with an updated %.",
                        False,
                    ))

            except Exception as e:
                logger.warning(f"Context monitor error: {e}")

    except asyncio.CancelledError:
        pass


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False, crashed: bool = False) -> None:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")
    (config.data_dir / "run_marker").touch()

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    ws_runner = await start_ws_server(state.event_bus, message_queue, state, config)
    logger.init(f"WebSocket server started on port {config.ws_port}")

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
        asyncio.create_task(context_monitor(state, config, queue=message_queue)),
    ]

    reason = "first_start" if first_start else ("crash — restarted after unexpected exit" if crashed else "restart — clean restart")
    await queue_greeting(message_queue, config=config, reason=reason)

    try:
        await state.graceful_shutdown.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    if not state.shutdown_event.is_set():
        state.shutdown_event.set()

    logger.shutdown("Shutting down...")

    for task in tasks:
        task.cancel()

    _, pending = await asyncio.wait(tasks, timeout=5)
    if pending:
        logger.shutdown("Shutdown timed out (SDK cleanup hung), forcing exit")
        os._exit(1)
    await ws_runner.cleanup()
    (config.data_dir / "run_marker").unlink(missing_ok=True)
    logger.shutdown("sweet dreams!")


def _detect_crash(config: vm.VestaConfig) -> bool:
    run_marker = config.data_dir / "run_marker"
    crashed = run_marker.exists()
    run_marker.unlink(missing_ok=True)
    return crashed


def _read_last_dreamer_run(config: vm.VestaConfig) -> dt.datetime | None:
    path = config.data_dir / "last_dreamer_run"
    try:
        if path.exists():
            return dt.datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("Could not read last_dreamer_run file")
    return None


def init_state(*, config: vm.VestaConfig) -> tuple[vm.State, bool]:
    session_id = None
    try:
        if config.session_file.exists():
            session_id = config.session_file.read_text().strip() or None
    except (OSError, UnicodeDecodeError):
        logger.warning("Could not read session file, starting fresh")

    crashed = _detect_crash(config)
    if crashed:
        logger.init("Crash detected")

    last_dreamer_run = _read_last_dreamer_run(config)

    if session_id:
        logger.init(f"Resuming session {session_id[:16]}...")
    return vm.State(last_dreamer_run=last_dreamer_run, session_id=session_id), crashed


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.root, config.notifications_dir, config.logs_dir, config.data_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting")

    memory_path = get_memory_path(config)
    first_start = not memory_path.exists() or "[Unknown - need to ask]" in memory_path.read_text()
    initial_state, crashed = init_state(config=config)
    initial_state.history = open_history(config.history_db)
    logger.init("Starting main loop...")
    await run_vesta(config, state=initial_state, first_start=first_start, crashed=crashed)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")


if __name__ == "__main__":
    main()
