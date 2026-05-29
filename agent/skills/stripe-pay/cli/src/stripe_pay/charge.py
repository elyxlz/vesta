"""Charge flow.

Steps:
  1. Validate inputs.
  2. Load OAuth token + restricted API key.
  3. Send an approval prompt to the user via their primary channel.
  4. Block waiting up to 5 minutes for ``yes`` / ``no``.
  5. On ``yes``: call Stripe Issuing-for-Agents to create a single-use card
     scoped to the requested amount + merchant + currency, and return its
     ephemeral PAN/CVC to stdout.
  6. Log the outcome to ``~/.stripe-pay/history.jsonl`` regardless.

The skill never persists card numbers — they live only in the returned dict.

If Stripe's Link-side cap is exceeded, Stripe will mark the spend request
``requires_link_app_approval``; we surface that in the user's prompt so they
know to also approve in the Link app.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import stripe  # type: ignore[import-untyped]

from . import channel as ch
from .auth import AuthError, load_active_token
from .config import Config


# Stripe zero-decimal currencies: the smallest unit equals the major unit, so the
# amount must NOT be multiplied by 100. https://stripe.com/docs/currencies#zero-decimal
ZERO_DECIMAL_CURRENCIES = frozenset(
    {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
)


def _to_minor_units(amount: float, currency: str) -> int:
    """Convert a major-unit amount to Stripe minor units, respecting zero-decimal currencies."""
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return int(round(amount))
    return int(round(amount * 100))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def charge(
    config: Config,
    *,
    amount: float,
    currency: str,
    merchant: str,
    reason: str,
    timeout_s: int = 300,
) -> dict:
    """Run the charge flow end-to-end. Returns a JSON-safe dict."""
    _validate_inputs(amount, currency, merchant, reason)

    api_key = config.load_api_key()
    if not api_key:
        raise AuthError(f"no Stripe API key on disk — write your restricted key to {config.api_key_file} (see SETUP.md step 2).")

    # This raises with a clear message if `authorize` hasn't run.
    access_token = load_active_token(config)

    primary = ch.detect_primary_channel()

    # 1. Pre-flight the spend request so we know whether Stripe's Link-side
    #    caps will require an in-app approval. Surface that in the prompt.
    requires_link_approval = _spend_request_requires_link_approval(
        api_key=api_key,
        access_token=access_token,
        amount=amount,
        currency=currency,
        merchant=merchant,
    )

    prompt = _build_prompt(
        amount=amount,
        currency=currency,
        merchant=merchant,
        reason=reason,
        requires_link_approval=requires_link_approval,
        timeout_s=timeout_s,
    )

    sent = ch.send_prompt(primary, prompt)

    reply = ch.wait_for_reply(
        primary,
        sent_at=sent["sent_at"],
        timeout_s=timeout_s,
    )

    if reply.decision == "timeout":
        result = {"status": "timeout", "reason": "no_reply_in_timeout"}
        _log(config, amount=amount, currency=currency, merchant=merchant, reason=reason, status="timeout", charge_id=None, channel=primary)
        return result

    if reply.decision == "reject":
        result = {"status": "rejected", "reason": "user_declined"}
        _log(
            config,
            amount=amount,
            currency=currency,
            merchant=merchant,
            reason=reason,
            status="rejected",
            charge_id=None,
            channel=primary,
            extra={"reply": reply.raw_text},
        )
        return result

    # Approved.
    try:
        card = _create_single_use_card(
            api_key=api_key,
            access_token=access_token,
            amount=amount,
            currency=currency,
            merchant=merchant,
            reason=reason,
        )
    except stripe.error.StripeError as e:  # type: ignore[attr-defined]
        result = {
            "status": "error",
            "reason": "stripe_api_error",
            "message": str(e),
        }
        _log(
            config,
            amount=amount,
            currency=currency,
            merchant=merchant,
            reason=reason,
            status="error",
            charge_id=None,
            channel=primary,
            extra={"error": str(e)},
        )
        # Tell the user the charge didn't go through.
        try:
            ch.send_prompt(
                primary,
                f"Heads up — the {currency} {amount:.2f} charge to {merchant} failed at Stripe's end: {e}",
            )
        except ch.ChannelError:
            pass
        return result

    result = {
        "status": "approved",
        "charge_id": card["charge_id"],
        "card": card["card"],
        "amount": amount,
        "currency": currency.upper(),
        "merchant": merchant,
        "requires_link_approval": requires_link_approval,
    }
    _log(
        config,
        amount=amount,
        currency=currency,
        merchant=merchant,
        reason=reason,
        status="approved",
        charge_id=card["charge_id"],
        channel=primary,
    )
    return result


# ---------------------------------------------------------------------------
# Stripe API calls
# ---------------------------------------------------------------------------


def _spend_request_requires_link_approval(
    *,
    api_key: str,
    access_token: str,
    amount: float,
    currency: str,
    merchant: str,
) -> bool:
    """Ask Stripe whether this charge would require an in-app Link approval.

    Returns False on any error (we don't want a soft preflight failure to
    block the real charge).
    """
    try:
        stripe.api_key = api_key
        # Per Stripe Agent Toolkit (April 2026), the SpendRequest preview
        # endpoint returns a ``next_action`` field when Link caps require an
        # in-app prompt.
        preview = stripe.SpendRequest.preview(  # type: ignore[attr-defined]
            access_token=access_token,
            amount=_to_minor_units(amount, currency),
            currency=currency.lower(),
            merchant=merchant,
        )
        next_action = getattr(preview, "next_action", None) or {}
        return bool(next_action.get("type") == "link_app_approval")
    except Exception:
        return False


def _create_single_use_card(
    *,
    api_key: str,
    access_token: str,
    amount: float,
    currency: str,
    merchant: str,
    reason: str,
) -> dict:
    """Create a single-use Issuing card scoped to this charge.

    Returns a dict with ``charge_id`` and ``card`` (number, exp, cvc, brand).
    """
    stripe.api_key = api_key

    # Issuing for Agents single-use card. The toolkit exposes this as
    # ``stripe.Issuing.AgentCard.create``; we keep the call surface narrow so
    # if the SDK renames it the patch is one line.
    card_obj = stripe.Issuing.AgentCard.create(  # type: ignore[attr-defined]
        access_token=access_token,
        amount=_to_minor_units(amount, currency),
        currency=currency.lower(),
        merchant=merchant,
        metadata={"reason": reason[:500], "skill": "vesta-stripe-pay"},
        single_use=True,
    )

    # Card numbers are returned only at creation time and never persisted by
    # this skill. Pull what we need into a plain dict.
    return {
        "charge_id": card_obj["id"],
        "card": {
            "number": card_obj["number"],
            "cvc": card_obj["cvc"],
            "exp_month": card_obj["exp_month"],
            "exp_year": card_obj["exp_year"],
            "brand": card_obj.get("brand", "visa"),
            "last4": card_obj["number"][-4:],
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_inputs(amount: float, currency: str, merchant: str, reason: str) -> None:
    if amount <= 0:
        raise ValueError("amount must be > 0")
    if not currency or len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a 3-letter ISO 4217 code (e.g. USD)")
    if not merchant or not merchant.strip():
        raise ValueError("merchant is required")
    if not reason or not reason.strip():
        raise ValueError("reason is required — the user needs context to approve")


def _build_prompt(
    *,
    amount: float,
    currency: str,
    merchant: str,
    reason: str,
    requires_link_approval: bool,
    timeout_s: int,
) -> str:
    """Compose the message sent to the user's primary channel."""
    minutes = max(1, timeout_s // 60)
    lines = [
        "Charge approval needed:",
        f"  - Amount: {currency.upper()} {amount:.2f}",
        f"  - Merchant: {merchant}",
        f"  - Reason: {reason}",
        "",
        f"Reply 'yes' to approve or 'no' to cancel within {minutes} minutes.",
    ]
    if requires_link_approval:
        lines.append("")
        lines.append("Note: this exceeds your Link spend cap, so Stripe will also ask you to approve inside the Link app.")
    return "\n".join(lines)


def _log(
    config: Config,
    *,
    amount: float,
    currency: str,
    merchant: str,
    reason: str,
    status: str,
    charge_id: str | None,
    channel: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one line to ``~/.stripe-pay/history.jsonl``."""
    config.ensure_dirs()
    entry = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "amount": amount,
        "currency": currency.upper(),
        "merchant": merchant,
        "reason": reason,
        "status": status,
        "charge_id": charge_id,
        "channel": channel,
    }
    if extra:
        entry.update(extra)
    with config.history_file.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        config.history_file.chmod(0o600)
    except OSError:
        pass


# Quiet pyflakes about ``time`` — kept available for any future preflight delay.
_ = time
