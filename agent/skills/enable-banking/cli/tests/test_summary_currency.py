"""`aggregate_by_category` must never add two currencies together.

An account that sees more than one currency is the ordinary case for anyone who travels, and the
old implementation summed `transaction_amount.amount` as a bare float while ignoring
`transaction_amount.currency` entirely. The result was a single confident number that was not a
quantity of anything, presented as `grand_total`. A weekly spending figure built that way overstates
by roughly the exchange rate on every foreign line, and nothing downstream can tell.
"""

from finance_cli.enablebanking import aggregate_by_category


def _tx(amount: str, currency: str, name: str, indicator: str = "DBIT") -> dict:
    return {
        "credit_debit_indicator": indicator,
        "transaction_amount": {"amount": amount, "currency": currency},
        "creditor_name": name,
    }


def test_currencies_are_never_added_together():
    out = aggregate_by_category([_tx("100.00", "GBP", "Shop"), _tx("100.00", "EUR", "Bar")])
    assert out["grand_total"] == {"GBP": 100.00, "EUR": 100.00}


def test_one_merchant_billing_in_two_currencies_stays_split():
    """The same name in two currencies is two rows, not one impossible sum."""
    out = aggregate_by_category([_tx("10.00", "GBP", "Pan"), _tx("3.86", "EUR", "Pan")])
    rows = {(r["category"], r["currency"]): r["total"] for r in out["categories"]}
    assert rows == {("Pan", "GBP"): 10.00, ("Pan", "EUR"): 3.86}
    assert out["transaction_count"] == 2


def test_every_row_carries_its_currency():
    """A figure printed without its unit invites exactly the addition this guards against."""
    out = aggregate_by_category([_tx("5.00", "EUR", "Kiosk")])
    assert all("currency" in row for row in out["categories"])


def test_credits_are_still_excluded():
    """Unchanged behaviour, pinned so the currency work cannot quietly alter it."""
    out = aggregate_by_category([_tx("50.00", "GBP", "Refund", indicator="CRDT")])
    assert out["categories"] == []
    assert out["grand_total"] == {}
    assert out["transaction_count"] == 0


def test_a_missing_currency_is_marked_not_merged():
    """Unknown must not silently join a real currency's pile."""
    out = aggregate_by_category([{"credit_debit_indicator": "DBIT", "transaction_amount": {"amount": "7.00"}, "creditor_name": "X"}])
    assert out["grand_total"] == {"???": 7.00}
