# Tool Bug Reports

## 1. Bash Tool - Null Bytes Error
**Date**: July 16-17, 2025
**Tool**: Bash
**Error**: `The argument 'args[2]' must be a string without null bytes. Received "source <(cat <<'__CLAUDE_SNAPSHOT_EOF__'\n" + '# Snapshot file\n' + '# Unset all aliases to avoid conflicts with functions\...`
**Context**: Trying to run any bash command, including simple ones like `ls` or `uv run`
**Workaround**: User must run commands manually in terminal
**Frequency**: Consistent - happens every time

## 2. Email Attachments List Parsing
**Date**: July 16, 2025
**Tool**: mcp__microsoft-mcp__send_email / create_email_draft
**Error**: `[Errno 2] No such file or directory: '/home/elyx/vesta/["/home/elyx/vesta/prescrizione_rx.pdf", "/home/elyx/vesta/prescrizione_trattamenti.pdf"]'`
**Context**: When passing a list of file paths as attachments parameter, the tool treats the entire list as a single string filename
**Workaround**: 
- Merge multiple PDFs into single file first
- Pass single file path as string (not list)
**Frequency**: Consistent when passing list of attachments

## 3. Calendar Event Update
**Date**: July 17, 2025
**Tool**: mcp__microsoft-mcp__update_event
**Error**: `Client error '400 Bad Request' for url 'https://graph.microsoft.com/v1.0/me/events/[event_id]'`
**Context**: Trying to update start/end times of existing calendar event
**Possible cause**: Event has Zoom meeting details or other restrictions
**Workaround**: Delete and recreate event instead of updating
**Frequency**: Unknown - needs more testing