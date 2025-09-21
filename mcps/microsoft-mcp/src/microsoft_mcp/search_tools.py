"""Search-related tools for Microsoft MCP"""

from typing import Any
from mcp.server.fastmcp import FastMCP
from . import graph

mcp = FastMCP("microsoft-mcp")


@mcp.tool()
def unified_search(
    query: str,
    account_id: str,
    entity_types: str | list[str] | None = None,
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Search across multiple Microsoft 365 resources using the modern search API

    Args:
        query: Search query string
        account_id: The account ID
        entity_types: Entity types to search (optional) - accepts:
            - Single type: "message"
            - Multiple types: "message,event,driveItem"
            - List of types: ["message", "event", "driveItem"]
            - Available types: message, event, drive, driveItem, list, listItem, site
            - Default if not specified: "message,event,driveItem"
        limit: Maximum number of results to return (default: 50)
    """

    if entity_types:
        if isinstance(entity_types, list):
            entity_types_list = entity_types
        else:
            # Parse comma-separated entity types
            entity_types_list = (
                [t.strip() for t in entity_types.split(",") if t.strip()]
                if "," in entity_types
                else [entity_types]
            )
    else:
        entity_types_list = ["message", "event", "driveItem"]

    results = {entity_type: [] for entity_type in entity_types_list}

    items = list(graph.search_query(query, entity_types_list, account_id, limit))

    for item in items:
        resource_type = item.get("@odata.type", "").split(".")[-1]

        if resource_type == "message":
            results.setdefault("message", []).append(item)
        elif resource_type == "event":
            results.setdefault("event", []).append(item)
        elif resource_type in ["driveItem", "file", "folder"]:
            results.setdefault("driveItem", []).append(item)
        else:
            results.setdefault("other", []).append(item)

    return {k: v for k, v in results.items() if v}
