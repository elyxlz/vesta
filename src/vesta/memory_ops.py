import asyncio
import collections.abc as cab
import contextlib
import datetime as dt

import vesta.memory_agent as vma
import vesta.models as vm
from vesta.agents import backup_all_memories
from vesta.constants import Messages
from vesta.effects import logger
from vesta.models import ConversationMessage


async def get_and_clear_subagent_conversations(state: vm.State) -> dict[str, list[str]]:
    async with state.subagent_conversations_lock:
        conversations = state.subagent_conversations.copy()
        state.subagent_conversations.clear()
        return conversations


async def get_and_clear_conversation_history(state: vm.State) -> list[ConversationMessage]:
    async with state.conversation_history_lock:
        history = state.conversation_history.copy()
        state.conversation_history.clear()
        return history


@contextlib.asynccontextmanager
async def heartbeat_logger(message_fn: cab.Callable[[], str], *, interval: float) -> cab.AsyncIterator[None]:
    async def pulse() -> None:
        while True:
            await asyncio.sleep(interval)
            logger.info(message_fn())

    task = asyncio.create_task(pulse())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def backup_memory_folder(config: vm.VestaSettings) -> None:
    backup_all_memories(config)


async def preserve_memory(state: vm.State, *, config: vm.VestaSettings) -> bool:
    """Preserve memory to disk. Returns True if memory was updated."""
    if config.ephemeral:
        logger.info("Skipping memory preservation (ephemeral mode)")
        return False

    logger.info(f"Preserving memory (timeout {config.memory_agent_timeout}s)...")

    def log_progress(message: str) -> None:
        logger.info(f"Memory agent: {message}")

    start_time = dt.datetime.now()

    def heartbeat_message() -> str:
        elapsed = int((dt.datetime.now() - start_time).total_seconds())
        return f"Memory agent still running... {elapsed}s elapsed"

    async with heartbeat_logger(heartbeat_message, interval=30):
        subagent_convos = await get_and_clear_subagent_conversations(state)
        history = await get_and_clear_conversation_history(state)

        backup_memory_folder(config)

        results = await vma.consolidate_all_memories(
            history if history else None,
            subagent_conversations=subagent_convos,
            config=config,
            progress_callback=log_progress,
        )

        elapsed = (dt.datetime.now() - start_time).total_seconds()

        if results:
            logger.info(Messages.MEMORY_UPDATED)
            for agent_name, diff in results.items():
                logger.info(f"--- {agent_name} memory ---")
                logger.info(diff)
            logger.info(f"[MEMORY] Total preservation time: {elapsed:.1f}s ({len(results)} agents updated)")
            return True
        else:
            logger.info(f"[MEMORY] No significant updates ({elapsed:.1f}s)")
            return False
