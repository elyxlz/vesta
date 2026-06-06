"""Vesta onboarding CLI — the agent-side of the Component 9 growth loop.

Drives the whole conduit onboarding in steps: verify the buyer's email by a code
they read back (yielding THE buyer's own session), reserve-and-checkout against the
vesta-cloud control plane, then once their VM is live create their first agent and
connect their Claude over vestad's PKCE OAuth. After the OTP every call is
authorized by the buyer's session — never a cross-tenant credential.
"""
