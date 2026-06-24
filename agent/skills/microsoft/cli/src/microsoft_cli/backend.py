"""Dual-path dispatcher: Microsoft Graph first, reverse-engineered OWA/EWS as a
permission-failure fallback.

Every email/calendar command runs through :func:`run`, which executes the Graph
implementation and, when Graph is unavailable *because of permissions*, transparently
retries the same logical operation against the OWA/EWS backend. The user can pin a
path with ``--backend {auto,graph,owa}`` (default ``auto``); ``graph`` and ``owa``
force a single path, which is what the test suite uses to prove parity on both.

What counts as a permission failure (and therefore triggers fallback):
  * HTTP 401/403 from Graph (app blocked, missing delegated scope, consent revoked)
  * a ``PermissionError`` raised by a command (e.g. the block feature's scope check)
  * failure to acquire a Graph token at all (no Azure app reachable on this tenant)

Any other exception (a real bug, a bad argument, a 404) propagates unchanged so the
fallback never masks genuine errors.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

AUTO, GRAPH, OWA = "auto", "graph", "owa"
_PERMISSION_STATUSES = (401, 403)


class GraphUnavailable(Exception):
    """Raised when a Graph token cannot be acquired, signalling the dispatcher to
    fall back to the OWA/EWS path."""


def _is_permission_failure(exc: Exception) -> bool:
    if isinstance(exc, (PermissionError, GraphUnavailable)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _PERMISSION_STATUSES:
        return True
    return False


def run(choice: str, graph_fn, owa_fn):
    """Execute a command via the chosen path.

    ``graph``/``owa`` force a single backend. ``auto`` tries Graph and falls back to
    OWA on a permission failure, re-raising anything else.
    """
    if choice == GRAPH:
        return graph_fn()
    if choice == OWA:
        return owa_fn()

    try:
        return graph_fn()
    except Exception as exc:  # noqa: BLE001 - we re-raise non-permission errors below
        if _is_permission_failure(exc):
            logger.warning("Graph path unavailable (%s: %s); falling back to OWA/EWS", type(exc).__name__, exc)
            return owa_fn()
        raise
