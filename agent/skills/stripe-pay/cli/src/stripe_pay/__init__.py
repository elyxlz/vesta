"""stripe-pay — Vesta skill for Stripe Link Wallet for Agents.

Two CLIs:
- ``stripe-pay authorize`` — one-time OAuth flow against Link.
- ``stripe-pay charge``    — sends an approval prompt to the user via their
  primary channel and, on approval, mints a single-use Issuing card.

The agent NEVER charges silently. Every charge requires per-call user approval.
"""

__version__ = "0.1.0"
