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

## Structure

Each MCP in this directory follows a consistent structure:
- Built with `fastmcp` for easy MCP server creation
- Python 3.12+ with type hints
- Uses `uv` for dependency management
- Modular design with separate auth, tools, and API modules

## Directory Layout

```
mcp-name/
├── src/
│   └── mcp_name/
│       ├── __init__.py
│       ├── server.py      # Entry point
│       ├── tools.py       # FastMCP tool definitions
│       └── [api].py       # API/service integration
├── tests/
│   ├── __init__.py
│   └── test_integration.py
├── pyproject.toml
├── README.md
├── .env                   # Local config (gitignored)
└── authenticate.py        # Helper script if needed
```

## Development Patterns

### Tool Definition (using FastMCP)
```python
from fastmcp import FastMCP

mcp = FastMCP("mcp-name")

@mcp.tool
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

## Common Dependencies

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=2.8.0",
    "httpx>=0.28.1",  # For HTTP APIs
    "python-dotenv>=1.1.0",
]

[dependency-groups]
dev = [
    "mcp>=1.9.3",
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