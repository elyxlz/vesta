"""Email block/unblock commands for Microsoft CLI.

Uses the Graph API inbox message rules endpoint to create rules that move
emails from a sender to the junk folder.

Requires the MailboxSettings.ReadWrite scope. If the current token does not
include this scope, a clear error is raised instructing the user to re-auth.
"""

from typing import Any

import httpx

from . import graph, auth
from .config import Config
from .settings import MicrosoftSettings

BLOCK_RULE_PREFIX = "Block "
MAILBOX_SETTINGS_SCOPE_ERROR = (
    "Insufficient privileges for mailbox rule management. "
    "Run `microsoft auth add --account {account}` to re-authorize with the required permissions "
    "(MailboxSettings.ReadWrite)."
)


def _get_settings() -> MicrosoftSettings:
    return MicrosoftSettings()


def _rule_display_name(sender: str) -> str:
    return f"{BLOCK_RULE_PREFIX}{sender}"


def _is_block_rule(rule: dict[str, Any]) -> bool:
    """Return True if a message rule was created by this tool (has our prefix)."""
    name: str = rule.get("displayName", "")
    return name.startswith(BLOCK_RULE_PREFIX)


def _get_inbox_rules(
    config: Config,
    client: httpx.Client,
    account_id: str,
    settings: MicrosoftSettings,
    account_email: str = "<your-account>",
) -> list[dict[str, Any]]:
    """Fetch all inbox message rules for the account."""
    try:
        result = graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "GET",
            "/me/mailFolders/inbox/messageRules",
            account_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise PermissionError(MAILBOX_SETTINGS_SCOPE_ERROR.format(account=account_email)) from exc
        raise

    if result is None:
        return []
    return result.get("value", [])


def list_block_rules(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
) -> list[dict[str, Any]]:
    """List all block rules created by this tool."""
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    rules = _get_inbox_rules(config, client, account_id, settings, account_email=account_email)
    block_rules = [r for r in rules if _is_block_rule(r)]

    output = []
    for rule in block_rules:
        conditions = rule.get("conditions", {})
        sender_contains = conditions.get("senderContains", [])
        output.append(
            {
                "id": rule.get("id"),
                "displayName": rule.get("displayName"),
                "isEnabled": rule.get("isEnabled"),
                "sequence": rule.get("sequence"),
                "blockedSenders": sender_contains,
            }
        )
    return output


def block_sender(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    sender: str,
) -> dict[str, Any]:
    """Create an inbox rule that moves emails from sender to junk and stops processing."""
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    # Check if a block rule for this sender already exists
    rules = _get_inbox_rules(config, client, account_id, settings, account_email=account_email)
    for rule in rules:
        conditions = rule.get("conditions", {})
        if sender.lower() in [s.lower() for s in conditions.get("senderContains", [])]:
            return {
                "status": "already_blocked",
                "sender": sender,
                "rule_id": rule.get("id"),
                "displayName": rule.get("displayName"),
            }

    rule_body: dict[str, Any] = {
        "displayName": _rule_display_name(sender),
        "sequence": 1,
        "isEnabled": True,
        "conditions": {
            "senderContains": [sender],
        },
        "actions": {
            "moveToFolder": "junkemail",
            "stopProcessingRules": True,
        },
    }

    try:
        result = graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "POST",
            "/me/mailFolders/inbox/messageRules",
            account_id,
            json=rule_body,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise PermissionError(MAILBOX_SETTINGS_SCOPE_ERROR.format(account=account_email)) from exc
        raise

    if not result:
        raise ValueError(f"Failed to create block rule for sender '{sender}'")

    return {
        "status": "blocked",
        "sender": sender,
        "rule_id": result.get("id"),
        "displayName": result.get("displayName"),
        "isEnabled": result.get("isEnabled"),
    }


def unblock_sender(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    sender: str,
) -> dict[str, Any]:
    """Remove inbox rule(s) that block the given sender."""
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    rules = _get_inbox_rules(config, client, account_id, settings, account_email=account_email)

    matching_rules = [r for r in rules if sender.lower() in [s.lower() for s in r.get("conditions", {}).get("senderContains", [])]]

    if not matching_rules:
        return {"status": "not_found", "sender": sender, "message": f"No block rule found for sender '{sender}'"}

    deleted_ids = []
    for rule in matching_rules:
        rule_id = rule["id"]
        try:
            graph.request(
                client,
                config.cache_file,
                config.scopes,
                settings,
                config.base_url,
                "DELETE",
                f"/me/mailFolders/inbox/messageRules/{rule_id}",
                account_id,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise PermissionError(MAILBOX_SETTINGS_SCOPE_ERROR.format(account=account_email)) from exc
            raise
        deleted_ids.append(rule_id)

    return {
        "status": "unblocked",
        "sender": sender,
        "deleted_rule_ids": deleted_ids,
    }
