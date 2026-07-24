"""Lifecycle reason transport shared by startup logging and the authenticated boot message."""

import dataclasses as dc
import json


@dc.dataclass(frozen=True)
class RestartReason:
    """Separate operational copy from the context delivered to the agent."""

    log_reason: str
    agent_message: str


def from_legacy(reason: str) -> RestartReason:
    """Upgrade the former `category: detail` string without changing its visible behavior."""
    if reason == CLEAN_RESTART.log_reason:
        return CLEAN_RESTART
    if reason == CRASH_RESTART.log_reason:
        return CRASH_RESTART
    detail = reason.partition(": ")[2]
    agent_message = reason if is_crash(reason) or not detail else detail
    return RestartReason(log_reason=reason, agent_message=agent_message)


def is_crash(reason: str) -> bool:
    return reason.startswith(("crash:", "error:"))


def parse_inbox(payload: str) -> RestartReason:
    """Parse the structured boot inbox, accepting the old plain string during rolling upgrades."""
    try:
        decoded = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return from_legacy(payload)

    if isinstance(decoded, str):
        return from_legacy(decoded)
    if isinstance(decoded, dict):
        log_reason = decoded.get("log_reason")
        agent_message = decoded.get("agent_message")
        if isinstance(log_reason, str) and log_reason.strip():
            if not isinstance(agent_message, str) or not agent_message.strip():
                return from_legacy(log_reason)
            return RestartReason(
                log_reason=log_reason.strip(),
                agent_message=agent_message.strip(),
            )
    return from_legacy(payload)


FIRST_START = RestartReason(log_reason="first start", agent_message="first start")
CLEAN_RESTART = RestartReason(
    log_reason="clean: routine restart, no specific reason",
    agent_message="You restarted after a routine shutdown.",
)
CRASH_RESTART = RestartReason(
    log_reason="crash: restarted after an unexpected exit",
    agent_message="crash: restarted after an unexpected exit",
)
AGENT_RESTART = RestartReason(
    log_reason="manual: restart requested by the agent",
    agent_message="You restarted your runtime.",
)
COMPACTION_RESTART = RestartReason(
    log_reason="compaction: context compacted",
    agent_message="Your conversation context was compacted, so the system restarted your runtime.",
)
