"""SQLite database setup and queries for contacts."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from .normalize import normalize_phone, phone_variants, looks_like_phone

DATA_DIR = Path.home() / "vesta" / "skills" / "contacts" / "data"


def get_db(data_dir: Path | None = None) -> sqlite3.Connection:
    """Get a database connection."""
    d = data_dir or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(d / "contacts.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(data_dir: Path | None = None):
    """Initialize the database schema and FTS5 table."""
    with closing(get_db(data_dir)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                organization TEXT DEFAULT '',
                title TEXT DEFAULT '',
                phones TEXT DEFAULT '[]',
                phones_normalized TEXT DEFAULT '[]',
                emails TEXT DEFAULT '[]',
                addresses TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                raw_vcf TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # FTS5 virtual table for full-text search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
                full_name,
                organization,
                phones,
                emails,
                addresses,
                notes,
                content='contacts',
                content_rowid='id',
                tokenize='unicode61'
            )
        """)

        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS contacts_ai AFTER INSERT ON contacts BEGIN
                INSERT INTO contacts_fts(rowid, full_name, organization, phones, emails, addresses, notes)
                VALUES (new.id, new.full_name, new.organization, new.phones, new.emails, new.addresses, new.notes);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS contacts_ad AFTER DELETE ON contacts BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, full_name, organization, phones, emails, addresses, notes)
                VALUES ('delete', old.id, old.full_name, old.organization, old.phones, old.emails, old.addresses, old.notes);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS contacts_au AFTER UPDATE ON contacts BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, full_name, organization, phones, emails, addresses, notes)
                VALUES ('delete', old.id, old.full_name, old.organization, old.phones, old.emails, old.addresses, old.notes);
                INSERT INTO contacts_fts(rowid, full_name, organization, phones, emails, addresses, notes)
                VALUES (new.id, new.full_name, new.organization, new.phones, new.emails, new.addresses, new.notes);
            END
        """)

        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a database row to a dictionary with parsed JSON fields."""
    d = dict(row)
    for field in ("phones", "phones_normalized", "emails", "addresses"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d


def _compact_contact(contact: dict[str, Any]) -> dict[str, Any]:
    """Return a compact representation of a contact."""
    phones = contact.get("phones", [])
    emails = contact.get("emails", [])
    return {
        "id": contact["id"],
        "name": contact["full_name"],
        "phone": phones[0] if phones else None,
        "email": emails[0] if emails else None,
        "organization": contact.get("organization") or None,
    }


def upsert_contact(
    conn: sqlite3.Connection,
    full_name: str,
    first_name: str,
    last_name: str,
    organization: str,
    title: str,
    phones: list[str],
    emails: list[str],
    addresses: list[str],
    notes: str,
    raw_vcf: str,
) -> tuple[int, bool]:
    """Insert or update a contact. Returns (id, was_updated).

    Matches existing contacts by normalized phone number or email address.
    """
    now = datetime.now(UTC).isoformat()
    phones_normalized = [normalize_phone(p) for p in phones]
    emails_lower = [e.lower().strip() for e in emails if e.strip()]

    # Try to find existing contact by phone or email
    existing_id = None

    # Match by normalized phone
    for norm_phone in phones_normalized:
        if not norm_phone:
            continue
        for variant in phone_variants(norm_phone):
            cursor = conn.execute(
                "SELECT id, phones_normalized FROM contacts"
            )
            for row in cursor:
                stored_phones = json.loads(row["phones_normalized"]) if row["phones_normalized"] else []
                for sp in stored_phones:
                    if sp and variant == sp:
                        existing_id = row["id"]
                        break
                    # Also check variants of the stored phone
                    if sp and sp in phone_variants(variant):
                        existing_id = row["id"]
                        break
                if existing_id:
                    break
            if existing_id:
                break
        if existing_id:
            break

    # Match by email
    if not existing_id:
        for email in emails_lower:
            if not email:
                continue
            cursor = conn.execute("SELECT id, emails FROM contacts")
            for row in cursor:
                stored_emails = json.loads(row["emails"]) if row["emails"] else []
                stored_lower = [e.lower().strip() for e in stored_emails]
                if email in stored_lower:
                    existing_id = row["id"]
                    break
            if existing_id:
                break

    phones_json = json.dumps(phones)
    phones_norm_json = json.dumps(phones_normalized)
    emails_json = json.dumps(emails)
    addresses_json = json.dumps(addresses)

    if existing_id:
        conn.execute(
            """UPDATE contacts SET
                full_name = ?, first_name = ?, last_name = ?,
                organization = ?, title = ?,
                phones = ?, phones_normalized = ?,
                emails = ?, addresses = ?,
                notes = ?, raw_vcf = ?, updated_at = ?
            WHERE id = ?""",
            (
                full_name, first_name, last_name,
                organization, title,
                phones_json, phones_norm_json,
                emails_json, addresses_json,
                notes, raw_vcf, now,
                existing_id,
            ),
        )
        conn.commit()
        return existing_id, True

    cursor = conn.execute(
        """INSERT INTO contacts
            (full_name, first_name, last_name, organization, title,
             phones, phones_normalized, emails, addresses,
             notes, raw_vcf, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            full_name, first_name, last_name, organization, title,
            phones_json, phones_norm_json, emails_json, addresses_json,
            notes, raw_vcf, now, now,
        ),
    )
    conn.commit()
    return cursor.lastrowid, False


def lookup_contact(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    """Look up contacts by name, phone, email, or organization.

    For phone queries, normalizes and checks variants.
    For text queries, searches name, email, and organization.
    """
    results = []
    seen_ids = set()

    if looks_like_phone(query):
        norm = normalize_phone(query)
        variants = phone_variants(norm) if norm else []
        cursor = conn.execute("SELECT * FROM contacts")
        for row in cursor:
            contact = _row_to_dict(row)
            stored_normalized = contact.get("phones_normalized", [])
            for sp in stored_normalized:
                if not sp:
                    continue
                # Check if any variant of the query matches any variant of stored
                query_variants = set(variants)
                stored_variants = set(phone_variants(sp))
                if query_variants & stored_variants:
                    if contact["id"] not in seen_ids:
                        results.append(contact)
                        seen_ids.add(contact["id"])
                    break
    else:
        # Text search: name, email, org (case-insensitive)
        q = query.lower().strip()
        cursor = conn.execute("SELECT * FROM contacts")
        for row in cursor:
            contact = _row_to_dict(row)
            cid = contact["id"]
            if cid in seen_ids:
                continue

            # Check full name
            if q in contact.get("full_name", "").lower():
                results.append(contact)
                seen_ids.add(cid)
                continue

            # Check first/last name
            if q in contact.get("first_name", "").lower() or q in contact.get("last_name", "").lower():
                results.append(contact)
                seen_ids.add(cid)
                continue

            # Check organization
            if q in contact.get("organization", "").lower():
                results.append(contact)
                seen_ids.add(cid)
                continue

            # Check emails
            for email in contact.get("emails", []):
                if q in email.lower():
                    results.append(contact)
                    seen_ids.add(cid)
                    break

    return results


def search_contacts(conn: sqlite3.Connection, term: str) -> list[dict[str, Any]]:
    """Full-text search across all indexed fields."""
    # Escape FTS5 special characters and add prefix matching
    escaped = term.replace('"', '""')
    fts_query = f'"{escaped}"*'

    try:
        cursor = conn.execute(
            """SELECT c.* FROM contacts c
               JOIN contacts_fts fts ON c.id = fts.rowid
               WHERE contacts_fts MATCH ?
               ORDER BY rank""",
            (fts_query,),
        )
        return [_row_to_dict(row) for row in cursor]
    except sqlite3.OperationalError:
        # Fallback to LIKE search if FTS fails
        pattern = f"%{term}%"
        cursor = conn.execute(
            """SELECT * FROM contacts
               WHERE full_name LIKE ? OR organization LIKE ?
               OR phones LIKE ? OR emails LIKE ?
               OR addresses LIKE ? OR notes LIKE ?""",
            (pattern, pattern, pattern, pattern, pattern, pattern),
        )
        return [_row_to_dict(row) for row in cursor]


def list_contacts(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """List all contacts in compact format."""
    cursor = conn.execute(
        "SELECT * FROM contacts ORDER BY full_name ASC LIMIT ?",
        (limit,),
    )
    return [_compact_contact(_row_to_dict(row)) for row in cursor]


def get_contact(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any] | None:
    """Get full details for a contact by ID."""
    cursor = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    row = cursor.fetchone()
    if row:
        result = _row_to_dict(row)
        # Remove internal normalized field from output
        result.pop("phones_normalized", None)
        return result
    return None


def delete_contact(conn: sqlite3.Connection, contact_id: int) -> bool:
    """Delete a contact by ID. Returns True if deleted."""
    cursor = conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    conn.commit()
    return cursor.rowcount > 0


def count_contacts(conn: sqlite3.Connection) -> int:
    """Return total number of contacts."""
    cursor = conn.execute("SELECT COUNT(*) FROM contacts")
    return cursor.fetchone()[0]


def get_all_contacts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get all contacts with full details (for export)."""
    cursor = conn.execute("SELECT * FROM contacts ORDER BY full_name ASC")
    return [_row_to_dict(row) for row in cursor]
