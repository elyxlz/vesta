"""Unit tests for the dual-path dispatcher (backend.run)."""

import httpx
import pytest
from microsoft_cli import backend


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_auto_uses_graph_when_it_succeeds():
    called = {"owa": False}
    out = backend.run(backend.AUTO, lambda: "graph-result", lambda: called.__setitem__("owa", True))
    assert out == "graph-result"
    assert called["owa"] is False


def test_auto_falls_back_on_403():
    def graph_fn():
        raise _http_error(403)

    out = backend.run(backend.AUTO, graph_fn, lambda: "owa-result")
    assert out == "owa-result"


def test_auto_falls_back_on_401():
    def graph_fn():
        raise _http_error(401)

    assert backend.run(backend.AUTO, graph_fn, lambda: "owa-result") == "owa-result"


def test_auto_falls_back_on_permission_error():
    def graph_fn():
        raise PermissionError("missing scope")

    assert backend.run(backend.AUTO, graph_fn, lambda: "owa-result") == "owa-result"


def test_auto_falls_back_on_graph_unavailable():
    def graph_fn():
        raise backend.GraphUnavailableError("no token")

    assert backend.run(backend.AUTO, graph_fn, lambda: "owa-result") == "owa-result"


def test_auto_does_not_mask_non_permission_errors():
    def graph_fn():
        raise _http_error(404)

    with pytest.raises(httpx.HTTPStatusError):
        backend.run(backend.AUTO, graph_fn, lambda: "owa-result")


def test_auto_does_not_mask_value_error():
    def graph_fn():
        raise ValueError("bad argument")

    with pytest.raises(ValueError):
        backend.run(backend.AUTO, graph_fn, lambda: "owa-result")


def test_force_graph_never_calls_owa():
    def owa_fn():
        raise AssertionError("owa must not run when graph is forced")

    assert backend.run(backend.GRAPH, lambda: "graph-result", owa_fn) == "graph-result"


def test_force_graph_propagates_its_error_without_fallback():
    def graph_fn():
        raise _http_error(403)

    with pytest.raises(httpx.HTTPStatusError):
        backend.run(backend.GRAPH, graph_fn, lambda: "owa-result")


def test_force_owa_rest_never_calls_graph():
    def graph_fn():
        raise AssertionError("graph must not run when owa-rest is forced")

    assert backend.run(backend.OWA_REST, graph_fn, lambda: "rest-result") == "rest-result"
