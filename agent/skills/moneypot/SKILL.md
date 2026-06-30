---
name: moneypot
description: Track shared expenses and joint money pots (Splitwise/Tricount style). Use when the user wants to record who paid for what in a group, money put into a shared pot, split costs among people, see who owes whom, or get the minimum set of payments to settle up. Also exposes an optional HTTP/JSON API. Keywords: split the bill, who owes, shared expenses, joint account, money pot, settle up, IOU, tricount, splitwise.
---

# Moneypot

A shared expense and pot tracker. A **pot** is a group (a trip, a household, a project) with members. You log two kinds of entries against it, and it computes net balances and the cheapest way to settle up. CLI plus an optional HTTP API. Data lives in `~/agent/data/moneypot.json` (shared by both).

Run the CLI with `python3 ~/agent/skills/moneypot/moneypot.py <command>`.

## Model

- **expense**: someone paid for a shared cost, split among members. Covers "I put money in / paid for a shared thing". The payer is credited the full amount; each member is debited their share.
- **transfer**: one member paid another directly (settling up, or moving cash). The sender is credited, the recipient debited.
- **balance**: net per member. Positive = owed money (ahead). Negative = owes. Nets always sum to zero.
- **settle-up**: the minimum list of payments that zeroes everyone out.

Amounts are stored as integer minor units (pence/cents), so there's no float drift. Equal splits distribute leftover pennies to the first members.

## CLI

```bash
PY="python3 ~/agent/skills/moneypot/moneypot.py"

# create a pot
$PY pot create trip --name "Ski Trip" --currency GBP --members "Alice,Bob,Cara"
$PY pot list
$PY pot delete trip --yes
$PY member add trip Dan

# expenses (default: split equally among ALL members)
$PY add-expense trip --payer Alice --amount 300 --desc "cabin"
$PY add-expense trip --payer Bob --amount 60 --desc "lunch" --for "Alice,Bob"      # subset, equal
$PY add-expense trip --payer Cara --amount 100 --desc "gear" --split "Alice:50,Bob:50,Cara:0"  # custom (entry currency)

# expense in another currency: give the rate, or --fetch it live
$PY add-expense trip --payer Alice --amount 10000 --currency EGP --rate 0.016 --desc "spa"
$PY add-expense trip --payer Alice --amount 10000 --currency EGP --fetch --desc "spa"

# direct payment between members (also takes --currency/--rate/--fetch)
$PY add-transfer trip --from Bob --to Alice --amount 25 --desc "settle"

# views (all take --json)
$PY list trip
$PY balance trip
$PY delete-entry trip 3
```

## Multi-currency

Each pot has a **base currency** (set at create). Every balance and settle-up is in the base. Any entry can be in a different currency:

- `--currency XXX` marks the entry currency; if it differs from base you must give the rate.
- `--rate R` = how many **base** units one **entry** unit is worth (`--currency EGP --rate 0.016` = 1 EGP is £0.016 when base is GBP).
- `--fetch` pulls a live rate (free no-key API); falls back to asking for `--rate`. The rate is stored on the entry, so old balances stay stable when FX moves.
- Custom `--split` is given in the entry currency and converted (rounding trued-up so shares sum exactly).

## Joint-account pattern

A pooled account (a couple's joint card) is just a member: `--members "Alice,Bob,Joint"`. Then:

- **Fill it**: `add-transfer pot --from Alice --to Joint --amount 300`.
- **Out-of-pocket cost that should've been joint**: `add-expense pot --payer Bob --amount 80 --for "Joint"` (Joint now owes Bob £80).
- **Account repays**: `add-transfer pot --from Joint --to Bob --amount 30`.
- Everyday spending straight off the joint card needn't be logged.

`contributions pot --account Joint` then reports who's paid in how much and the top-up the lower one needs to stay level, plus what the account still owes each person:

```
contributions into 'Joint':
  Alice              £300.00  ✓ level
  Bob                £200.00  (add £100.00 to match)
'Joint' still owes (out-of-pocket, net of repayments):
   Bob  £50.00
```

## HTTP API (optional)

`server.py` is a stdlib JSON API over the same data, for dashboards or other apps. Mutations are lock-serialized. See `SETUP.md` to run it as a vestad service. Routes:

```
GET    /health
GET    /pots                                list pots
POST   /pots                                {id, name?, currency?, members:[...]}
GET    /pots/{id}                           full pot
DELETE /pots/{id}
GET    /pots/{id}/entries
POST   /pots/{id}/members                   {name}
POST   /pots/{id}/expenses                  {payer, amount, desc?, currency?, rate?, fetch?, for?:[...], split?:{Name:amt}}
POST   /pots/{id}/transfers                 {from, to, amount, desc?, currency?, rate?, fetch?}
DELETE /pots/{id}/entries/{eid}
GET    /pots/{id}/balance
GET    /pots/{id}/contributions?account=X
```

Errors return `{"error": "..."}` with HTTP 400 (bad input), 404 (no route), or 401 (bad key).

**Public vs private.** By default the API is open. Set an app-level key with `--api-key KEY` (or `MONEYPOT_API_KEY`) to require it on every route except `/health`; callers pass `Authorization: Bearer KEY` or `X-API-Key: KEY`, otherwise 401. This is independent of vestad's own token gating (registering the service without `--public` adds a second layer).

## Notes

- `--currency` accepts any label; `GBP/USD/EUR/JPY` print with a symbol, others print the code.
- "How much each person put in" = the **paid** figure shown next to each balance.
- No setup needed for CLI use; the data file is created on first write. The API needs the one-time service registration in `SETUP.md`.
- Self-contained, stdlib only, no personal data baked in.
