import json
import dataclasses as dc
import datetime as dt
import pathlib as pl
import typing as tp

import claude_code_sdk.types as ccsdk_types
import vesta.models as vm


def format_timestamp_message(text: str, sender: str, timestamp: dt.datetime, colors: dict[str, str]) -> list[str]:
    timestamp_str = timestamp.strftime("%I:%M %p")
    color_map = {"You": "cyan", "Vesta": "magenta", "System": "yellow"}
    base_sender = sender.split("[")[0] if "[" in sender else sender

    if base_sender in color_map:
        display_sender = sender.lower()
        prefix = f"{colors['dim']}[{timestamp_str}]{colors['reset']} {colors[color_map[base_sender]]}{display_sender}:{colors['reset']}"
        return [f"{prefix} {line}" for line in text.split("\n") if line.strip()]
    elif sender:
        prefix = f"{colors['dim']}[{timestamp_str}]{colors['reset']} {colors['green']}{sender}:{colors['reset']}"
        return [f"{prefix} {line}" for line in text.split("\n") if line.strip()]
    else:
        return [f"{colors['dim']}[{timestamp_str}]{colors['reset']} {colors['yellow']}{text}{colors['reset']}"]


def format_tool_call(name: str, input_data: tp.Any, sub_agent_context: str | None, service_icons: dict[str, str]) -> tuple[str, str | None]:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)
    input_preview = (input_str[:150] + "...") if len(input_str) > 150 else input_str

    if name == "Task":
        agent_type = input_data.get("subagent_type", "unknown") if isinstance(input_data, dict) else "unknown"
        description = input_data.get("description", "") if isinstance(input_data, dict) else ""
        return f"🤖 Task [{agent_type}]: {description or input_preview}", agent_type

    prefix = f"[{sub_agent_context}] " if sub_agent_context else ""

    if name.startswith("mcp__"):
        parts = name.replace("mcp__", "").split("__")
        service = parts[0] if parts else "unknown"
        action = ".".join(parts[1:]) if len(parts) > 1 else "action"
        icon = service_icons.get(service, "🔧")
        return f"🔧 {prefix}{icon} [{service}] {action}: {input_preview}", sub_agent_context

    return f"🔧 {prefix}{name}: {input_preview}", sub_agent_context


def extract_usage_from_result(msg: ccsdk_types.ResultMessage) -> dict[str, tp.Any] | None:
    """Extract token usage information from a ResultMessage."""
    if not msg.usage:
        return None

    return {
        "input_tokens": msg.usage.get("input_tokens", 0),
        "cache_read_input_tokens": msg.usage.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": msg.usage.get("cache_creation_input_tokens", 0),
        "output_tokens": msg.usage.get("output_tokens", 0),
        "total_cost_usd": msg.total_cost_usd or 0.0,
    }


def parse_assistant_message(
    msg: tp.Any, sub_agent_context: str | None, service_icons: dict[str, str]
) -> tuple[list[str], str | None, dict[str, tp.Any] | None]:
    # Handle ResultMessage
    if isinstance(msg, ccsdk_types.ResultMessage):
        return ([], sub_agent_context, extract_usage_from_result(msg))

    if not isinstance(msg, ccsdk_types.AssistantMessage):
        return ([msg] if isinstance(msg, str) else [], sub_agent_context, None)

    texts = []
    has_task_result = False
    current_context = sub_agent_context

    for block in msg.content:
        if isinstance(block, ccsdk_types.TextBlock):
            text = block.text
            if current_context and "completed" in text.lower():
                has_task_result = True
            texts.append(text)
        elif isinstance(block, ccsdk_types.ToolUseBlock):
            formatted, new_context = format_tool_call(block.name, block.input, current_context, service_icons)
            texts.append(formatted)
            if new_context:
                current_context = new_context

    if has_task_result and current_context:
        current_context = None

    return texts, current_context, None


def update_state(state: vm.State, **updates) -> vm.State:
    return dc.replace(state, **updates)


def add_to_conversation_history(history: list[dict[str, tp.Any]], role: str, content: str) -> list[dict[str, tp.Any]]:
    return history + [{"role": role, "content": content}]


def calculate_token_count(history: list[dict[str, tp.Any]]) -> int:
    return sum(len(str(msg)) // 4 for msg in history)


def should_preserve_memory(history: list[dict[str, tp.Any]], max_tokens: int, ephemeral: bool) -> bool:
    # TEMPORARILY DISABLED FOR DEBUGGING
    return False
    # if ephemeral or not history:
    #     return False
    # return calculate_token_count(history) >= max_tokens


def filter_new_notifications(all_notifications: list[vm.Notification], existing_paths: set[str]) -> list[vm.Notification]:
    return [n for n in all_notifications if n.file_path not in existing_paths]


def format_notification_batch(notifications: list[vm.Notification]) -> str:
    if len(notifications) == 1:
        return notifications[0].format_for_display()

    prompts = [n.format_for_display() for n in notifications]
    return "[NOTIFICATIONS]\n" + "\n".join(prompts)


def build_query_with_timestamp(prompt: str, timestamp: dt.datetime) -> str:
    timestamp_str = timestamp.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    return f"[Current time: {timestamp_str}]\n{prompt}"


@dc.dataclass(frozen=True)
class MonitoringAction:
    action_type: tp.Literal["check_bridge", "check_mcp", "check_proactive", "process_notifications"]
    data: tp.Any = None


def calculate_monitoring_actions(
    current_time: dt.datetime,
    last_proactive: dt.datetime,
    config: vm.VestaSettings,
) -> list[MonitoringAction]:
    actions = []

    if current_time - last_proactive >= dt.timedelta(minutes=config.proactive_check_interval):
        actions.append(MonitoringAction("check_proactive"))

    return actions


def should_process_notification_buffer(
    buffer: list[vm.Notification], buffer_start_time: dt.datetime | None, current_time: dt.datetime, buffer_delay: int
) -> bool:
    if not buffer or not buffer_start_time:
        return False
    return (current_time - buffer_start_time).total_seconds() >= buffer_delay


def classify_output_line(text: str, sub_agent_context: str | None, is_tool: bool) -> tp.Literal["agent_task", "agent_tool", "tool", "message"]:
    if not text or not text.strip():
        return "message"

    if text.startswith("🤖"):
        return "agent_task"
    elif sub_agent_context and (is_tool or text.startswith("🔧")):
        return "agent_tool"
    elif is_tool or text.startswith("🔧"):
        return "tool"
    else:
        return "message"


def format_output_line(
    text: str, line_type: tp.Literal["agent_task", "agent_tool", "tool", "message"], sub_agent_context: str | None, colors: dict[str, str]
) -> str:
    if line_type == "agent_task":
        return f"{colors['cyan']}>>{text}{colors['reset']}"
    elif line_type == "agent_tool":
        return f"{colors['cyan']}  >{text}{colors['reset']}"
    elif line_type == "tool":
        return f"{colors['yellow']}>{text}{colors['reset']}"
    else:
        sender = f"Vesta[{sub_agent_context}]" if sub_agent_context else "Vesta"
        return f"[{sender}] {text}"


def build_mcp_env_vars() -> dict[str, str]:
    return {"PYTHONUNBUFFERED": "1"}


def transform_mcp_config(servers: dict[str, vm.McpServer]) -> dict[str, dict[str, tp.Any]]:
    env_vars = build_mcp_env_vars()
    return {
        name: {
            "command": server["command"],
            "args": server["args"],
            "env": env_vars,
        }
        for name, server in servers.items()
    }


def get_notification_files(directory: pl.Path) -> list[pl.Path]:
    if not directory.exists():
        return []
    return list(directory.glob("*.json"))


def parse_notification_file_content(content: str) -> dict[str, tp.Any]:
    return json.loads(content)


def decide_notification_action(
    notifications: list[vm.Notification], is_processing: bool, has_client: bool
) -> tp.Literal["interrupt", "queue", "skip"]:
    if not notifications:
        return "skip"

    if has_client and is_processing:
        return "interrupt"
    else:
        return "queue"


def extract_paths_to_delete(notifications: list[vm.Notification]) -> set[str]:
    return {n.file_path for n in notifications if n.file_path}
