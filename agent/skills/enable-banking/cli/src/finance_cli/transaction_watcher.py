"""Poll Enable Banking for new transactions and write notifications."""

import json
import sys
import time
from datetime import datetime, UTC, timedelta
from pathlib import Path

SEEN_FILE = Path.home() / ".finance" / "seen_transactions.json"
NOTIFICATIONS_DIR = Path.home() / "notifications"
POLL_INTERVAL = 300  # 5 minutes


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(list(seen)))


def make_tx_id(tx: dict) -> str:
    """Create a unique ID for a transaction."""
    return f"{tx.get('entry_reference', '')}-{tx.get('booking_date', '')}-{tx.get('transaction_amount', {}).get('amount', '')}"


def format_tx(tx: dict) -> str:
    """Format a transaction for notification."""
    amount_info = tx.get("transaction_amount", {})
    amount = amount_info.get("amount", "?")
    currency = amount_info.get("currency", "")

    # Try to get merchant/description — handle both flat and nested formats
    details = tx.get("remittance_information_unstructured", "")
    if not details:
        ri = tx.get("remittance_information", [])
        if isinstance(ri, list) and ri:
            details = ri[0]
    if not details:
        creditor = tx.get("creditor", {})
        details = (creditor.get("name", "") if isinstance(creditor, dict) else tx.get("creditor_name", "")) or ""
    if not details:
        debtor = tx.get("debtor", {})
        details = (debtor.get("name", "") if isinstance(debtor, dict) else tx.get("debtor_name", "")) or ""
    if not details:
        details = "Unknown"

    # Credit or debit
    credit_debit = tx.get("credit_debit_indicator", "")
    sign = "+" if credit_debit == "CRDT" else "-" if credit_debit == "DBIT" else ""

    # Currency symbol
    symbols = {"GBP": "£", "EUR": "€", "USD": "$"}
    sym = symbols.get(currency, currency + " ")

    return f"{sign}{sym}{amount} — {details}"


def poll_once() -> list[dict]:
    """Check for new transactions. Returns list of new ones."""
    from finance_cli.enablebanking import get_transactions

    config_path = Path.home() / ".finance" / "config.json"
    if not config_path.exists():
        return []

    conf = json.loads(config_path.read_text())
    if not conf.get("session_id") or not conf.get("accounts"):
        return []

    seen = load_seen()
    new_txs = []

    # Only check last 2 days to keep it fast
    date_from = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = datetime.now(UTC).strftime("%Y-%m-%d")

    for account in conf["accounts"]:
        try:
            txs = get_transactions(conf, account["uid"], date_from=date_from, date_to=date_to)
            for tx in txs:
                tx_id = make_tx_id(tx)
                if tx_id and tx_id not in seen:
                    seen.add(tx_id)
                    tx["_account_currency"] = account.get("currency", "")
                    new_txs.append(tx)
        except Exception as e:
            print(f"Error checking account {account.get('uid', '?')}: {e}", file=sys.stderr)

    save_seen(seen)
    return new_txs


def write_notification(tx: dict) -> None:
    """Write a notification JSON for a new transaction."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    formatted = format_tx(tx)
    notification = {
        "type": "finance",
        "source": "finance",
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "message": f"New transaction: {formatted}",
    }

    filename = f"finance_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{hash(formatted) % 10000:04d}.json"
    (NOTIFICATIONS_DIR / filename).write_text(json.dumps(notification, indent=2))


def seed_seen() -> None:
    """Seed the seen file with current transactions so we don't notify on old ones."""
    from finance_cli.enablebanking import get_transactions

    config_path = Path.home() / ".finance" / "config.json"
    conf = json.loads(config_path.read_text())

    seen = set()
    date_from = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now(UTC).strftime("%Y-%m-%d")

    for account in conf.get("accounts", []):
        try:
            txs = get_transactions(conf, account["uid"], date_from=date_from, date_to=date_to)
            for tx in txs:
                tx_id = make_tx_id(tx)
                if tx_id:
                    seen.add(tx_id)
        except Exception as e:
            print(f"Error seeding account {account.get('uid', '?')}: {e}", file=sys.stderr)

    save_seen(seen)
    print(f"Seeded {len(seen)} existing transactions")


def serve() -> None:
    """Run the polling loop."""
    print(f"Transaction watcher started, polling every {POLL_INTERVAL}s")

    # Seed on first run if no seen file
    if not SEEN_FILE.exists():
        print("First run — seeding existing transactions...")
        seed_seen()

    while True:
        try:
            new_txs = poll_once()
            for tx in new_txs:
                formatted = format_tx(tx)
                print(f"New: {formatted}")
                write_notification(tx)
        except Exception as e:
            print(f"Poll error: {e}", file=sys.stderr)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "seed":
        seed_seen()
    elif cmd == "serve":
        serve()
    else:
        print("Usage: python -m finance_cli.transaction_watcher [serve|seed]", file=sys.stderr)
        sys.exit(1)
