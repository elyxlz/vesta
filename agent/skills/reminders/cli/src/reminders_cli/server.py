import logging
import threading

import uvicorn
from fastapi import FastAPI, HTTPException

from . import commands
from .config import Config

logger = logging.getLogger(__name__)


# --- App factory ---


def _create_app(config: Config) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc):
        raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/reminders")
    def list_reminders(limit: int = 50, show_deleted: bool = False):
        return commands.remind_list(config, limit=limit, show_deleted=show_deleted)

    @app.post("/reminders", status_code=201)
    def set_reminder(body: commands.ReminderSpec):
        return commands.remind_set(config, body)

    @app.get("/reminders/{reminder_id}")
    def get_reminder(reminder_id: str):
        return commands.remind_get(config, reminder_id=reminder_id)

    @app.patch("/reminders/{reminder_id}")
    def update_reminder(reminder_id: str, body: commands.UpdateSpec):
        return commands.remind_update(config, reminder_id=reminder_id, spec=body)

    @app.post("/reminders/{reminder_id}/snooze")
    def snooze_reminder(reminder_id: str, body: commands.SnoozeSpec):
        return commands.remind_snooze(config, reminder_id=reminder_id, spec=body)

    @app.delete("/reminders/{reminder_id}")
    def delete_reminder(reminder_id: str):
        return commands.remind_delete(config, reminder_id=reminder_id)

    return app


def start_server(config: Config, port: int) -> uvicorn.Server:
    app = _create_app(config)
    uv_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(uv_config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server
