#!/usr/bin/env python3
"""moneypot - shared expense & pot tracker (Splitwise/Tricount style).

A "pot" is a shared group (a trip, a household, a project) with members. Two
entry types are logged against it: expenses (a payer covers a cost, split among
members) and transfers (one member pays another directly). It computes net
balances and the minimum set of payments to settle up. Multi-currency: each pot
has a base currency; entries can be in another currency with an exchange rate.

Money is stored as integer minor units (pence/cents) so settle-up is exact with
no float drift. Stdlib only. Data in ~/agent/data/moneypot.json.

This module is both a CLI (`python3 moneypot.py ...`) and an importable service
layer (`create_pot`, `add_expense`, `add_transfer`, `balance`, ... raise
MoneypotError on bad input) used by the HTTP API in server.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, UTC
from pathlib import Path

# Persistent, gitignored data dir (the vesta platform convention; core stores
# its state here too). Override with MONEYPOT_DATA for a custom location.
DATA_FILE = Path(os.environ.get("MONEYPOT_DATA", Path.home() / "agent" / "data" / "moneypot.json"))
DATA_DIR = DATA_FILE.parent


class MoneypotError(ValueError):
    """Bad input. CLI maps it to a clean error+exit; the API maps it to HTTP 400."""


# ---------- storage ----------


def load() -> dict:
    if not DATA_FILE.exists():
        return {"pots": {}}
    try:
        return json.loads(DATA_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"pots": {}}


def save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(DATA_FILE)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_pot(data: dict, pot_id: str) -> dict:
    pot = data["pots"].get(pot_id)
    if pot is None:
        raise MoneypotError(f"no pot '{pot_id}'")
    return pot


def _next_entry_id(pot: dict) -> int:
    return max((e["id"] for e in pot["entries"]), default=0) + 1


# ---------- money helpers ----------


def to_cents(s) -> int:
    """Parse a money value ('12', '12.5', '12.50') to integer minor units."""
    s = str(s).strip().replace(",", "")
    if not s:
        raise MoneypotError("empty amount")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    try:
        if "." in s:
            whole, frac = s.split(".", 1)
            frac = (frac + "00")[:2]
        else:
            whole, frac = s, "00"
        cents = int(whole or "0") * 100 + int(frac or "0")
    except ValueError:
        raise MoneypotError(f"bad amount: {s!r}")
    return -cents if neg else cents


def fmt(cents: int, currency: str) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    sym = {"GBP": "£", "USD": "$", "EUR": "€", "JPY": "¥"}.get(currency, "")
    body = f"{c // 100:,}.{c % 100:02d}"
    return f"{sign}{sym}{body}" if sym else f"{sign}{body} {currency}"


def parse_rate(s) -> float:
    """Exchange rate: how many BASE units one ENTRY-currency unit is worth."""
    try:
        r = float(s)
    except (ValueError, TypeError):
        raise MoneypotError(f"bad rate: {s!r}")
    if r <= 0:
        raise MoneypotError("rate must be positive")
    return r


def convert(orig_cents: int, rate: float) -> int:
    return round(orig_cents * rate)


def fetch_rate(orig: str, base: str) -> float | None:
    """Best-effort live FX lookup (1 orig = ? base) via a free no-key API."""
    try:
        url = f"https://open.er-api.com/v6/latest/{orig.upper()}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("result") != "success":
            return None
        return data.get("rates", {}).get(base.upper())
    except Exception:
        return None


def resolve_rate(orig_currency: str, base_currency: str, rate=None, fetch: bool = False) -> float:
    if orig_currency.upper() == base_currency.upper():
        return 1.0
    if rate is not None:
        return parse_rate(rate)
    if fetch:
        r = fetch_rate(orig_currency, base_currency)
        if r is None:
            raise MoneypotError(f"couldn't fetch {orig_currency}->{base_currency} rate; supply a rate")
        return r
    raise MoneypotError(f"entry is in {orig_currency.upper()} but pot base is {base_currency.upper()}; supply a rate or fetch")


def split_equal(total: int, members: list[str]) -> dict[str, int]:
    """Split total cents equally; leftover pennies go to the first members."""
    n = len(members)
    base, rem = divmod(total, n)
    return {m: base + (1 if i < rem else 0) for i, m in enumerate(members)}


def _resolve_split(pot, orig_total, base_total, rate, orig_currency, for_list, split_map):
    """Per-member shares in BASE minor units. Custom split is in the ENTRY currency."""
    members = pot["members"]
    if split_map:
        orig_shares = {}
        for name, amt in split_map.items():
            name = name.strip()
            if name not in members:
                raise MoneypotError(f"'{name}' is not a member of this pot")
            orig_shares[name] = to_cents(amt)
        if sum(orig_shares.values()) != orig_total:
            raise MoneypotError(f"split must sum to {fmt(orig_total, orig_currency)}, got {fmt(sum(orig_shares.values()), orig_currency)}")
        base_shares = {m: convert(c, rate) for m, c in orig_shares.items()}
        drift = base_total - sum(base_shares.values())
        if drift and base_shares:
            biggest = max(base_shares, key=lambda m: base_shares[m])
            base_shares[biggest] += drift
        return base_shares
    if for_list:
        for m in for_list:
            if m not in members:
                raise MoneypotError(f"'{m}' is not a member of this pot")
        return split_equal(base_total, for_list)
    return split_equal(base_total, members)


# ---------- balance engine ----------


def compute_nets(pot: dict) -> dict[str, int]:
    """Net per member in cents. Positive = owed money / ahead. Negative = owes."""
    nets = {m: 0 for m in pot["members"]}
    for e in pot["entries"]:
        if e["type"] == "expense":
            nets[e["payer"]] = nets.get(e["payer"], 0) + e["amount"]
            for m, share in e["split"].items():
                nets[m] = nets.get(m, 0) - share
        elif e["type"] == "transfer":
            nets[e["from"]] = nets.get(e["from"], 0) + e["amount"]
            nets[e["to"]] = nets.get(e["to"], 0) - e["amount"]
    return nets


def settle_up(nets: dict[str, int]) -> list[tuple[str, str, int]]:
    """Minimal greedy settle-up: list of (debtor, creditor, cents)."""
    rem: dict[str, int] = dict(nets)
    creditors: list[str] = sorted((m for m, v in nets.items() if v > 0), key=lambda m: -nets[m])
    debtors: list[str] = sorted((m for m, v in nets.items() if v < 0), key=lambda m: nets[m])
    txns: list[tuple[str, str, int]] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d, c = debtors[i], creditors[j]
        pay = min(-rem[d], rem[c])
        if pay > 0:
            txns.append((d, c, pay))
        rem[d] += pay
        rem[c] -= pay
        if rem[d] == 0:
            i += 1
        if rem[c] == 0:
            j += 1
    return txns


# ---------- service layer (raises MoneypotError; used by CLI and API) ----------


def create_pot(data, pot_id, name=None, currency="GBP", members=None) -> dict:
    if not pot_id or not pot_id.strip():
        raise MoneypotError("pot id required")
    pot_id = pot_id.strip()
    if pot_id in data["pots"]:
        raise MoneypotError(f"pot '{pot_id}' already exists")
    members = members or []
    if isinstance(members, str):
        members = [m.strip() for m in members.split(",") if m.strip()]
    members = [m.strip() for m in members if m and m.strip()]
    if not members:
        raise MoneypotError("need at least one member")
    pot = {"name": name or pot_id, "currency": currency.upper(), "members": members, "created": _now(), "entries": []}
    data["pots"][pot_id] = pot
    return pot


def add_member(data, pot_id, name) -> dict:
    pot = get_pot(data, pot_id)
    name = (name or "").strip()
    if not name:
        raise MoneypotError("member name required")
    if name in pot["members"]:
        raise MoneypotError(f"'{name}' already a member")
    pot["members"].append(name)
    return pot


def add_expense(data, pot_id, payer, amount, desc="", currency=None, rate=None, fetch=False, for_list=None, split_map=None) -> dict:
    pot = get_pot(data, pot_id)
    base = pot["currency"]
    if payer not in pot["members"]:
        raise MoneypotError(f"payer '{payer}' is not a member")
    orig_total = to_cents(amount)
    if orig_total <= 0:
        raise MoneypotError("amount must be positive")
    orig_currency = (currency or base).upper()
    r = resolve_rate(orig_currency, base, rate, fetch)
    base_total = convert(orig_total, r)
    split = _resolve_split(pot, orig_total, base_total, r, orig_currency, for_list, split_map)
    entry = {
        "id": _next_entry_id(pot),
        "type": "expense",
        "payer": payer,
        "amount": base_total,
        "currency": orig_currency,
        "rate": r,
        "orig_amount": orig_total,
        "desc": desc or "",
        "split": split,
        "ts": _now(),
    }
    pot["entries"].append(entry)
    return entry


def add_transfer(data, pot_id, sender, recipient, amount, desc="", currency=None, rate=None, fetch=False) -> dict:
    pot = get_pot(data, pot_id)
    base = pot["currency"]
    for who, label in ((sender, "from"), (recipient, "to")):
        if who not in pot["members"]:
            raise MoneypotError(f"{label} '{who}' is not a member")
    if sender == recipient:
        raise MoneypotError("from and to must differ")
    orig_amt = to_cents(amount)
    if orig_amt <= 0:
        raise MoneypotError("amount must be positive")
    orig_currency = (currency or base).upper()
    r = resolve_rate(orig_currency, base, rate, fetch)
    base_amt = convert(orig_amt, r)
    entry = {
        "id": _next_entry_id(pot),
        "type": "transfer",
        "from": sender,
        "to": recipient,
        "amount": base_amt,
        "currency": orig_currency,
        "rate": r,
        "orig_amount": orig_amt,
        "desc": desc or "",
        "ts": _now(),
    }
    pot["entries"].append(entry)
    return entry


def remove_entry(data, pot_id, entry_id) -> None:
    pot = get_pot(data, pot_id)
    before = len(pot["entries"])
    pot["entries"] = [e for e in pot["entries"] if e["id"] != entry_id]
    if len(pot["entries"]) == before:
        raise MoneypotError(f"no entry #{entry_id} in {pot_id}")


def balance(data, pot_id) -> dict:
    pot = get_pot(data, pot_id)
    nets = compute_nets(pot)
    paid = {m: 0 for m in pot["members"]}
    for e in pot["entries"]:
        if e["type"] == "expense":
            paid[e["payer"]] = paid.get(e["payer"], 0) + e["amount"]
    total_spent = sum(e["amount"] for e in pot["entries"] if e["type"] == "expense")
    txns = settle_up(nets)
    return {
        "pot": pot_id,
        "currency": pot["currency"],
        "total_spent": total_spent,
        "balances": {m: nets.get(m, 0) for m in pot["members"]},
        "paid": paid,
        "settle_up": [{"from": d, "to": c, "amount": a} for d, c, a in txns],
    }


def contributions(data, pot_id, account) -> dict:
    pot = get_pot(data, pot_id)
    if account not in pot["members"]:
        raise MoneypotError(f"'{account}' is not a member of this pot")
    others = [m for m in pot["members"] if m != account]
    if not others:
        raise MoneypotError("pot has no members besides the account")
    contributed = {m: 0 for m in others}
    owed_back = {m: 0 for m in others}
    for e in pot["entries"]:
        if e["type"] == "transfer":
            if e["to"] == account and e["from"] in contributed:
                contributed[e["from"]] += e["amount"]
            if e["from"] == account and e["to"] in owed_back:
                owed_back[e["to"]] -= e["amount"]
        elif e["type"] == "expense" and e["payer"] in owed_back:
            owed_back[e["payer"]] += e["split"].get(account, 0)
    target = max(contributed.values())
    return {
        "pot": pot_id,
        "currency": pot["currency"],
        "account": account,
        "contributed": contributed,
        "topup_to_match": {m: target - contributed[m] for m in others},
        "account_owes": {m: owed_back[m] for m in others if owed_back[m] != 0},
    }


# ---------- CLI ----------


def _die(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _rule(width=48):
    return "-" * width


def _split_map(split_csv):
    if not split_csv:
        return None
    out = {}
    for part in split_csv.split(","):
        if ":" not in part:
            raise MoneypotError(f"bad split part {part!r}, expected Name:amount")
        name, amt = part.split(":", 1)
        out[name.strip()] = amt
    return out


def cmd_pot_create(args):
    data = load()
    create_pot(data, args.id, args.name, args.currency, args.members)
    save(data)
    print(f"created pot '{args.id}' ({args.name or args.id}) in {args.currency.upper()} with members: {args.members}")


def cmd_pot_list(args):
    data = load()
    if args.json:
        print(
            json.dumps(
                [
                    {"id": pid, **{k: v for k, v in p.items() if k != "entries"}, "entries": len(p["entries"])}
                    for pid, p in data["pots"].items()
                ],
                indent=2,
            )
        )
        return
    if not data["pots"]:
        print("no pots yet. create one: moneypot pot create <id> --members 'A,B'")
        return
    print(f"  {'POT':<14} {'NAME':<22} {'CUR':<5} {'ENTRIES':>7}  MEMBERS")
    print(f"  {_rule(64)}")
    for pid, p in data["pots"].items():
        print(f"  {pid:<14} {p['name'][:22]:<22} {p['currency']:<5} {len(p['entries']):>7}  {', '.join(p['members'])}")


def cmd_pot_delete(args):
    data = load()
    get_pot(data, args.id)
    if not args.yes:
        _die("pass --yes to confirm deleting the whole pot and its history")
    del data["pots"][args.id]
    save(data)
    print(f"deleted pot '{args.id}'")


def cmd_member_add(args):
    data = load()
    add_member(data, args.id, args.name)
    save(data)
    print(f"added member '{args.name}' to {args.id}")


def cmd_add_expense(args):
    data = load()
    e = add_expense(
        data,
        args.id,
        args.payer,
        args.amount,
        args.desc,
        args.currency,
        args.rate,
        args.fetch,
        [m.strip() for m in args.for_.split(",")] if args.for_ else None,
        _split_map(args.split),
    )
    save(data)
    pot = data["pots"][args.id]
    base = pot["currency"]
    shares = ", ".join(f"{m} {fmt(s, base)}" for m, s in e["split"].items())
    tail = f" (= {fmt(e['amount'], base)} @ {e['rate']})" if e["currency"] != base else ""
    print(f"#{e['id']} expense: {e['payer']} paid {fmt(e['orig_amount'], e['currency'])}{tail} for {e['desc'] or '(no desc)'}")
    print(f"   split: {shares}")


def cmd_add_transfer(args):
    data = load()
    e = add_transfer(data, args.id, args.from_, args.to, args.amount, args.desc, args.currency, args.rate, args.fetch)
    save(data)
    base = data["pots"][args.id]["currency"]
    tail = f" (= {fmt(e['amount'], base)} @ {e['rate']})" if e["currency"] != base else ""
    note = f" ({e['desc']})" if e["desc"] else ""
    print(f"#{e['id']} transfer: {e['from']} -> {e['to']} {fmt(e['orig_amount'], e['currency'])}{tail}{note}")


def cmd_list(args):
    data = load()
    pot = get_pot(data, args.id)
    cur = pot["currency"]
    if args.json:
        print(json.dumps(pot["entries"], indent=2, ensure_ascii=False))
        return
    if not pot["entries"]:
        print(f"{pot['name']}: no entries yet")
        return
    print(f"{pot['name']} [{cur}]  ·  {len(pot['entries'])} entries")
    print(f"  {_rule(60)}")
    for e in pot["entries"]:
        ecur = e.get("currency", cur)
        orig = f"  [{fmt(e.get('orig_amount', e['amount']), ecur)} @ {e.get('rate', 1)}]" if ecur != cur else ""
        who = f"{e['payer']} paid" if e["type"] == "expense" else f"{e['from']} -> {e['to']}"
        print(f"  #{e['id']:<3} {e['ts'][:10]}  {who:<22} {fmt(e['amount'], cur):>12}{orig}  {e['desc']}")


def cmd_balance(args):
    data = load()
    b = balance(data, args.id)
    cur = b["currency"]
    if args.json:
        print(json.dumps(b, indent=2))
        return
    pot = data["pots"][args.id]
    print(f"{pot['name']} [{cur}]  ·  total spent {fmt(b['total_spent'], cur)}")
    print(f"  {_rule(44)}")
    print(f"  {'MEMBER':<16} {'NET':>12}   PAID")
    for m in pot["members"]:
        print(f"  {m:<16} {fmt(b['balances'][m], cur):>12}   (paid {fmt(b['paid'][m], cur)})")
    print("  (positive = owed to them · negative = they owe)")
    print(f"  {_rule(44)}")
    if not b["settle_up"]:
        print("  settle-up: all square ✓")
    else:
        print("  settle-up (minimum payments):")
        for t in b["settle_up"]:
            print(f"     {t['from']} pays {t['to']}  {fmt(t['amount'], cur)}")


def cmd_contributions(args):
    data = load()
    c = contributions(data, args.id, args.account)
    cur = c["currency"]
    if args.json:
        print(json.dumps(c, indent=2))
        return
    pot = data["pots"][args.id]
    print(f"{pot['name']} [{cur}]  ·  contributions into '{c['account']}'")
    print(f"  {_rule(44)}")
    for m, amt in c["contributed"].items():
        gap = c["topup_to_match"][m]
        tail = f"  (add {fmt(gap, cur)} to match)" if gap > 0 else "  ✓ level"
        print(f"  {m:<16} {fmt(amt, cur):>12}{tail}")
    if c["account_owes"]:
        print(f"  {_rule(44)}")
        print(f"  '{c['account']}' still owes (out-of-pocket, net of repayments):")
        for m, amt in c["account_owes"].items():
            print(f"     {m}  {fmt(amt, cur)}")


def cmd_delete_entry(args):
    data = load()
    remove_entry(data, args.id, args.entry_id)
    save(data)
    print(f"deleted entry #{args.entry_id} from {args.id}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moneypot", description="Shared expense & pot tracker (Splitwise/Tricount style).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pot = sub.add_parser("pot", help="manage pots (shared groups)")
    potsub = pot.add_subparsers(dest="potcmd", required=True)
    pc = potsub.add_parser("create", help="create a pot")
    pc.add_argument("id")
    pc.add_argument("--name", default=None)
    pc.add_argument("--currency", default="GBP")
    pc.add_argument("--members", required=True, help="comma-separated, e.g. 'Alice,Bob'")
    pc.set_defaults(func=cmd_pot_create)
    pl = potsub.add_parser("list", help="list pots")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_pot_list)
    pd = potsub.add_parser("delete", help="delete a pot")
    pd.add_argument("id")
    pd.add_argument("--yes", action="store_true")
    pd.set_defaults(func=cmd_pot_delete)

    m = sub.add_parser("member", help="manage members")
    msub = m.add_subparsers(dest="memcmd", required=True)
    ma = msub.add_parser("add", help="add a member to a pot")
    ma.add_argument("id")
    ma.add_argument("name")
    ma.set_defaults(func=cmd_member_add)

    ae = sub.add_parser("add-expense", help="log a shared expense someone paid")
    ae.add_argument("id")
    ae.add_argument("--payer", required=True)
    ae.add_argument("--amount", required=True)
    ae.add_argument("--desc", default="")
    ae.add_argument("--for", dest="for_", default=None, help="split equally among these members, e.g. 'Alice,Bob'")
    ae.add_argument("--split", default=None, help="custom amounts in entry currency, e.g. 'Alice:60,Bob:40'")
    ae.add_argument("--currency", default=None, help="entry currency if different from pot base, e.g. EGP")
    ae.add_argument("--rate", default=None, help="1 entry-currency unit = ? base units")
    ae.add_argument("--fetch", action="store_true", help="auto-fetch the FX rate")
    ae.set_defaults(func=cmd_add_expense)

    at = sub.add_parser("add-transfer", help="log a direct payment between members")
    at.add_argument("id")
    at.add_argument("--from", dest="from_", required=True)
    at.add_argument("--to", required=True)
    at.add_argument("--amount", required=True)
    at.add_argument("--desc", default="")
    at.add_argument("--currency", default=None)
    at.add_argument("--rate", default=None)
    at.add_argument("--fetch", action="store_true")
    at.set_defaults(func=cmd_add_transfer)

    ls = sub.add_parser("list", help="show a pot's entry history")
    ls.add_argument("id")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    bal = sub.add_parser("balance", help="show balances + settle-up plan")
    bal.add_argument("id")
    bal.add_argument("--json", action="store_true")
    bal.set_defaults(func=cmd_balance)

    con = sub.add_parser("contributions", help="joint-account view: contribution equality + what the account owes")
    con.add_argument("id")
    con.add_argument("--account", required=True, help="the pooled-account member, e.g. Joint")
    con.add_argument("--json", action="store_true")
    con.set_defaults(func=cmd_contributions)

    de = sub.add_parser("delete-entry", help="remove an entry by id")
    de.add_argument("id")
    de.add_argument("entry_id", type=int)
    de.set_defaults(func=cmd_delete_entry)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except MoneypotError as e:
        _die(str(e))


if __name__ == "__main__":
    main()
