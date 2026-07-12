"""Tricount API client.

Reverse-engineered from:
  - https://github.com/elrandar/tricount-api (MIT, primary reference)
  - https://github.com/mlaily/TricountApi (F# notebook)

Base URL: https://api.tricount.bunq.com
Auth: anonymous device registration via RSA key + UUID (no account credentials needed).

All amounts are negative strings for expenses (e.g. "-25.00"), positive for income.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from . import config

BASE_URL = "https://api.tricount.bunq.com"

# Android app User-Agent from reverse-engineering (elrandar/tricount-api)
USER_AGENT = "com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C"

# Hardcoded request tracking ID used by the official app (elrandar/tricount-api)
REQUEST_ID = "049bfcdf-6ae4-4cee-af7b-45da31ea85d0"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Amount:
    value: str
    currency: str

    @property
    def display(self) -> str:
        val = float(self.value)
        sign = "-" if val < 0 else "+"
        return f"{sign}{abs(val):.2f} {self.currency}"

    @property
    def abs_float(self) -> float:
        return abs(float(self.value))


@dataclass
class Member:
    id: int
    uuid: str
    display_name: str
    status: str  # ACTIVE | INACTIVE | DELETED


@dataclass
class Allocation:
    membership_uuid: str
    amount: Amount
    alloc_type: str  # AMOUNT | RATIO


@dataclass
class Transaction:
    id: int
    uuid: str
    description: str
    amount: Amount
    payer_uuid: str
    allocations: list[Allocation]
    date: str
    tx_type: str  # NORMAL | INCOME | BALANCE
    status: str  # ACTIVE | INACTIVE | SETTLED


@dataclass
class Tricount:
    id: int
    uuid: str
    title: str
    currency: str
    status: str  # READ_WRITE | READ_ONLY | ARCHIVED
    public_identifier_token: str
    members: list[Member] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)

    def member_by_uuid(self, member_uuid: str) -> Member | None:
        for m in self.members:
            if m.uuid == member_uuid:
                return m
        return None

    def member_by_name(self, name: str) -> Member | None:
        name_lower = name.lower()
        for m in self.members:
            if m.display_name.lower() == name_lower:
                return m
        return None

    def transaction_by_id(self, entry_id: int) -> Transaction | None:
        for tx in self.transactions:
            if tx.id == entry_id:
                return tx
        return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TricountClient:
    """Client for the unofficial Tricount API."""

    def __init__(self) -> None:
        self._creds: dict | None = config.load_creds()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self) -> dict:
        """Register a new anonymous device and persist credentials.

        No Tricount account needed. Generates an RSA key pair and registers
        with the Tricount backend to get an auth token and user_id.

        Returns the credentials dict (also saved to ~/.tricount/credentials.json).
        """
        # Generate RSA 2048-bit key pair (PKCS1 format as expected by the API)
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.PKCS1,
            )
            .decode()
        )

        installation_uuid = str(uuid.uuid4())

        resp = httpx.post(
            f"{BASE_URL}/v1/session-registry-installation",
            headers={
                "User-Agent": USER_AGENT,
                "app-id": installation_uuid,
                "X-Bunq-Client-Request-Id": REQUEST_ID,
                "Content-Type": "application/json",
            },
            json={
                "app_installation_uuid": installation_uuid,
                "client_public_key": public_key_pem,
                "device_description": "vesta",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        token: str | None = None
        user_id: int | None = None
        for item in data.get("Response", []):
            if "Token" in item:
                token = item["Token"]["token"]
            if "UserPerson" in item:
                user_id = item["UserPerson"]["id"]

        if not token or not user_id:
            raise RuntimeError(f"Unexpected auth response: {data}")

        creds = {
            "app_installation_uuid": installation_uuid,
            "auth_token": token,
            "user_id": user_id,
            "public_key_pem": public_key_pem,
        }
        config.save_creds(creds)
        self._creds = creds
        return creds

    def ensure_auth(self) -> dict:
        """Load existing credentials or authenticate fresh."""
        if not self._creds:
            self._creds = config.load_creds()
        if not self._creds:
            raise RuntimeError("Not authenticated. Run: tricount auth register")
        return self._creds

    def auth_status(self) -> dict:
        creds = config.load_creds()
        if not creds:
            return {"status": "not_authenticated"}
        return {
            "status": "authenticated",
            "user_id": creds["user_id"],
            "app_installation_uuid": creds["app_installation_uuid"],
            "credentials_file": str(config.CREDS_FILE),
        }

    def logout(self) -> dict:
        deleted = config.delete_creds()
        self._creds = None
        return {"deleted": deleted}

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        creds = self.ensure_auth()
        return {
            "User-Agent": USER_AGENT,
            "app-id": creds["app_installation_uuid"],
            "X-Bunq-Client-Request-Id": REQUEST_ID,
            "X-Bunq-Client-Authentication": creds["auth_token"],
            "Content-Type": "application/json",
        }

    def _user_id(self) -> int:
        return self.ensure_auth()["user_id"]

    def _get(self, path: str) -> Any:
        resp = httpx.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> Any:
        resp = httpx.post(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> Any:
        resp = httpx.put(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> Any:
        resp = httpx.delete(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Tricount operations
    # ------------------------------------------------------------------

    def list_tricounts(self) -> list[Tricount]:
        """List all tricounts the current device has joined."""
        data = self._get(f"/v1/user/{self._user_id()}/registry")
        return [self._parse_registry(item["Registry"]) for item in data.get("Response", []) if "Registry" in item]

    def join_tricount(self, token: str) -> Tricount:
        """Join a tricount by its public identifier token (e.g. 'tABC123').

        The token is the last segment of a Tricount sharing URL:
          https://www.tricount.com/en/topic/tABC123...
        or the short code shown in the app.

        After joining, the tricount appears in list_tricounts().
        """
        body = {
            "all_registry_active": [{"public_identifier_token": token}],
            "all_registry_archived": [],
            "all_registry_deleted": [],
        }
        self._post(f"/v1/user/{self._user_id()}/registry-synchronization", body)

        # After sync, find the tricount in the list
        for t in self.list_tricounts():
            if t.public_identifier_token == token:
                return t
        raise RuntimeError(f"Could not find tricount with token '{token}' after joining")

    def get_tricount(self, tricount_id: int) -> Tricount:
        """Get a specific tricount by numeric ID."""
        for t in self.list_tricounts():
            if t.id == tricount_id:
                return t
        raise RuntimeError(f"Tricount {tricount_id} not found (not joined?)")

    def find_tricount(self, id_or_token: str) -> Tricount:
        """Find a tricount by numeric ID or public token string."""
        tricounts = self.list_tricounts()
        if id_or_token.isdigit():
            target_id = int(id_or_token)
            for t in tricounts:
                if t.id == target_id:
                    return t
        else:
            for t in tricounts:
                if t.public_identifier_token == id_or_token:
                    return t
                if t.title.lower() == id_or_token.lower():
                    return t
        raise RuntimeError(
            f"Tricount '{id_or_token}' not found. Use 'tricount list' to see available tricounts, or 'tricount join <token>' to join one."
        )

    # ------------------------------------------------------------------
    # Expense operations
    # ------------------------------------------------------------------

    def _build_equal_allocations(
        self,
        split_uuids: list[str],
        amount: float,
        currency: str,
    ) -> list[dict[str, Any]]:
        """Build equal-split AMOUNT allocations, distributing rounding remainder to the last member."""
        n = len(split_uuids)
        share = round(amount / n, 2)
        allocations: list[dict[str, Any]] = [
            {
                "membership_uuid": m_uuid,
                "amount": {"value": f"-{share:.2f}", "currency": currency},
                "type": "AMOUNT",
            }
            for m_uuid in split_uuids
        ]
        # Fix rounding: last allocation absorbs the remainder
        total_allocated = round(share * n, 2)
        if total_allocated != round(amount, 2):
            diff = round(amount - total_allocated, 2)
            last_val = share + diff
            allocations[-1]["amount"]["value"] = f"-{last_val:.2f}"
        return allocations

    def _build_fixed_allocations(
        self,
        amount_splits: dict[str, float],
        currency: str,
    ) -> list[dict[str, Any]]:
        """Build fixed AMOUNT allocations from a uuid->amount mapping."""
        return [
            {
                "membership_uuid": m_uuid,
                "amount": {"value": f"-{amt:.2f}", "currency": currency},
                "type": "AMOUNT",
            }
            for m_uuid, amt in amount_splits.items()
        ]

    def _build_ratio_allocations(
        self,
        ratio_splits: dict[str, float],
        amount: float,
        currency: str,
    ) -> list[dict[str, Any]]:
        """Build proportional AMOUNT allocations from a uuid->shares mapping.

        Computes each member's share of the total proportionally, with the last
        member absorbing any rounding remainder.
        """
        total_ratio = sum(ratio_splits.values())
        uuids = list(ratio_splits.keys())
        ratios = [ratio_splits[u] for u in uuids]

        raw_amounts = [round(amount * r / total_ratio, 2) for r in ratios]
        # Fix rounding remainder: adjust last entry
        total_allocated = round(sum(raw_amounts), 2)
        if total_allocated != round(amount, 2):
            diff = round(amount - total_allocated, 2)
            raw_amounts[-1] = round(raw_amounts[-1] + diff, 2)

        return [
            {
                "membership_uuid": uuids[i],
                "amount": {"value": f"-{raw_amounts[i]:.2f}", "currency": currency},
                "type": "AMOUNT",
            }
            for i in range(len(uuids))
        ]

    def add_expense(
        self,
        tricount: Tricount,
        description: str,
        amount: float,
        payer_uuid: str,
        split_uuids: list[str] | None = None,
        amount_splits: dict[str, float] | None = None,
        ratio_splits: dict[str, float] | None = None,
        date: str | None = None,
    ) -> dict:
        """Add an expense to a tricount.

        Split modes (mutually exclusive, in order of precedence):
          amount_splits: {uuid -> fixed_amount} — AMOUNT type, exact per-member values
          ratio_splits:  {uuid -> shares}       — proportional, computed as AMOUNT type
          split_uuids:   [uuid, ...]            — equal split among listed members

        If none are provided, raises ValueError.
        """
        if amount_splits:
            allocations = self._build_fixed_allocations(amount_splits, tricount.currency)
        elif ratio_splits:
            allocations = self._build_ratio_allocations(ratio_splits, amount, tricount.currency)
        elif split_uuids:
            allocations = self._build_equal_allocations(split_uuids, amount, tricount.currency)
        else:
            raise ValueError("One of split_uuids, amount_splits, or ratio_splits must be provided")

        if date is None:
            date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000000")

        body = {
            "description": description,
            "amount": {"value": f"-{amount:.2f}", "currency": tricount.currency},
            "membership_uuid_owner": payer_uuid,
            "type_transaction": "NORMAL",
            "allocations": allocations,
            "date": date,
        }
        return self._post(
            f"/v1/user/{self._user_id()}/registry/{tricount.id}/registry-entry",
            body,
        )

    def edit_expense(
        self,
        tricount: Tricount,
        entry_id: int,
        description: str | None = None,
        amount: float | None = None,
        payer_uuid: str | None = None,
        split_uuids: list[str] | None = None,
        amount_splits: dict[str, float] | None = None,
        ratio_splits: dict[str, float] | None = None,
        date: str | None = None,
    ) -> dict:
        """Edit an existing expense (PUT).

        Any parameter left as None is copied from the existing expense.
        Provide at least one change.
        """
        existing = tricount.transaction_by_id(entry_id)
        if existing is None:
            raise RuntimeError(f"Expense {entry_id} not found in tricount '{tricount.title}'")

        # Merge with existing values
        new_description = description if description is not None else existing.description
        new_amount = amount if amount is not None else existing.amount.abs_float
        new_payer_uuid = payer_uuid if payer_uuid is not None else existing.payer_uuid
        new_date = date if date is not None else existing.date

        # Build allocations
        allocations: list[dict[str, Any]]
        if amount_splits:
            allocations = self._build_fixed_allocations(amount_splits, tricount.currency)
        elif ratio_splits:
            allocations = self._build_ratio_allocations(ratio_splits, new_amount, tricount.currency)
        elif split_uuids:
            allocations = self._build_equal_allocations(split_uuids, new_amount, tricount.currency)
        else:
            # Reuse existing allocations (with updated amount if changed)
            if amount is not None:
                # Recompute proportionally from existing split
                existing_total = sum(a.amount.abs_float for a in existing.allocations)
                if existing_total > 0:
                    allocations = [
                        {
                            "membership_uuid": a.membership_uuid,
                            "amount": {
                                "value": f"-{round(new_amount * a.amount.abs_float / existing_total, 2):.2f}",
                                "currency": tricount.currency,
                            },
                            "type": "AMOUNT",
                        }
                        for a in existing.allocations
                    ]
                    # Fix rounding
                    total_alloc = sum(float(a["amount"]["value"]) for a in allocations)
                    diff = round(-new_amount - total_alloc, 2)
                    if diff != 0:
                        last = allocations[-1]
                        cur = float(last["amount"]["value"])
                        last["amount"]["value"] = f"{cur + diff:.2f}"
                else:
                    allocations = [
                        {
                            "membership_uuid": a.membership_uuid,
                            "amount": {"value": a.amount.value, "currency": tricount.currency},
                            "type": "AMOUNT",
                        }
                        for a in existing.allocations
                    ]
            else:
                allocations = [
                    {
                        "membership_uuid": a.membership_uuid,
                        "amount": {"value": a.amount.value, "currency": tricount.currency},
                        "type": "AMOUNT",
                    }
                    for a in existing.allocations
                ]

        body = {
            "description": new_description,
            "amount": {"value": f"-{new_amount:.2f}", "currency": tricount.currency},
            "membership_uuid_owner": new_payer_uuid,
            "type_transaction": existing.tx_type,
            "allocations": allocations,
            "date": new_date,
        }
        return self._put(
            f"/v1/user/{self._user_id()}/registry/{tricount.id}/registry-entry/{entry_id}",
            body,
        )

    def delete_expense(self, tricount: Tricount, entry_id: int) -> dict:
        """Delete an expense by ID.

        Sends DELETE to /v1/user/{userId}/registry/{registryId}/registry-entry/{entryId}.
        """
        return self._delete(f"/v1/user/{self._user_id()}/registry/{tricount.id}/registry-entry/{entry_id}")

    # ------------------------------------------------------------------
    # Balance calculation (client-side)
    # ------------------------------------------------------------------

    def get_balances(self, tricount: Tricount) -> list[dict]:
        """Calculate net balances for each member (client-side computation).

        Positive balance = member is owed money.
        Negative balance = member owes money.
        """
        member_by_uuid = {m.uuid: m for m in tricount.members}
        balances: dict[str, float] = {m.uuid: 0.0 for m in tricount.members}

        for tx in tricount.transactions:
            # Include both NORMAL expenses and BALANCE (reimbursement/settlement) entries.
            # BALANCE entries use the same payer-credit / allocation-debit formula:
            #   membership_owned = the payer (person sending money)
            #   allocations = the recipient (negative amount) + payer (0.00)
            # Ignoring BALANCE entries leaves out all inter-member settlements, causing
            # balances to be off by thousands when most of the total has been settled.
            if tx.tx_type not in ("NORMAL", "BALANCE") or tx.status != "ACTIVE":
                continue

            payer = tx.payer_uuid
            if payer in balances:
                balances[payer] += tx.amount.abs_float

            for alloc in tx.allocations:
                m_uuid = alloc.membership_uuid
                if m_uuid in balances:
                    balances[m_uuid] -= alloc.amount.abs_float

        return [
            {
                "member": member_by_uuid[u].display_name if u in member_by_uuid else u,
                "uuid": u,
                "balance": round(v, 2),
                "currency": tricount.currency,
            }
            for u, v in balances.items()
        ]

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_registry(self, data: dict) -> Tricount:
        members = [self._parse_member(m) for m in data.get("memberships", [])]
        transactions = [self._parse_entry(e) for e in data.get("all_registry_entry", [])]
        return Tricount(
            id=data.get("id", 0),
            uuid=data.get("uuid", ""),
            title=data.get("title", ""),
            currency=data.get("currency", ""),
            status=data.get("status", ""),
            public_identifier_token=data.get("public_identifier_token", ""),
            members=members,
            transactions=transactions,
        )

    @staticmethod
    def _unwrap_membership(raw: dict) -> dict:
        """Unwrap the typed membership envelope.

        The API wraps members as:
          { "RegistryMembershipNonUser": { ... } }
        or
          { "RegistryMembershipUser": { ... } }
        This returns the inner dict regardless of wrapper key.
        """
        for key in ("RegistryMembershipNonUser", "RegistryMembershipUser"):
            if key in raw:
                return raw[key]
        # Already unwrapped (flat dict)
        return raw

    def _parse_member(self, raw: dict) -> Member:
        data = self._unwrap_membership(raw)
        alias = data.get("alias", {})
        return Member(
            id=data.get("id", 0),
            uuid=data.get("uuid", ""),
            display_name=alias.get("display_name", data.get("uuid", "")),
            status=data.get("status", "ACTIVE"),
        )

    def _parse_entry(self, raw: dict) -> Transaction:
        # Entries may be wrapped as { "RegistryEntry": { ... } }
        data = raw.get("RegistryEntry", raw)

        raw_amt = data.get("amount", {})

        # Payer is in membership_owned envelope
        payer_uuid = ""
        membership_owned = data.get("membership_owned", {})
        if membership_owned:
            payer_data = self._unwrap_membership(membership_owned)
            payer_uuid = payer_data.get("uuid", "")

        allocations = []
        for a in data.get("allocations", []):
            m_uuid = ""
            membership_raw = a.get("membership", {})
            if membership_raw:
                m_data = self._unwrap_membership(membership_raw)
                m_uuid = m_data.get("uuid", "")
            allocations.append(
                Allocation(
                    membership_uuid=m_uuid,
                    amount=Amount(
                        value=a.get("amount", {}).get("value", "0"),
                        currency=a.get("amount", {}).get("currency", ""),
                    ),
                    alloc_type=a.get("type", "AMOUNT"),
                )
            )

        return Transaction(
            id=data.get("id", 0),
            uuid=data.get("uuid", ""),
            description=data.get("description", ""),
            amount=Amount(
                value=raw_amt.get("value", "0"),
                currency=raw_amt.get("currency", ""),
            ),
            payer_uuid=payer_uuid,
            allocations=allocations,
            date=data.get("date", ""),
            tx_type=data.get("type_transaction", "NORMAL"),
            status=data.get("status", "ACTIVE"),
        )
