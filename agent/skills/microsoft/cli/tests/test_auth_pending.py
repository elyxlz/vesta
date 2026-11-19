"""Device-code polling: a sign-in the user has not finished yet is pending, not a failure.

Entra returns the OAuth code `authorization_pending` in `error` and only an AADSTS70016 sentence
in `error_description`, so the pending check must read both fields.
"""

from __future__ import annotations

import pytest
from microsoft_cli import auth_commands

AADSTS70016 = "AADSTS70016: The provided request has not yet been authorized by the user. Trace ID: x"
AADSTS70020 = "AADSTS70020: The provided value for the input parameter 'device_code' is not valid. This device code has expired."


@pytest.mark.parametrize(
    "result",
    [
        {"error": "authorization_pending", "error_description": AADSTS70016},
        {"error": "slow_down", "error_description": "slow down"},
        {"error": "invalid_grant", "error_description": AADSTS70016},
        {"error": "authorization_pending"},
    ],
)
def test_pending_sign_in_is_pending(result: dict) -> None:
    error_msg = result["error_description"] if "error_description" in result else result["error"]
    assert auth_commands._is_pending(result, error_msg)


@pytest.mark.parametrize(
    "result",
    [
        {"error": "expired_token", "error_description": AADSTS70020},
        {"error": "access_denied", "error_description": "AADSTS70000: The user denied the request."},
    ],
)
def test_expired_or_denied_sign_in_is_not_pending(result: dict) -> None:
    assert not auth_commands._is_pending(result, result["error_description"])
