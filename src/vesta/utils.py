import datetime as dt
import json
import typing as tp

from claude_agent_sdk import AssistantMessage, Message, ResultMessage, TextBlock, ToolUseBlock

import vesta.models as vm


def format_tool_call(name: str, *, input_data: object, sub_agent_context: str | None) -> tuple[str, str | None]:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)
    input_preview = (input_str[:150] + "...") if len(input_str) > 150 else input_str

    if name == "Task":
        if isinstance(input_data, dict):
            data = tp.cast(dict[str, tp.Any], input_data)
            agent_type = data["subagent_type"] if "subagent_type" in data else "unknown"
            description = data["description"] if "description" in data else ""
        else:
            agent_type = "unknown"
            description = ""
        return f"[TASK] [{agent_type}]: {description or input_preview}", agent_type

    prefix = f"[{sub_agent_context}] " if sub_agent_context else ""

    return f"[TOOL] {prefix}{name}: {input_preview}", sub_agent_context


def parse_assistant_message(msg: Message, *, sub_agent_context: str | None) -> tuple[list[str], str | None, str | None]:
    if isinstance(msg, ResultMessage):
        session_id: str | None = None
        try:
            session_id = msg.session_id
        except AttributeError:
            pass
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
    buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, current_time: dt.datetime, buffer_delay: int
) -> bool:
    if not buffer or not buffer_start_time:
        return False
    return (current_time - buffer_start_time).total_seconds() >= buffer_delay


def decide_notification_action(
    notifications: list[vm.Notification], *, is_processing: bool, has_client: bool
) -> tp.Literal["interrupt", "queue", "skip"]:
    if not notifications:
        return "skip"

    if has_client and is_processing:
        return "interrupt"
    else:
        return "queue"
