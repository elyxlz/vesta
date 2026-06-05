"""Vesta onboarding CLI — the agent-side of the Component 9 growth loop.

Calls the vesta-cloud control plane's public onboarding endpoints
(`/api/onboard/check`, `/api/onboard/checkout`) to validate a subdomain and mint
a Stripe Checkout link for a prospective new user, tagged with this vesta's
referral code when it has one.
"""
