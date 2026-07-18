import logging
import threading
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import commands
from .config import Config

logger = logging.getLogger(__name__)


# --- Request bodies ---


class AddTaskBody(BaseModel):
    title: str
    due_datetime: str | None = None
    timezone: str | None = None
    due_in_minutes: int | None = None
    due_in_hours: int | None = None
    due_in_days: int | None = None
    priority: str | int = "normal"
    initial_metadata: str | None = None


class UpdateTaskBody(BaseModel):
    status: Literal["pending", "done"] | None = None
    title: str | None = None
    priority: str | int | None = None
    due_datetime: str | None = None
    timezone: str | None = None
    due_in_minutes: int | None = None
    due_in_hours: int | None = None
    due_in_days: int | None = None


class UpdateReminderBody(BaseModel):
    message: str


class SnoozeReminderBody(BaseModel):
    in_minutes: int | None = None
    in_hours: int | None = None
    in_days: int | None = None
    at: str | None = None
    tz: str | None = None


# --- App factory ---


def _create_app(config: Config) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc):
        raise HTTPException(status_code=400, detail=str(exc))

    # -- Tasks --

    @app.get("/tasks")
    def list_tasks(show_completed: bool = False):
        return commands.list_tasks(config, show_completed=show_completed)

    @app.get("/tasks/search")
    def search_tasks(q: str = Query(), show_completed: bool = False):
        return commands.search_tasks(config, query=q, show_completed=show_completed)

    @app.post("/tasks", status_code=201)
    def add_task(body: AddTaskBody):
        return commands.add_task(
            config,
            title=body.title,
            due=commands.DueSpec(
                due_datetime=body.due_datetime,
                timezone=body.timezone,
                due_in_minutes=body.due_in_minutes,
                due_in_hours=body.due_in_hours,
                due_in_days=body.due_in_days,
            ),
            priority=body.priority,
            initial_metadata=body.initial_metadata,
        )

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        return commands.get_task(config, task_id=task_id)

    @app.patch("/tasks/{task_id}")
    def update_task(task_id: str, body: UpdateTaskBody):
        return commands.update_task(
            config,
            task_id=task_id,
            status=body.status,
            title=body.title,
            priority=body.priority,
            due=commands.DueSpec(
                due_datetime=body.due_datetime,
                timezone=body.timezone,
                due_in_minutes=body.due_in_minutes,
                due_in_hours=body.due_in_hours,
                due_in_days=body.due_in_days,
            ),
        )

    @app.delete("/tasks/{task_id}")
    def delete_task(task_id: str):
        return commands.delete_task(config, task_id=task_id)

    # -- Reminders --

    @app.get("/reminders")
    def list_reminders(task_id: str | None = None, limit: int = 50):
        return commands.remind_list(config, task_id=task_id, limit=limit)

    @app.post("/reminders", status_code=201)
    def set_reminder(body: commands.ReminderSpec):
        return commands.remind_set(config, body)

    @app.patch("/reminders/{reminder_id}")
    def update_reminder(reminder_id: str, body: UpdateReminderBody):
        return commands.remind_update(config, reminder_id=reminder_id, message=body.message)

    @app.post("/reminders/{reminder_id}/snooze")
    def snooze_reminder(reminder_id: str, body: SnoozeReminderBody):
        return commands.remind_snooze(
            config,
            reminder_id=reminder_id,
            in_minutes=body.in_minutes,
            in_hours=body.in_hours,
            in_days=body.in_days,
            at=body.at,
            tz=body.tz,
        )

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
