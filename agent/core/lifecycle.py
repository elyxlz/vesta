"""Lifecycle reason transport shared by startup logging and the authenticated boot message.

The single owner of the restart-reason vocabulary: the `category: detail` operational shape, the
crash categories that drive the non-zero exit, and the canonical copy for agent-initiated restarts.
"""

import dataclasses as dc

import pydantic as pyd


@dc.dataclass(frozen=True)
class RestartReason:
    """Separate operational copy from the context delivered to the agent."""

    log_reason: str
    agent_message: str


class InboxPayload(pyd.BaseModel):
    """The structured boot inbox vestad writes (`docker::write_pending_restart_reason`)."""

    log_reason: str
    agent_message: str = ""


def is_crash(reason: str | None) -> bool:
    """Whether a restart reason marks an unexpected exit (the `crash:`/`error:` categories the
    processor/loop error handlers write). It drives the non-zero exit that lets Docker's on-failure
    policy recover the agent, the inbox-override precedence on boot, and the render (crash reasons
    keep their marker)."""
    return reason is not None and reason.startswith(("crash:", "error:"))


def from_legacy(reason: str) -> RestartReason:
    """Derive agent copy from a bare `category: detail` reason: the category is an internal routing
    tag, so only the human detail is shown. Crash reasons stay whole, their marker is the story."""
    if reason == CLEAN_RESTART.log_reason:
        return CLEAN_RESTART
    if reason == CRASH_RESTART.log_reason:
        return CRASH_RESTART
    detail = reason.partition(": ")[2]
    return RestartReason(log_reason=reason, agent_message=reason if is_crash(reason) or not detail else detail)


def parse_inbox(payload: str) -> RestartReason:
    """Parse the boot inbox vestad wrote for this boot.

    LEGACY(remove-when: no agent can boot on an inbox written by a vestad older than the release
    that ships this file): a vestad that stopped its agents before being upgraded left a bare
    reason string behind, so a payload that is not the structured JSON is read as one."""
    try:
        parsed = InboxPayload.model_validate_json(payload)
    except pyd.ValidationError:
        return from_legacy(payload)
    if not parsed.log_reason.strip():
        return from_legacy(payload)
    if not parsed.agent_message.strip():
        return from_legacy(parsed.log_reason.strip())
    return RestartReason(log_reason=parsed.log_reason.strip(), agent_message=parsed.agent_message.strip())


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
