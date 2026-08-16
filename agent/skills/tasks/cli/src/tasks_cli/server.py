import logging
import threading
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import commands
from .config import Config
from .scheduler import write_notification

logger = logging.getLogger(__name__)


# --- Request bodies ---


class AddTaskBody(BaseModel):
    subject: str
    due_datetime: str | None = None
    timezone: str | None = None
    due_in_minutes: int | None = None
    due_in_hours: int | None = None
    due_in_days: int | None = None
    priority: str | int = "normal"
    initial_metadata: str | None = None


class UpdateTaskBody(BaseModel):
    status: Literal["pending", "in_progress", "completed"] | None = None
    subject: str | None = None
    priority: str | int | None = None
    due_datetime: str | None = None
    timezone: str | None = None
    due_in_minutes: int | None = None
    due_in_hours: int | None = None
    due_in_days: int | None = None
    clear_due: bool = False


# --- Task update (app path) ---


def _apply_task_update(config: Config, notif_dir: Path, task_id: str, body: UpdateTaskBody) -> dict:
    """Apply a task update coming from the app. A pending->completed transition here is the one completion
    the agent does not already know about (its own CLI edits are self-evident), so it notifies,
    snoozed (interrupt=False), which the CLI path never does."""
    already_completed = body.status == "completed" and commands.get_task(config, task_id=task_id)["status"] == "completed"
    result = commands.update_task(
        config,
        task_id=task_id,
        status=body.status,
        subject=body.subject,
        priority=body.priority,
        due=commands.DueSpec(
            due_datetime=body.due_datetime,
            timezone=body.timezone,
            due_in_minutes=body.due_in_minutes,
            due_in_hours=body.due_in_hours,
            due_in_days=body.due_in_days,
            clear=body.clear_due,
        ),
    )
    if body.status == "completed" and not already_completed:
        write_notification(notif_dir, "task_completed", interrupt=False, task_id=task_id, message=f"Task completed: {result['subject']}")
    return result


# --- App factory ---


def _create_app(config: Config, notif_dir: Path) -> FastAPI:
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
            subject=body.subject,
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
        return _apply_task_update(config, notif_dir, task_id, body)

    @app.delete("/tasks/{task_id}")
    def delete_task(task_id: str):
        return commands.delete_task(config, task_id=task_id)

    return app


def start_server(config: Config, port: int, notif_dir: Path) -> uvicorn.Server:
    app = _create_app(config, notif_dir)
    uv_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(uv_config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server
