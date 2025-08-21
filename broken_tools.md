# Broken Tools & Known Issues

## Microsoft Graph Calendar API
**Status**: Partially broken
**Date discovered**: June 23, 2025
**Last tested**: August 7, 2025

### Issues:
1. **Calendar events not showing up**: Both personal (elio@pascarelli.com) and work (elio@audiogen.co) calendars return empty results when querying events
2. **Search events error**: Returns "can't compare offset-naive and offset-aware datetimes" error
3. **Update event error**: Returns 400 Bad Request when trying to update existing events

### Workarounds:
- Search email for calendar invites instead
- Create new events works, but can't update them
- Manual calendar management through Outlook web

### Error examples:
```
Error calling tool 'update_event': Client error '400 Bad Request' for url 'https://graph.microsoft.com/v1.0/me/events/[event_id]'
```

---

## OneDrive Search API  
**Status**: Broken for personal accounts
**Date discovered**: July 18, 2025
**Affected account**: eliopascarelli@outlook.com (OneDrive account)

### Issues:
- Search functionality (search_files, unified_search) doesn't work with personal Microsoft accounts
- Returns 400 Bad Request on any search query
- Works fine on work/school accounts (elio@pascarelli.com, elio@audiogen.co)

### Workarounds:
- Use list_files to browse directories manually instead of searching

---

## Microsoft MCP Email Forward Function
**Status**: Missing functionality
**Date discovered**: August 7, 2025

### Issues:
- No direct forward function available in Microsoft MCP tools
- Can only send new emails or reply, not forward existing emails

### Workarounds:
- Send new email with original content copied
- Use Outlook web interface to forward manually

### Todo:
- Added to todo list to implement forward functionality

---

## Notes:
- Always update this file when discovering new tool issues
- Include workarounds so we don't forget how to handle broken functionality
- Test periodically to see if issues are resolved