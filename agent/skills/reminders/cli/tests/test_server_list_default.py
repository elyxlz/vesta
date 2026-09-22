"""GET /reminders never silently truncates.

The CLI already gives JSON every row unless --limit caps it (a silent page size would make a
truncated list read as "no"); the HTTP surface serves the same kind of scripts, so its default
must be unbounded too, while ?limit=N still caps it for callers who ask."""

from reminders_cli import commands, server
from reminders_cli.config import Config


def _get_reminders_endpoint():
    app = server._create_app(Config())
    # POST /reminders shares the path; pick the route whose methods include GET.
    return next(
        route.endpoint for route in app.routes if getattr(route, "path", None) == "/reminders" and "GET" in getattr(route, "methods", set())
    )


def test_http_list_defaults_to_every_row(tmp_config: Config, monkeypatch):
    seen = {}

    def fake_remind_list(config, *, limit, show_deleted=False):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(commands, "remind_list", fake_remind_list)

    _get_reminders_endpoint()()

    assert seen["limit"] is None


def test_http_list_honors_an_explicit_limit(tmp_config: Config, monkeypatch):
    seen = {}

    def fake_remind_list(config, *, limit, show_deleted=False):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(commands, "remind_list", fake_remind_list)

    _get_reminders_endpoint()(limit=10)

    assert seen["limit"] == 10
