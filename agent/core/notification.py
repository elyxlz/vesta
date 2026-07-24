"""The notification data model and the core-notification vocabulary."""

import datetime as dt
import xml.sax.saxutils as xml_utils

import pydantic as pyd

# The source string for internal control-flow notifications. Core notifications are exempt from the
# user's interrupt rules; loops.py derives their disposition from the type.
CORE_SOURCE = "core"

# Notification `type` values for the `source=core` notifications that remain notifications (periodic
# control-flow). Boot-time control-flow (greeting, migrations, skill-sync, config issues) is delivered
# as boot turns instead — see core/main.py collect_boot_turns — so it carries no notification type.
TYPE_PROACTIVE_CHECK = "proactive_check"
TYPE_NIGHTLY_DREAM = "nightly_dream"
TYPE_COMPACTION_FOLLOWUP = "compaction_followup"

# Types listed here snooze (wait for idle); every other core type interrupts.
CORE_SNOOZE_TYPES = frozenset({TYPE_PROACTIVE_CHECK, TYPE_COMPACTION_FOLLOWUP})


# Fields promoted to the <channel> element's inner body (the message), in priority order.
# Everything else on a notification renders as an attribute. Skills that carry a human-readable
# message use one of these keys (whatsapp/app-chat write `message`); metadata-only notifications
# (email, reactions) have none and render as attributes with an empty body.
_CONTENT_FIELDS = ("message", "text", "content")


class Notification(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="allow")

    timestamp: dt.datetime
    source: str
    type: str
    # The producing skill's default disposition, used when no user rule matches (True -> interrupt,
    # False -> snooze). See notification_interrupt_policy.notif_disposition.
    interrupt: bool = True
    body: str | None = None
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        """Render the notification as a <channel> element: routing metadata as attributes, the
        message as the inner body. This mirrors the shape Claude Code injects for native channel
        events, so the model reads Vesta notifications in a structure it already handles well.

        A multi-line `body` (core/system notifications) becomes the inner text directly. Otherwise
        the first present content field (message/text/content) becomes the body and every other
        field renders as an attribute.

        Drops empty strings, False bools, empty lists, and None since they cost tokens without
        carrying information. Booleans should be named so True is the interesting case
        (`contact_unknown`, `is_forwarded`, `missed`). Strips microsecond precision from any
        datetime field.
        """
        if self.body is not None:
            return f'<channel source="{self.source}" type="{self.type}">\n{self.body.strip()}\n</channel>'
        data = self.model_dump(exclude={"file_path", "type", "source", "body", "interrupt"})
        content = ""
        for field in _CONTENT_FIELDS:
            if field in data and isinstance(data[field], str) and data[field].strip():
                content = xml_utils.escape(data.pop(field).strip())
                break
        attrs = [f'source="{self.source}"', f'type="{self.type}"']
        for key, value in data.items():
            if value is None or value == "" or value is False or value == []:
                continue
            rendered = value.replace(microsecond=0).isoformat() if isinstance(value, dt.datetime) else value
            if rendered is True:
                rendered = "true"
            attrs.append(f"{key}={xml_utils.quoteattr(str(rendered))}")
        return f"<channel {' '.join(attrs)}>{content}</channel>"
