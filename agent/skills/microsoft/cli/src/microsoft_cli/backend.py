"""Dual-path dispatcher: Microsoft Graph first, browser-captured OWA REST as a
permission-failure fallback.

Every email/calendar/folder command runs through :func:`run`, which executes the
Graph implementation and, when Graph is unavailable *because of permissions*,
transparently retries the same logical operation against the OWA REST backend.
The user can pin a path with ``--backend {auto,graph,owa-rest}`` (default
``auto``); ``graph`` and ``owa-rest`` force a single path, which is what the test
suite uses to prove parity on both.

What counts as a permission failure (and therefore triggers fallback):
  * HTTP 401/402/403 from Graph (app blocked, missing delegated scope, consent revoked)
  * a ``PermissionError`` raised by a command (e.g. the block feature's scope check)
  * failure to acquire a Graph token at all (no Azure app reachable on this tenant)

Any other exception (a real bug, a bad argument, a 404) propagates unchanged so the
fallback never masks genuine errors.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

AUTO, GRAPH, OWA_REST = "auto", "graph", "owa-rest"
_PERMISSION_STATUSES = (401, 402, 403)


class GraphUnavailable(Exception):
    """Raised when a Graph token cannot be acquired, signalling the dispatcher to
    fall back to the OWA REST path."""


def _is_permission_failure(exc: Exception) -> bool:
    if isinstance(exc, (PermissionError, GraphUnavailable)):
        return True
    return bool(isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _PERMISSION_STATUSES)


def run(choice: str, graph_fn, rest_fn):
    """Execute a command via the chosen path.

    ``graph`` / ``owa-rest`` force a single backend. ``auto`` tries Graph and on a
    permission failure falls back to ``rest_fn``; anything else re-raises.
    """
    if choice == GRAPH:
        return graph_fn()
    if choice == OWA_REST:
        return rest_fn()

    # AUTO: try Graph, fall back to OWA REST on permission failures only.
    try:
        return graph_fn()
    except Exception as exc:
        if _is_permission_failure(exc):
            logger.warning("Graph path unavailable (%s: %s); falling back to OWA REST", type(exc).__name__, exc)
            return rest_fn()
        raise
