"""`aggregate_by_category` must never add two currencies together."""

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
    """Credits are income and never enter the spending summary."""
    out = aggregate_by_category([_tx("50.00", "GBP", "Refund", indicator="CRDT")])
    assert out["categories"] == []
    assert out["grand_total"] == {}
    assert out["transaction_count"] == 0


def test_a_missing_currency_falls_back_to_the_account_currency():
    tx = {"credit_debit_indicator": "DBIT", "transaction_amount": {"amount": "7.00"}, "creditor_name": "X", "_account_currency": "GBP"}
    out = aggregate_by_category([tx])
    assert out["grand_total"] == {"GBP": 7.00}
