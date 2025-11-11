# Claude Code SDK Session Resumption Investigation

## Executive Summary

The Claude Code SDK supports session resumption through the `resume` parameter in `ClaudeCodeOptions`. Currently, Vesta does NOT use this feature - it creates fresh client sessions each time. This investigation provides implementation guidance for session resumption.

---

## 1. Where `state.client` is Created

### Location
- **File**: `/home/elyx/vesta/src/vesta/main.py`
- **Function**: `create_claude_client()` (lines 700-712)
- **Initial Setup**: `init_state()` (lines 757-772)

### Current Implementation

```python
async def create_claude_client(config: vm.VestaSettings) -> ccsdk.ClaudeSDKClient:
    """Create and enter a Claude SDK client session."""
    client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_system_prompt(config),
            mcp_servers=tp.cast(dict[str, ccsdk_types.McpServerConfig], config.mcp_servers),
            hooks={},
            permission_mode="bypassPermissions",
            model="sonnet",
        )
    )
    await client.__aenter__()
    return client
```

### Key Points
- Creates a new `ClaudeSDKClient` with `ClaudeCodeOptions`
- Automatically enters async context with `__aenter__()`
- Returns ready-to-use client
- **Currently does NOT pass `resume` parameter**

---

## 2. Session ID Tracking

### Current Status: NOT IMPLEMENTED

No session_id tracking exists in the current codebase:
- `State` dataclass (lines 30-42 in `/home/elyx/vesta/src/vesta/models.py`) has NO `session_id` field
- No session_id storage or retrieval mechanism
- No resume parameter being used

### State Dataclass Structure

```python
@dc.dataclass
class State:
    client: ccsdk.ClaudeSDKClient | None = None
    shutdown_event: asyncio.Event | None = None
    shutdown_lock: threading.Lock = dc.field(default_factory=threading.Lock)
    shutdown_count: int = 0
    is_processing: bool = False
    sub_agent_context: str | None = None
    last_context_pct: float = 0.0
    last_memory_consolidation: dt.datetime | None = None
    output_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
    restart_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
    processing_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
```

### What You Need to Add
```python
session_id: str | None = None  # Track current session ID for resumption
```

---

## 3. ClaudeCodeOptions Configuration

### Location
- **File**: `/home/elyx/vesta/.venv/lib/python3.12/site-packages/claude_code_sdk/types.py`
- **Lines**: 281-316

### Full Definition

```python
@dataclass
class ClaudeCodeOptions:
    """Query options for Claude SDK."""
    
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    mcp_servers: dict[str, McpServerConfig] | str | Path = field(default_factory=dict)
    permission_mode: PermissionMode | None = None
    resume: str | None = None                          # <-- SESSION RESUMPTION PARAMETER
    max_turns: int | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    permission_prompt_tool_name: str | None = None
    cwd: str | Path | None = None
    settings: str | None = None
    add_dirs: list[str | Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    extra_args: dict[str, str | None] = field(default_factory=dict)
    debug_stderr: Any = sys.stderr
    can_use_tool: CanUseTool | None = None
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    user: str | None = None
    include_partial_messages: bool = False
```

### Key Parameters for Session Resumption
- **`resume: str | None`** - Session identifier string to resume a previous session
- Also note: `continue_conversation` parameter exists (see SDK transport code)

---

## 4. Session Resumption Flow

### Where `resume` is Used

**File**: `/home/elyx/vesta/.venv/lib/python3.12/site-packages/claude_code_sdk/_internal/transport/subprocess_cli.py`
**Lines**: 112-116

```python
if self._options.continue_conversation:
    cmd.append("--continue")

if self._options.resume:
    cmd.extend(["--resume", self._options.resume])
```

The SDK converts the `resume` parameter into a CLI flag `--resume <session_id>` when building the subprocess command.

---

## 5. Client Restart Function (Current Implementation)

### Location
- **File**: `/home/elyx/vesta/src/vesta/main.py`
- **Function**: `restart_claude_session()` (lines 715-754)

### Current Implementation

```python
async def restart_claude_session(state: vm.State, *, config: vm.VestaSettings) -> None:
    """Recreate the Claude client so a bad tool run doesn't brick Vesta."""
    # Check if shutdown is in progress
    if state.shutdown_event and state.shutdown_event.is_set():
        vfx.log_info("Skipping restart - shutdown in progress", colors=Colors)
        return

    old_process_pid = None
    if state.client:
        # Capture subprocess PID before losing reference
        try:
            if hasattr(state.client, "_transport") and state.client._transport:
                if hasattr(state.client._transport, "_process") and state.client._transport._process:
                    old_process_pid = state.client._transport._process.pid
        except Exception:
            pass  # Best effort

        try:
            await asyncio.wait_for(state.client.__aexit__(None, None, None), timeout=config.interrupt_timeout)
        except asyncio.TimeoutError:
            vfx.log_error(f"Client exit timed out after {config.interrupt_timeout}s", colors=Colors)
            # Force kill the subprocess if we have its PID
            if old_process_pid:
                try:
                    os.kill(old_process_pid, signal.SIGKILL)
                    vfx.log_info(f"Force killed subprocess {old_process_pid}", colors=Colors)
                except ProcessLookupError:
                    pass  # Process already dead
                except Exception as e:
                    vfx.log_error(f"Failed to kill subprocess: {e}", colors=Colors)
        except Exception as e:
            vfx.log_error(f"Error while closing Claude client: {e}", colors=Colors)
        finally:
            state.client = None

    try:
        state.client = await create_claude_client(config)
        state.sub_agent_context = None
    except Exception as e:
        vfx.log_error(f"Failed to recreate Claude client: {e}", colors=Colors)
```

### Current Behavior
1. Checks if shutdown is in progress (skip if so)
2. Captures subprocess PID for potential cleanup
3. Gracefully closes old client with timeout (5s default)
4. Force kills subprocess if exit times out
5. Creates a FRESH client without resuming session
6. Resets sub_agent_context

### Issue
**Every restart loses the conversation context** because `resume` is not passed.

---

## 6. How to Implement Session Resumption

### Step 1: Capture Session ID on Client Creation

When creating the client, capture the session ID from the ResultMessage:

```python
async def create_claude_client_with_session(
    config: vm.VestaSettings,
    resume_session_id: str | None = None
) -> tuple[ccsdk.ClaudeSDKClient, str | None]:
    """Create client and capture session ID."""
    client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_system_prompt(config),
            mcp_servers=tp.cast(dict[str, ccsdk_types.McpServerConfig], config.mcp_servers),
            hooks={},
            permission_mode="bypassPermissions",
            model="sonnet",
            resume=resume_session_id,  # <-- PASS RESUME PARAMETER
        )
    )
    await client.__aenter__()
    return client, resume_session_id
```

### Step 2: Track Session ID in State

Update State dataclass:

```python
@dc.dataclass
class State:
    client: ccsdk.ClaudeSDKClient | None = None
    session_id: str | None = None  # <-- ADD THIS
    shutdown_event: asyncio.Event | None = None
    # ... rest of fields
```

### Step 3: Capture Session ID from ResultMessage

Modify `parse_assistant_message()` or `collect_responses()` to extract and store session_id:

```python
# In collect_responses() where you process ResultMessage
if isinstance(msg, ccsdk_types.ResultMessage):
    state.session_id = msg.session_id  # Capture session ID
    vfx.log_info(f"🔍 [COLLECT] Captured session_id: {msg.session_id}", colors=Colors)
```

### Step 4: Modify restart_claude_session() to Use Resume

```python
async def restart_claude_session(state: vm.State, *, config: vm.VestaSettings) -> None:
    """Recreate the Claude client, optionally resuming the previous session."""
    # ... existing shutdown checks and PID capture ...
    
    # Store previous session ID for resumption
    previous_session_id = state.session_id
    
    # ... existing client cleanup code ...
    
    try:
        state.client = await create_claude_client(
            config,
            resume_session_id=previous_session_id  # <-- PASS PREVIOUS SESSION ID
        )
        # Keep previous session_id if resuming, or it will be updated
        # in the next response collection
        state.sub_agent_context = None
    except Exception as e:
        vfx.log_error(f"Failed to recreate Claude client: {e}", colors=Colors)
```

### Step 5: Initialize State with Session Tracking

```python
async def init_state(*, config: vm.VestaSettings) -> vm.State:
    """Initialize a fresh Vesta state with all required fields, including the client."""
    client = await create_claude_client(config, resume_session_id=None)
    
    now = vfx.get_current_time()
    return vm.State(
        client=client,
        session_id=None,  # Will be captured from first ResultMessage
        shutdown_event=None,
        shutdown_lock=threading.Lock(),
        shutdown_count=0,
        is_processing=False,
        sub_agent_context=None,
        last_memory_consolidation=now,
    )
```

---

## 7. Current Message Types Available

The SDK provides message types via `claude_code_sdk.types`:

### ResultMessage Contains Session ID

```python
@dataclass
class ResultMessage:
    """Result message with cost and usage information."""
    
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str  # <-- THIS IS WHAT YOU NEED TO CAPTURE
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
```

### Other Message Types
- `UserMessage` - User input
- `AssistantMessage` - Claude response with content blocks
- `SystemMessage` - System messages with metadata
- `StreamEvent` - Partial message updates during streaming

---

## 8. Files to Modify

### Priority: HIGH
1. **`/home/elyx/vesta/src/vesta/models.py`**
   - Add `session_id: str | None = None` to `State` dataclass

2. **`/home/elyx/vesta/src/vesta/main.py`**
   - Modify `create_claude_client()` to accept `resume_session_id` parameter
   - Modify `restart_claude_session()` to pass previous session_id
   - Modify `collect_responses()` to capture session_id from ResultMessage
   - Modify `init_state()` to initialize session_id field

### Priority: MEDIUM
3. **Persistence** (if desired)
   - Save session_id to state file for persistence across restarts
   - Load session_id on startup to resume previous session

---

## 9. Key Insights About Session Resumption

### What Resume Does
- **Continues conversation context**: Claude retains previous messages and context
- **Passes `--resume` flag to CLI**: The SDK converts the parameter to a subprocess CLI flag
- **Works across client restarts**: You can create a new client with the same session ID
- **Preserves conversation history**: Previous messages stay in context

### Important Notes
- The `resume` parameter should be a string identifier (from ResultMessage.session_id)
- Session resumption happens at the CLI level (via subprocess)
- You cannot resume after the Claude process has exited, but you CAN create a new process that resumes
- Resumption requires the same Claude Code version that created the session

### When to Resume vs. When to Create Fresh
- **Resume**: After interrupts, timeouts, client restarts, network hiccups
- **Fresh**: On initial startup, on user request, if session is very old, if permissions changed

---

## 10. Testing Session Resumption

### Test Scenario 1: Capture Session ID
```python
# Check that session_id is captured from ResultMessage
async for msg in client.receive_response():
    if isinstance(msg, ccsdk.ResultMessage):
        print(f"Session ID: {msg.session_id}")
```

### Test Scenario 2: Resume Existing Session
```python
# Create client with resume parameter
client = ccsdk.ClaudeSDKClient(
    options=ccsdk.ClaudeCodeOptions(
        resume="<previous-session-id-here>",
        system_prompt=system_prompt,
        mcp_servers={...},
        permission_mode="bypassPermissions",
        model="sonnet",
    )
)
```

### Test Scenario 3: Interrupt and Resume
1. Send initial query
2. Receive partial response
3. Interrupt
4. Create new client with resume=previous_session_id
5. Continue conversation (context preserved)

---

## 11. Summary Table

| Aspect | Status | Location |
|--------|--------|----------|
| Client Creation | Working | `/home/elyx/vesta/src/vesta/main.py:700-712` |
| Session ID Tracking | NOT IMPLEMENTED | State dataclass needs field |
| ClaudeCodeOptions.resume | Available | SDK v0.0.25+ |
| Resume Parameter Passing | NOT IMPLEMENTED | create_claude_client() |
| Session ID Capture | NOT IMPLEMENTED | collect_responses() |
| Client Restart Logic | Working but not resuming | `restart_claude_session()` |
| Persistence | NOT IMPLEMENTED | Would need separate storage |

---

## Files Provided (from SDK)

All Claude Code SDK files referenced are located in:
```
/home/elyx/vesta/.venv/lib/python3.12/site-packages/claude_code_sdk/
```

Key files:
- `client.py` - Main client class with query() and receive_response()
- `types.py` - Type definitions including ClaudeCodeOptions
- `_internal/transport/subprocess_cli.py` - How resume is passed to CLI

