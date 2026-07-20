"""App-chat intake: turn an inbound `message` WS frame into a model turn.

Intake is done in-process, in the coroutine that receives the frame, not by a sidecar subscriber
on the broadcast bus. That subscriber could die (OOM, never respawned after a restore) and silently
drop a message the UI had already echoed as delivered, and the bus drops the oldest event under
load: both wrong for delivery-critical intake. Doing the file write here makes the `user` echo an
honest delivery receipt (see the message-flow section of CLAUDE.md).

`api._recv_loop` is the sole caller: it dispatches a `type:"message"` frame to `handle_app_message`.
"""

import asyncio
import datetime as dt
import logging
import time

import pydantic as pyd

from .config import VestaConfig, atomic_write_text
from .events import EventBus, UserEvent
from .models import State
from .notification import Notification

logger = logging.getLogger("vesta.app_chat_intake")


def _write_app_chat_notification(config: VestaConfig, text: str, intent_id: str | None = None) -> None:
    """Persist an inbound app message as a `source=app-chat` notification file: the in-process intake
    the monitor loop picks up. This is what actually delivers app chat to the model."""
    directory = config.notifications_dir
    directory.mkdir(parents=True, exist_ok=True)
    # `message` is an extra field (Notification allows extras); it renders as the notification's
    # text, matching what the app-chat sidecar used to write. model_validate takes the dict so the
    # extra passes the type checker. intent_id rides along as another extra when the client sent one.
    fields: dict[str, str | bool | dt.datetime] = {
        "timestamp": dt.datetime.now(),
        "source": "app-chat",
        "type": "message",
        "message": text,
        "interrupt": True,
        "reply_hint": "reply with `app-chat send`, and think about how you can best show your personality",
    }
    if intent_id is not None:
        fields["intent_id"] = intent_id
    notif = Notification.model_validate(fields)
    path = directory / f"{time.time_ns()}-app-chat-message.json"
    atomic_write_text(path, notif.model_dump_json())


# Bound on the recently-seen intent_id set (State.seen_intent_ids): the newest N intents dedup a
# retried send-message; older ones age out (a retry that far behind is not a real double-send).
_SEEN_INTENT_IDS_CAP = 256


def _remember_intent(state: State, intent_id: str) -> None:
    """Record an app-chat intent_id as seen, bounded FIFO so the set can't grow without limit."""
    state.seen_intent_ids[intent_id] = None
    while len(state.seen_intent_ids) > _SEEN_INTENT_IDS_CAP:
        state.seen_intent_ids.popitem(last=False)


async def handle_app_message(data: dict[str, pyd.JsonValue], text: str, event_bus: EventBus, config: VestaConfig, state: State) -> None:
    """Emit the `user` echo event (history + broadcast, the chat's own view of the message) and write
    the intake notification the monitor loop turns into a model turn. Intake is the file write, done
    in-process off the loop so a dead subscriber can't drop a message the UI already echoed.

    A message carrying an intent_id already seen is a retry (the client resends on a `503`/timeout);
    it is dropped whole, no second echo and no second intake, so the model never acts on it twice. The
    intent is recorded before the awaited write so a concurrent retry on another socket dedups too.
    Messages without an intent_id are never deduped."""
    intent_id = data["intent_id"] if "intent_id" in data and isinstance(data["intent_id"], str) else None
    if intent_id is not None:
        if intent_id in state.seen_intent_ids:
            logger.debug("dropping duplicate app-chat message intent_id=%s", intent_id)
            return
        _remember_intent(state, intent_id)
    event: UserEvent = {"type": "user", "text": text}
    method = data["input_method"] if "input_method" in data else None
    if isinstance(method, str) and method in ("voice", "typed"):
        event["input_method"] = method
    if intent_id is not None:
        event["intent_id"] = intent_id
    event_bus.emit(event)
    try:
        await asyncio.to_thread(_write_app_chat_notification, config, text, intent_id)
    except OSError as e:
        # A lost intake write must surface loudly, never masquerade as delivered.
        logger.error("failed to write app-chat notification: %s", e)
