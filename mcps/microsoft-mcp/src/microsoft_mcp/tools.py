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
    check_availability,
    search_events,
)
from .email_tools import (
    list_emails,
    get_email,
    create_email_draft,
    send_email,
    reply_to_email,
    reply_all_email,
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
from .search_tools import unified_search

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
    "check_availability",
    "search_events",
    # Email
    "list_emails",
    "get_email",
    "create_email_draft",
    "send_email",
    "reply_to_email",
    "reply_all_email",
    "get_attachment",
    "search_emails",
    # Files
    "list_files",
    "get_file",
    "create_file",
    "update_file",
    "delete_file",
    "search_files",
    # Search
    "unified_search",
]
