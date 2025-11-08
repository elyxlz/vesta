# MCP Development Guidelines

## Core Philosophy

### Error Handling
- **NO SILENT FAILURES**: Never use `.get()` with defaults that hide errors
- **VALIDATE INPUTS**: Check all required fields exist and have valid values
- **RAISE LOUDLY**: Throw clear, specific errors immediately when something is wrong
- **NO DEFAULTS**: Don't assume default values - require explicit inputs

### Code Style
- **MINIMAL COMMENTS**: Write self-documenting code, not comment novels
- **Comments only when necessary**: Complex algorithms or non-obvious business logic
- **No redundant comments**: Don't describe what the code clearly shows
- **FUNCTIONAL**: Use functional programming patterns, no OOP/classes
- **NO GLOBAL STATE**: Use lifespan pattern for resource management (see Development Patterns section)

### Initialization Principle
- **LAZY INITIALIZATION**: Never initialize resources at import time
- **LIFESPAN PATTERN**: All initialization happens in the lifespan async context manager
- **DEPENDENCY INJECTION**: Resources passed via context, not as function parameters
- **NO IMPORT SIDE EFFECTS**: Importing a module should never create connections, files, or start services

### Independence Principle
- **STANDALONE**: Each MCP must be completely independent and self-contained
- **NO SHARED CODE**: Do not create shared libraries between MCPs
- **DUPLICATE IF NEEDED**: Better to duplicate small utilities than create dependencies
- **ISOLATED NOTIFICATIONS**: Each MCP handles its own notification system independently

## Structure Standards

### Required Structure
Each MCP MUST follow this exact structure:
- Built with `fastmcp` for easy MCP server creation
- Python 3.12+ with type hints
- Uses `uv` for dependency management
- Modular design with separate auth, tools, and API modules

### Directory Layout (MANDATORY)

```
mcp-name/
├── src/
│   └── mcp_name/           # Use underscore in package name
│       ├── __init__.py
│       ├── server.py        # Just calls mcp.run() - 10 lines max
│       ├── context.py       # Context dataclass with all shared resources
│       ├── tools.py         # FastMCP instance with lifespan + tools (400 lines max)
│       ├── [domain]_tools.py # Split large tools into domain files
│       └── [api].py         # API/service integration modules
├── tests/
│   ├── __init__.py
│   └── test_integration.py
├── pyproject.toml           # Standardized metadata
├── README.md
├── .env.example             # Required env vars documentation
└── authenticate.py          # Helper script if needed
```

### File Size Limits
- **tools.py**: Maximum 400 lines. Split into domain-specific files if larger:
  - `email_tools.py`, `calendar_tools.py`, `file_tools.py` etc.
- **Each domain file**: Maximum 500 lines
- **server.py**: Maximum 10 lines (just imports mcp and calls mcp.run())
- **context.py**: Keep under 50 lines (just dataclass definition)

## Development Patterns

### Lifespan Pattern (Resource Management)

**REQUIRED**: All MCPs MUST use the lifespan pattern for resource management. Never use global variables.

#### Why Lifespan?
- **Zero Globals**: All resources managed via context, no module-level state
- **Proper Lifecycle**: Resources created on startup, cleaned up on shutdown
- **Type Safety**: Full type checking with dataclasses
- **Dependency Injection**: FastMCP auto-injects context into tools
- **Easier Testing**: Mock contexts without changing global state

#### Basic Structure

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

@dataclass
class MyContext:
    data_dir: Path
    # Add all shared resources here

@asynccontextmanager
async def my_lifespan(server: FastMCP) -> AsyncIterator[MyContext]:
    """Manage MCP lifecycle"""
    # 1. Parse CLI arguments
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    # 2. Initialize resources
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    ctx = MyContext(data_dir=data_dir)

    # 3. Yield context (MCP runs here)
    try:
        yield ctx
    finally:
        # 4. Cleanup resources
        pass

mcp = FastMCP("my-mcp", lifespan=my_lifespan)

@mcp.tool()
def my_tool(ctx: Context, param: str) -> dict:
    """FastMCP auto-injects ctx, excludes it from tool schema"""
    context: MyContext = ctx.request_context.lifespan_context
    # Use context.data_dir, etc.
    return {"result": "ok"}
```

#### Key Rules

1. **Context Dataclass**: Define all shared resources in a dataclass
2. **Async Context Manager**: Use `@asynccontextmanager` for lifespan
3. **CLI Args in Lifespan**: Parse args in lifespan, NOT in `main()`
4. **Context Injection**: Add `ctx: Context` as first param to ALL tool functions
5. **Extract Context**: `context: MyContext = ctx.request_context.lifespan_context`
6. **Simplified server.py**: Just call `mcp.run()`, no initialization code

#### Complete Example (Scheduler-MCP)

```python
# tools.py
@dataclass
class SchedulerContext:
    scheduler: BackgroundScheduler
    data_dir: Path
    notif_dir: Path

@asynccontextmanager
async def scheduler_lifespan(server: FastMCP) -> AsyncIterator[SchedulerContext]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--notifications-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    notif_dir = Path(args.notifications_dir).resolve()
    notif_dir.mkdir(parents=True, exist_ok=True)

    from . import scheduler as scheduler_module
    scheduler = scheduler_module.create_scheduler(data_dir)
    scheduler.start()

    ctx = SchedulerContext(scheduler, data_dir, notif_dir)
    init_db(ctx)
    check_missed_reminders(ctx)

    try:
        yield ctx
    finally:
        scheduler.shutdown(wait=True)

mcp = FastMCP("scheduler-mcp", lifespan=scheduler_lifespan)

@mcp.tool()
def set_reminder(ctx: Context, message: str, minutes: float | None = None) -> dict:
    context: SchedulerContext = ctx.request_context.lifespan_context
    # Use context.scheduler, context.data_dir, etc.
    return {"id": "...", "status": "scheduled"}

# server.py
from .tools import mcp

def main():
    mcp.run()  # That's it!
```

#### Advanced: HTTP Clients & Background Threads

```python
@dataclass
class MicrosoftContext:
    cache_file: Path
    http_client: httpx.Client
    notif_dir: Path
    monitor_stop_event: threading.Event
    monitor_logger: logging.Logger

@asynccontextmanager
async def microsoft_lifespan(server: FastMCP) -> AsyncIterator[MicrosoftContext]:
    # Parse args
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    # Setup resources
    http_client = httpx.Client(timeout=30.0, follow_redirects=True)
    monitor_stop_event = threading.Event()

    ctx = MicrosoftContext(
        cache_file=data_dir / "cache.bin",
        http_client=http_client,
        notif_dir=notif_dir,
        monitor_stop_event=monitor_stop_event,
        monitor_logger=logger,
    )

    # Start background thread
    monitor_thread = threading.Thread(target=monitor.run, args=(ctx,), daemon=True)
    monitor_thread.start()

    try:
        yield ctx
    finally:
        # Graceful shutdown
        monitor_stop_event.set()
        monitor_thread.join(timeout=5)
        http_client.close()
```

#### Testing with Mock Context

```python
@dataclass
class MockRequestContext:
    lifespan_context: SchedulerContext

@dataclass
class MockContext:
    request_context: MockRequestContext

@pytest.fixture
def mock_ctx(scheduler_context):
    return MockContext(request_context=MockRequestContext(lifespan_context=scheduler_context))

def test_tool(mock_ctx):
    result = my_tool(mock_ctx, param="value")
    assert result["status"] == "ok"
```

#### Passing Context to Non-Tool Functions

For helper functions that can't accept `Context` (e.g., APScheduler jobs, monitor threads):
- Pass individual resources as function parameters
- For APScheduler: Pass paths/IDs as args, not context objects (can't serialize)
- For threads: Pass entire context object

```python
# APScheduler jobs - pass individual params
def job_function(reminder_id: str, message: str, data_dir: Path, notif_dir: Path):
    # Can't receive Context because APScheduler serializes job args
    pass

# Background threads - pass context
def monitor_thread(ctx: MicrosoftContext):
    while not ctx.monitor_stop_event.is_set():
        # Use ctx.http_client, ctx.cache_file, etc.
        pass
```

### Tool Definition (using FastMCP from mcp.server)
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-name")

@mcp.tool()  # Note the parentheses
def tool_name(param: str) -> dict:
    """Tool description for LLM"""
    # Implementation
    return result
```

### Authentication
- Store credentials in environment variables
- Use `.env` file for local development
- Check for required env vars at startup
- Provide clear error messages if missing

### Testing
```python
# Integration tests using MCP client
async def get_session():
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "mcp-name"],
        env={"REQUIRED_VAR": os.getenv("REQUIRED_VAR")}
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session

@pytest.mark.asyncio
async def test_tool():
    async for session in get_session():
        result = await session.call_tool("tool_name", {"param": "value"})
        assert not result.isError
```

## Creating a New MCP

1. Copy structure from existing MCP (e.g., microsoft-mcp)
2. Update `pyproject.toml` with new name and dependencies
3. Implement tools in `src/mcp_name/tools.py`
4. Add integration tests
5. Document tool usage in README.md

## Project Metadata Standards

### pyproject.toml Requirements
```toml
[project]
name = "mcp-name"  # Use hyphens in project name
version = "0.1.0"  # Start at 0.1.0
description = "Clear, specific description of what this MCP does"
readme = "README.md"
authors = [
    { name = "elyx", email = "elio@pascarelli.com" }
]
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.6.0",       # Required for all MCPs (includes FastMCP)
    "httpx>=0.28.1",         # For HTTP APIs if needed
    "python-dotenv>=1.1.0",  # For environment management
    # Add service-specific deps here
]

[project.scripts]
mcp-name = "mcp_name.server:main"  # Entry point

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.4.0",
    "pytest-asyncio>=1.0.0",
]
```

## Testing

Run tests for individual MCPs:
```bash
cd mcps/mcp-name
uv run python -m pytest tests/ -v
```

Note: Always use `uv run python -m pytest` instead of `uv run pytest` to ensure pytest runs correctly in the virtual environment.

## Environment Setup

Each MCP should have a `.env.example` file showing required variables:
```env
MCP_NAME_API_KEY=your-api-key-here
MCP_NAME_ENDPOINT=https://api.example.com
```

## Notification Support

For MCPs that need to send notifications to Vesta:
1. Write to shared `notifications.json` file
2. Use file locking for concurrent access
3. Include timestamp, source, type, and data fields
4. Vesta will process and clear notifications on each run

## Error Handling

- Return clear error messages that help Vesta understand what went wrong
- Use exceptions for unrecoverable errors
- Return empty lists/dicts for "no results" (not errors)
- Include retry logic for transient API failures

## Typing Standards

### Modern Python Typing (3.11+)
- Use `|` instead of `Union` and `Optional`
- Use built-in types: `list`, `dict`, `tuple` instead of `List`, `Dict`, `Tuple`
- Examples:
  ```python
  # Good
  def process(data: str | None = None) -> list[dict[str, Any]]:
      ...

  # Bad
  from typing import Optional, List, Dict
  def process(data: Optional[str] = None) -> List[Dict[str, Any]]:
      ...
  ```

## Required Refactoring Status

### ✅ WhatsApp MCP (COMPLETED)
- ✅ Moved from `whatsapp-mcp-server/` to `src/whatsapp_mcp/`
- ✅ Split main.py into server.py and tools.py
- ✅ Updated pyproject.toml with proper metadata
- ✅ Added .env.example file

### ✅ Microsoft MCP (COMPLETED)
- ✅ Split 1155-line tools.py into domain modules:
  - email_tools.py - Email operations
  - calendar_tools.py - Calendar operations
  - file_tools.py - OneDrive operations
  - auth_tools.py - Authentication
  - search_tools.py - Search operations
- ✅ Added .env.example file

### ✅ Scheduler MCP (ALREADY COMPLIANT)
- Structure already follows standards
- ✅ Added .env.example file

## Enforcement Rules

1. **File Size Limits**: Enforce during code review
   - tools.py: max 400 lines
   - Domain modules: max 500 lines
   - server.py: max 100 lines

2. **Structure Validation**: Check before commits
   - Must have src/mcp_name/ structure
   - Must have __init__.py
   - Must have .env.example

3. **Typing Validation**: Use modern Python 3.11+ typing
   - No imports from typing for basic types
   - Use | for unions
   - Use built-in generic types

4. **Independence Validation**: No shared code between MCPs
   - Each MCP must be self-contained
   - Duplication is acceptable for independence