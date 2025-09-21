# MCP Refactoring Plan

## Overview
Refactor WhatsApp and Microsoft MCPs to follow clean initialization patterns established in Scheduler MCP.

## Core Principles
- **No import-time side effects** - Importing modules should never create files, connections, or load configs
- **Lazy initialization** - Resources created only after parsing command-line args
- **Functional approach** - No classes, minimal global state
- **Pass dependencies** - Explicitly pass initialized resources to functions

## WhatsApp MCP Refactoring

### Current Issues
1. `whatsapp.py:10-16` - Hardcoded `MESSAGES_DB_PATH` at import time
2. `whatsapp.py:17` - Hardcoded `WHATSAPP_API_BASE_URL`
3. Path gets overwritten in `server.py:30` (works but not clean)

### Changes Required

#### 1. whatsapp.py
```python
# Remove at module level:
- MESSAGES_DB_PATH = os.path.join(...)
- WHATSAPP_API_BASE_URL = "http://localhost:8080/api"

# Add initialization function:
+ def init_whatsapp(db_path: Path, api_url: str = None):
+     global _db_path, _api_url
+     _db_path = db_path
+     _api_url = api_url or "http://localhost:8080/api"

# Update all functions to use _db_path instead of MESSAGES_DB_PATH
```

#### 2. server.py
```python
# Instead of:
- whatsapp.MESSAGES_DB_PATH = str(data_dir / "messages.db")

# Use:
+ whatsapp.init_whatsapp(data_dir / "messages.db")
```

## Microsoft MCP Refactoring

### Current Issues
1. `auth.py:7` - `load_dotenv()` runs at import
2. `auth.py:9` - Hardcoded `CACHE_FILE` path
3. `notifications.py:6` - Hardcoded `NOTIF_DIR` path
4. `monitor.py` - Likely has hardcoded paths too
5. All paths overwritten in `server.py:37-43` (works but not clean)

### Changes Required

#### 1. auth.py
```python
# Remove at module level:
- load_dotenv(find_dotenv())
- CACHE_FILE = pl.Path.home() / ".microsoft_mcp_token_cache.json"

# Add:
+ _cache_file = None
+
+ def init_auth(cache_file: Path):
+     global _cache_file
+     _cache_file = cache_file
+     load_dotenv(find_dotenv())  # Load env vars when initialized

# Update _read_cache() and _write_cache() to use _cache_file
```

#### 2. notifications.py
```python
# Remove at module level:
- NOTIF_DIR = Path("../../notifications").resolve()

# Add:
+ _notif_dir = None
+
+ def init_notifications(notif_dir: Path):
+     global _notif_dir
+     _notif_dir = notif_dir

# Update write_notification() to use _notif_dir
```

#### 3. monitor.py
```python
# Check for hardcoded paths and apply same pattern:
+ def init_monitor(base_dir: Path, state_file: Path, log_file: Path):
+     # Initialize monitor paths
```

#### 4. server.py
```python
# Instead of overwriting module variables:
- auth.CACHE_FILE = data_dir / "token_cache.json"
- monitor.BASE_DIR = data_dir
- notifications.NOTIF_DIR = notifications_dir

# Use initialization functions:
+ auth.init_auth(data_dir / "token_cache.json")
+ monitor.init_monitor(data_dir, data_dir / "last_check", data_dir / "monitor.log")
+ notifications.init_notifications(notifications_dir)
```

## Implementation Order

### Phase 1: WhatsApp MCP (Simpler)
1. Create `init_whatsapp()` function
2. Remove hardcoded paths
3. Update all database functions to use initialized path
4. Update server.py to call init function
5. Test to ensure nothing breaks

### Phase 2: Microsoft MCP (More Complex)
1. Fix auth.py - create `init_auth()`, remove import-time `load_dotenv()`
2. Fix notifications.py - create `init_notifications()`
3. Check and fix monitor.py
4. Update server.py to use init functions instead of overwriting
5. Ensure all imports work without side effects
6. Test authentication, notifications, and monitoring

## Testing Strategy

After each refactor:
1. Verify MCP starts without errors
2. Test basic functionality (list/send for WhatsApp, list emails for Microsoft)
3. Ensure paths are correctly set from command-line args
4. Verify no files/connections created at import time

## Success Criteria

✅ No hardcoded paths at module level
✅ No `load_dotenv()` or file operations at import time
✅ All initialization happens after parsing args in main()
✅ Clean functional design with minimal global state
✅ All MCPs follow same initialization pattern as Scheduler MCP

## Estimated Time
- WhatsApp MCP: 15-20 minutes
- Microsoft MCP: 30-40 minutes (more complex with multiple modules)

## Notes
- Keep changes minimal - only fix initialization issues
- Don't change functionality, just reorganize when things happen
- Maintain backwards compatibility with existing data/config