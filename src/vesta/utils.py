import json
import datetime as dt
import typing as tp

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, ResultMessage
import vesta.models as vm


def format_tool_call(name: str, *, input_data: tp.Any, sub_agent_context: str | None) -> tuple[str, str | None]:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)
    input_preview = (input_str[:150] + "...") if len(input_str) > 150 else input_str

    if name == "Task":
        agent_type = input_data.get("subagent_type", "unknown") if isinstance(input_data, dict) else "unknown"
        description = input_data.get("description", "") if isinstance(input_data, dict) else ""
        return f"[TASK] [{agent_type}]: {description or input_preview}", agent_type

    prefix = f"[{sub_agent_context}] " if sub_agent_context else ""

    if name.startswith("mcp__"):
        parts = name.replace("mcp__", "").split("__")
        service = parts[0] if parts else "unknown"
        action = ".".join(parts[1:]) if len(parts) > 1 else "action"
        return f"[TOOL] {prefix}[{service}] {action}: {input_preview}", sub_agent_context

    return f"[TOOL] {prefix}{name}: {input_preview}", sub_agent_context


def parse_assistant_message(msg: tp.Any, sub_agent_context: str | None) -> tuple[list[str], str | None, str | None]:
    if isinstance(msg, ResultMessage):
        session_id = msg.session_id if hasattr(msg, "session_id") else None
        return ([], sub_agent_context, session_id)

    if not isinstance(msg, AssistantMessage):
        return ([msg] if isinstance(msg, str) else [], sub_agent_context, None)

    texts = []
    has_task_result = False
    current_context = sub_agent_context

    for block in msg.content:
        if isinstance(block, TextBlock):
            text = block.text
            if current_context and "completed" in text.lower():
                has_task_result = True
            texts.append(text)
        elif isinstance(block, ToolUseBlock):
            formatted, new_context = format_tool_call(block.name, input_data=block.input, sub_agent_context=current_context)
            texts.append(formatted)
            if new_context:
                current_context = new_context

    if has_task_result and current_context:
        current_context = None

    return texts, current_context, None


def filter_new_notifications(all_notifications: list[vm.Notification], *, existing_paths: set[str]) -> list[vm.Notification]:
    return [n for n in all_notifications if n.file_path not in existing_paths]


def format_notification_batch(notifications: list[vm.Notification], *, suffix: str = "") -> str:
    suffix_str = f"\n\n{suffix}" if suffix else ""
    if len(notifications) == 1:
        return notifications[0].format_for_display() + suffix_str

    prompts = [n.format_for_display() for n in notifications]
    return "[NOTIFICATIONS]\n" + "\n".join(prompts) + suffix_str


def build_query_with_timestamp(prompt: str, *, timestamp: dt.datetime) -> str:
    timestamp_str = timestamp.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    return f"[Current time: {timestamp_str}]\n{prompt}"


def should_process_notification_buffer(
    buffer: list[vm.Notification], buffer_start_time: dt.datetime | None, current_time: dt.datetime, *, buffer_delay: int
) -> bool:
    if not buffer or not buffer_start_time:
        return False
    return (current_time - buffer_start_time).total_seconds() >= buffer_delay


def parse_notification_file_content(content: str) -> dict[str, tp.Any]:
    return json.loads(content)


def decide_notification_action(
    notifications: list[vm.Notification], *, is_processing: bool, has_client: bool
) -> tp.Literal["interrupt", "queue", "skip"]:
    if not notifications:
        return "skip"

    if has_client and is_processing:
        return "interrupt"
    else:
        return "queue"


def extract_paths_to_delete(notifications: list[vm.Notification]) -> set[str]:
    return {n.file_path for n in notifications if n.file_path}
