"""Microsoft MCP tools - aggregates all domain-specific tools"""

from .auth_tools import (
    mcp,
    list_accounts,
    authenticate_account,
    complete_authentication,
)
from .calendar_tools import (
    list_events,
    get_event,
    create_event,
    update_event,
    delete_event,
    respond_event,
)
from .email_tools import (
    list_emails,
    get_email,
    create_email_draft,
    send_email,
    reply_to_email,
    get_attachment,
    search_emails,
    update_email,
)

__all__ = [
    "mcp",
    # Auth
    "list_accounts",
    "authenticate_account",
    "complete_authentication",
    # Calendar
    "list_events",
    "get_event",
    "create_event",
    "update_event",
    "delete_event",
    "respond_event",
    # Email
    "list_emails",
    "get_email",
    "create_email_draft",
    "send_email",
    "reply_to_email",
    "get_attachment",
    "search_emails",
    "update_email",
]
