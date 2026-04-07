import functools
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import commands
from .config import Config

logger = logging.getLogger(__name__)

TASK_ID_PATTERN = re.compile(r"^/tasks/([^/]+)$")
REMINDER_ID_PATTERN = re.compile(r"^/reminders/([^/]+)$")


def _pick(body: dict, key: str, default=None):
    return body[key] if key in body else default


def _bool_param(params: dict, key: str) -> bool:
    return key in params and params[key][0] == "true"


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    content_length = int(handler.headers["Content-Length"] or "0")
    if content_length == 0:
        return {}
    raw = handler.rfile.read(content_length)
    return json.loads(raw)


def _send_json(handler: BaseHTTPRequestHandler, status: int, data):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_error(handler: BaseHTTPRequestHandler, status: int, message: str):
    _send_json(handler, status, {"error": message})


def _handle_errors(method):
    @functools.wraps(method)
    def wrapper(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)
        try:
            method(self, path, params)
        except json.JSONDecodeError:
            _send_error(self, 400, "invalid JSON body")
        except ValueError as exc:
            _send_error(self, 400, str(exc))
        except Exception as exc:
            logger.error(f"{self.command} {path} failed: {exc}")
            _send_error(self, 500, str(exc))
    return wrapper


class TasksRequestHandler(BaseHTTPRequestHandler):
    config: Config

    def log_message(self, format, *args):
        logger.info(format, *args)

    @_handle_errors
    def do_GET(self, path, params):
        if path == "/tasks/search":
            q_values = params["q"] if "q" in params else None
            if not q_values:
                _send_error(self, 400, "query parameter 'q' is required")
                return
            result = commands.search_tasks(self.config, query=q_values[0], show_completed=_bool_param(params, "show_completed"))
            _send_json(self, 200, result)

        elif path == "/tasks":
            result = commands.list_tasks(self.config, show_completed=_bool_param(params, "show_completed"))
            _send_json(self, 200, result)

        elif task_match := TASK_ID_PATTERN.match(path):
            result = commands.get_task(self.config, task_id=task_match.group(1))
            _send_json(self, 200, result)

        elif path == "/reminders":
            task_id = params["task_id"][0] if "task_id" in params else None
            limit = int(params["limit"][0]) if "limit" in params else 50
            result = commands.remind_list(self.config, task_id=task_id, limit=limit)
            _send_json(self, 200, result)

        else:
            _send_error(self, 404, "not found")

    @_handle_errors
    def do_POST(self, path, params):
        body = _read_json_body(self)

        if path == "/tasks":
            if "title" not in body:
                _send_error(self, 400, "title is required")
                return
            result = commands.add_task(
                self.config,
                title=body["title"],
                due_datetime=_pick(body, "due_datetime"),
                timezone=_pick(body, "timezone"),
                due_in_minutes=_pick(body, "due_in_minutes"),
                due_in_hours=_pick(body, "due_in_hours"),
                due_in_days=_pick(body, "due_in_days"),
                priority=_pick(body, "priority", "normal"),
                initial_metadata=_pick(body, "initial_metadata"),
            )
            _send_json(self, 201, result)

        elif path == "/reminders":
            if "message" not in body:
                _send_error(self, 400, "message is required")
                return
            result = commands.remind_set(
                self.config,
                message=body["message"],
                task_id=_pick(body, "task_id"),
                scheduled_datetime=_pick(body, "scheduled_datetime"),
                tz=_pick(body, "tz"),
                in_minutes=_pick(body, "in_minutes"),
                in_hours=_pick(body, "in_hours"),
                in_days=_pick(body, "in_days"),
                recurring=_pick(body, "recurring"),
            )
            _send_json(self, 201, result)

        else:
            _send_error(self, 404, "not found")

    @_handle_errors
    def do_PATCH(self, path, params):
        body = _read_json_body(self)

        if task_match := TASK_ID_PATTERN.match(path):
            result = commands.update_task(
                self.config,
                task_id=task_match.group(1),
                status=_pick(body, "status"),
                title=_pick(body, "title"),
                priority=_pick(body, "priority"),
            )
            _send_json(self, 200, result)

        elif reminder_match := REMINDER_ID_PATTERN.match(path):
            if "message" not in body:
                _send_error(self, 400, "message is required")
                return
            result = commands.remind_update(self.config, reminder_id=reminder_match.group(1), message=body["message"])
            _send_json(self, 200, result)

        else:
            _send_error(self, 404, "not found")

    @_handle_errors
    def do_DELETE(self, path, params):
        if task_match := TASK_ID_PATTERN.match(path):
            result = commands.delete_task(self.config, task_id=task_match.group(1))
            _send_json(self, 200, result)

        elif reminder_match := REMINDER_ID_PATTERN.match(path):
            result = commands.remind_delete(self.config, reminder_id=reminder_match.group(1))
            _send_json(self, 200, result)

        else:
            _send_error(self, 404, "not found")


def start_server(config: Config, port: int) -> ThreadingHTTPServer:
    TasksRequestHandler.config = config
    server = ThreadingHTTPServer(("0.0.0.0", port), TasksRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"HTTP server listening on 0.0.0.0:{port}")
    return server
