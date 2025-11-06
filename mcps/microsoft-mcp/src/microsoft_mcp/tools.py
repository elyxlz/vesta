"""Microsoft MCP tools - aggregates all domain-specific tools"""

from .auth_tools import (
    mcp,
    list_accounts,
    authenticate_account,
    complete_authentication,
)
from .calendar_tools import (
    list_events,
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
)
from .file_tools import (
    list_files,
    get_file,
    create_file,
    update_file,
    delete_file,
    search_files,
)

__all__ = [
    "mcp",
    # Auth
    "list_accounts",
    "authenticate_account",
    "complete_authentication",
    # Calendar
    "list_events",
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
    # Files
    "list_files",
    "get_file",
    "create_file",
    "update_file",
    "delete_file",
    "search_files",
]
