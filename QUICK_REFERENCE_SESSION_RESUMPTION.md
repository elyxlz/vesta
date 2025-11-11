# Quick Reference: Session Resumption Implementation

## TL;DR

The SDK's `resume` parameter lets you continue conversations after client restarts. Currently Vesta creates fresh sessions each time. You need to:

1. Add `session_id` field to State dataclass
2. Capture session_id from ResultMessage.session_id
3. Pass resume parameter when creating new client

## 5-Minute Overview

### Current Client Creation (lines 700-712, main.py)
```python
client = ccsdk.ClaudeSDKClient(
    options=ccsdk.ClaudeCodeOptions(
        system_prompt=...,
        mcp_servers=...,
        model="sonnet",
        # resume=None  # <-- Currently missing!
    )
)
```

### What's Needed
1. **models.py, State class**: Add `session_id: str | None = None`
2. **main.py, collect_responses()**: Capture session from ResultMessage
3. **main.py, create_claude_client()**: Accept and pass resume parameter
4. **main.py, restart_claude_session()**: Pass previous session_id

## Code Changes

### 1. Update State (models.py, ~line 32)
```python
@dc.dataclass
class State:
    client: ccsdk.ClaudeSDKClient | None = None
    session_id: str | None = None  # <-- ADD THIS LINE
    shutdown_event: asyncio.Event | None = None
    # ... rest unchanged
```

### 2. Update create_claude_client() (main.py, ~line 700)
```python
async def create_claude_client(
    config: vm.VestaSettings,
    resume_session_id: str | None = None,  # ADD PARAMETER
) -> ccsdk.ClaudeSDKClient:
    """Create and enter a Claude SDK client session."""
    client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_system_prompt(config),
            mcp_servers=tp.cast(dict[str, ccsdk_types.McpServerConfig], config.mcp_servers),
            hooks={},
            permission_mode="bypassPermissions",
            model="sonnet",
            resume=resume_session_id,  # ADD THIS LINE
        )
    )
    await client.__aenter__()
    return client
```

### 3. Capture Session ID (main.py, collect_responses(), ~line 244)
```python
async def collect_responses(...) -> tuple[list[str], vm.State]:
    # ... existing code ...
    async for msg in client.receive_response():
        # Capture session ID from ResultMessage
        if isinstance(msg, ccsdk_types.ResultMessage):
            state.session_id = msg.session_id  # ADD THIS LINE
        
        text, _, usage_data = parse_assistant_message(msg, state=state)
        # ... rest of loop
```

### 4. Update restart_claude_session() (main.py, ~line 715)
```python
async def restart_claude_session(state: vm.State, *, config: vm.VestaSettings) -> None:
    """Recreate the Claude client, optionally resuming the previous session."""
    
    # ... existing shutdown/PID capture code ...
    
    previous_session_id = state.session_id  # ADD THIS LINE
    
    # ... existing client cleanup code ...
    
    try:
        state.client = await create_claude_client(
            config,
            resume_session_id=previous_session_id,  # ADD THIS LINE
        )
        state.sub_agent_context = None
    except Exception as e:
        vfx.log_error(f"Failed to recreate Claude client: {e}", colors=Colors)
```

### 5. Update init_state() (main.py, ~line 757)
```python
async def init_state(*, config: vm.VestaSettings) -> vm.State:
    """Initialize a fresh Vesta state with all required fields, including the client."""
    client = await create_claude_client(config, resume_session_id=None)  # ADD PARAMETER
    
    now = vfx.get_current_time()
    return vm.State(
        client=client,
        session_id=None,  # ADD THIS LINE
        shutdown_event=None,
        # ... rest unchanged
    )
```

## Imports Needed

All imports already exist:
- `ccsdk_types` already imported at top of main.py
- `ResultMessage` available via `ccsdk_types.ResultMessage`

## Testing

Quick validation:
```python
# In collect_responses loop, add logging
if isinstance(msg, ccsdk_types.ResultMessage):
    state.session_id = msg.session_id
    print(f"Session ID captured: {msg.session_id}")
```

Then interrupt/restart and verify:
1. Session ID is captured
2. Session ID is passed to new client
3. Conversation context is preserved

## Key Files

- **models.py**: State dataclass definition
- **main.py**: Client creation and restart logic
- **SDK location**: `.venv/lib/python3.12/site-packages/claude_code_sdk/`

## SDK Version

Requires: `claude-code-sdk>=0.0.25` (already in pyproject.toml)
