"""Poll Enable Banking for new transactions and write notifications."""

import json
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

SEEN_FILE = Path.home() / ".finance" / "seen_transactions.json"
NOTIFICATIONS_DIR = Path.home() / "notifications"
POLL_INTERVAL = 300  # 5 minutes


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to path atomically: write a sibling temp file, then rename over the target, so a
    monitor tick globbing the notifications dir never observes a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


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
    formatted = format_tx(tx)
    notification = {
        "type": "finance",
        "source": "finance",
        # A new transaction is a record to review when idle, not something to drop everything for, so it
        # pools by default. The user can add an interrupt rule for e.g. large amounts if they want.
        "interrupt": False,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "message": f"New transaction: {formatted}",
    }

    filename = f"{time.time_ns()}-finance-message.json"
    atomic_write_text(NOTIFICATIONS_DIR / filename, json.dumps(notification, indent=2))


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


def write_died_notification(reason: str) -> None:
    """Announce that this watcher is going away without having been asked to.

    A poller's silence is indistinguishable from a quiet period, so a watcher that dies simply
    stops producing spending notifications and nobody learns until a human checks by hand. The
    daemon contract in `skills/vestad/SKILL.md` defines a `daemon_died` notification for exactly
    this, but it is per-daemon opt-in and this skill had never opted in.

    interrupt=True, unlike the transaction notification above: a transaction is a record to review
    when idle, whereas a dead watcher means every FUTURE record is silently lost.
    """
    notification = {
        "type": "daemon_died",
        "source": "finance",
        "interrupt": True,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "message": f"finance watcher exited unexpectedly ({reason}). Spending notifications are "
        "stopped until it is restarted with `finance daemon start`.",
    }
    filename = f"{time.time_ns()}-finance-daemon_died.json"
    atomic_write_text(NOTIFICATIONS_DIR / filename, json.dumps(notification, indent=2))


def serve() -> None:
    """Run the polling loop, reporting any death nobody asked for."""
    print(f"Transaction watcher started, polling every {POLL_INTERVAL}s")

    # A deliberate stop must never be reported as a crash, which is the half of the contract that
    # is easy to miss. `finance daemon stop` sends SIGTERM, so SIGTERM alone is the quiet exit.
    asked_to_stop = False

    def _on_sigterm(_signum, _frame):
        nonlocal asked_to_stop
        asked_to_stop = True
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        _poll_forever()
    except BaseException as exc:
        # Deliberately BaseException: the poll loop already swallows every `Exception`, so anything
        # reaching here is a SystemExit, a KeyboardInterrupt, a MemoryError or similar, which is
        # precisely the class of death that used to happen in total silence. Re-raised after the
        # notification is written, so the process still exits and a supervisor still sees it.
        if not asked_to_stop:
            write_died_notification(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
        raise
    else:
        # The loop never returns on its own, so an ordinary return is itself an anomaly.
        if not asked_to_stop:
            write_died_notification("poll loop returned unexpectedly")


def _poll_forever() -> None:
    while True:
        try:
            # The seed is what keeps the first poll quiet, and it needs the config a watcher
            # started before sign-in does not have yet, so a failure just waits a cycle.
            if SEEN_FILE.exists():
                for tx in poll_once():
                    formatted = format_tx(tx)
                    print(f"New: {formatted}")
                    write_notification(tx)
            else:
                print("First run — seeding existing transactions...")
                seed_seen()
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
