import logging

from core import logger


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.message = ""

    def emit(self, record: logging.LogRecord) -> None:
        self.message = record.getMessage()


def test_file_log_preserves_agent_rich_colors_as_ansi(monkeypatch):
    handler = _CaptureHandler()
    monkeypatch.setattr(logger, "_file_handler", handler)

    logger._agent_phase("THINKING", "hello")

    assert "\x1b[35m[AGENT]\x1b[0m" in handler.message
    assert "\x1b[34m[THINKING]\x1b[0m" in handler.message
    assert handler.message.endswith(" hello")


def test_file_log_preserves_notification_color_as_ansi(monkeypatch):
    handler = _CaptureHandler()
    monkeypatch.setattr(logger, "_file_handler", handler)

    logger.notification("hello")

    assert "\x1b[32m[NOTIFICATION]\x1b[0m" in handler.message
    assert handler.message.endswith(" hello")
