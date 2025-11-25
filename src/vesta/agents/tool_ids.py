"""Tool routing constants for Vesta sub-agents."""

# =============================================================================
# Playwright Tools (Browser Agent)
# =============================================================================
PLAYWRIGHT_TOOL_SUFFIXES = [
    "browser_click",
    "browser_close",
    "browser_console_messages",
    "browser_drag",
    "browser_evaluate",
    "browser_file_upload",
    "browser_fill_form",
    "browser_handle_dialog",
    "browser_hover",
    "browser_navigate",
    "browser_navigate_back",
    "browser_network_requests",
    "browser_press_key",
    "browser_resize",
    "browser_select_option",
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_type",
    "browser_wait_for",
    "browser_tabs",
    "browser_install",
    "browser_mouse_click_xy",
    "browser_mouse_drag_xy",
    "browser_mouse_move_xy",
    "browser_pdf_save",
    "browser_start_tracing",
    "browser_stop_tracing",
]
PLAYWRIGHT_TOOL_IDS = [f"mcp__playwright__{suffix}" for suffix in PLAYWRIGHT_TOOL_SUFFIXES]

# =============================================================================
# Microsoft Tools (Email/Calendar Agent)
# =============================================================================
MICROSOFT_AUTH_TOOL_SUFFIXES = [
    "list_accounts",
    "authenticate_account",
    "complete_authentication",
]

MICROSOFT_EMAIL_TOOL_SUFFIXES = [
    "list_emails",
    "get_email",
    "create_email_draft",
    "send_email",
    "reply_to_email",
    "get_attachment",
    "search_emails",
    "update_email",
]

MICROSOFT_CALENDAR_TOOL_SUFFIXES = [
    "list_events",
    "get_event",
    "create_event",
    "update_event",
    "delete_event",
    "respond_event",
]

MICROSOFT_AUTH_TOOL_IDS = [f"mcp__microsoft__{s}" for s in MICROSOFT_AUTH_TOOL_SUFFIXES]
MICROSOFT_EMAIL_TOOL_IDS = [f"mcp__microsoft__{s}" for s in MICROSOFT_EMAIL_TOOL_SUFFIXES]
MICROSOFT_CALENDAR_TOOL_IDS = [f"mcp__microsoft__{s}" for s in MICROSOFT_CALENDAR_TOOL_SUFFIXES]
MICROSOFT_ALL_TOOL_IDS = MICROSOFT_AUTH_TOOL_IDS + MICROSOFT_EMAIL_TOOL_IDS + MICROSOFT_CALENDAR_TOOL_IDS

# =============================================================================
# PDF Reader Tools (Report Writer Agent)
# =============================================================================
PDF_READER_TOOL_IDS = ["mcp__pdf-reader__read_pdf"]

# =============================================================================
# Main Agent Disallowed Tools
# =============================================================================
MAIN_AGENT_DISALLOWED_TOOLS = PLAYWRIGHT_TOOL_IDS + MICROSOFT_ALL_TOOL_IDS
