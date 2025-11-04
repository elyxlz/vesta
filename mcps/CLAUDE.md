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
- **NO GLOBAL STATE**: Avoid global variables and mutable module-level state

### Initialization Principle
- **LAZY INITIALIZATION**: Never initialize resources at import time
- **EXPLICIT SETUP**: All initialization happens in main() after parsing args
- **PASS DEPENDENCIES**: Pass initialized resources to functions that need them
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
│       ├── server.py        # Entry point with argparse for --data-dir and --notifications-dir
│       ├── tools.py         # FastMCP tool definitions (keep under 400 lines)
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
- **server.py**: Maximum 100 lines (just initialization and argument parsing)

## Development Patterns

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