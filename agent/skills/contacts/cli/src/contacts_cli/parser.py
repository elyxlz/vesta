"""vCard (.vcf) parsing using the vobject library."""

from dataclasses import dataclass, field
from pathlib import Path

import vobject


@dataclass
class ParsedContact:
    """A parsed contact from a vCard."""

    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    organization: str = ""
    title: str = ""
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    notes: str = ""
    raw_vcf: str = ""


def _safe_str(value) -> str:
    """Safely convert a vobject value to string."""
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _parse_single_vcard(vcard) -> ParsedContact:
    """Parse a single vCard object into a ParsedContact."""
    contact = ParsedContact()

    # Raw vCard text
    try:
        contact.raw_vcf = vcard.serialize()
    except Exception:
        contact.raw_vcf = ""

    # FN (formatted name) — the display name
    if hasattr(vcard, "fn"):
        contact.full_name = _safe_str(vcard.fn.value)

    # N (structured name)
    if hasattr(vcard, "n"):
        n = vcard.n.value
        contact.first_name = _safe_str(getattr(n, "given", ""))
        contact.last_name = _safe_str(getattr(n, "family", ""))
        # If no FN, construct from N
        if not contact.full_name:
            parts = [contact.first_name, contact.last_name]
            contact.full_name = " ".join(p for p in parts if p)

    # If still no name, use email or phone as fallback
    if not contact.full_name:
        contact.full_name = "(unnamed)"

    # TEL (phone numbers)
    if hasattr(vcard, "tel_list"):
        for tel in vcard.tel_list:
            phone = _safe_str(tel.value)
            if phone:
                contact.phones.append(phone)

    # EMAIL
    if hasattr(vcard, "email_list"):
        for email in vcard.email_list:
            addr = _safe_str(email.value)
            if addr:
                contact.emails.append(addr)

    # ADR (addresses)
    if hasattr(vcard, "adr_list"):
        for adr in vcard.adr_list:
            try:
                a = adr.value
                parts = []
                for component in [
                    getattr(a, "street", ""),
                    getattr(a, "city", ""),
                    getattr(a, "region", ""),
                    getattr(a, "code", ""),
                    getattr(a, "country", ""),
                ]:
                    s = _safe_str(component)
                    if s:
                        parts.append(s)
                if parts:
                    contact.addresses.append(", ".join(parts))
            except Exception:
                continue

    # ORG
    if hasattr(vcard, "org"):
        org_value = vcard.org.value
        if isinstance(org_value, list):
            contact.organization = " ".join(_safe_str(o) for o in org_value if _safe_str(o))
        else:
            contact.organization = _safe_str(org_value)

    # TITLE
    if hasattr(vcard, "title"):
        contact.title = _safe_str(vcard.title.value)

    # NOTE
    if hasattr(vcard, "note"):
        contact.notes = _safe_str(vcard.note.value)

    return contact


def parse_vcf_file(filepath: str | Path) -> list[ParsedContact]:
    """Parse a .vcf file that may contain one or more vCards.

    Returns a list of ParsedContact objects.
    Raises FileNotFoundError if the file doesn't exist.
    Raises ValueError if the file cannot be parsed.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"File is empty: {filepath}")

    contacts = []
    try:
        for vcard in vobject.readComponents(text):
            try:
                parsed = _parse_single_vcard(vcard)
                contacts.append(parsed)
            except Exception:
                # Skip individual cards that fail to parse but continue
                continue
    except Exception as e:
        raise ValueError(f"Failed to parse vCard file: {e}")

    return contacts


def contact_to_vcf(contact: dict) -> str:
    """Convert a contact dict back to vCard format."""
    vcard = vobject.vCard()

    # FN
    fn = vcard.add("fn")
    fn.value = contact.get("full_name", "")

    # N
    n = vcard.add("n")
    n.value = vobject.vcard.Name(
        family=contact.get("last_name", ""),
        given=contact.get("first_name", ""),
    )

    # TEL
    phones = contact.get("phones", [])
    if isinstance(phones, str):
        import json

        phones = json.loads(phones)
    for phone in phones:
        tel = vcard.add("tel")
        tel.value = phone

    # EMAIL
    emails = contact.get("emails", [])
    if isinstance(emails, str):
        import json

        emails = json.loads(emails)
    for email in emails:
        e = vcard.add("email")
        e.value = email

    # ORG
    org = contact.get("organization", "")
    if org:
        o = vcard.add("org")
        o.value = [org]

    # TITLE
    title = contact.get("title", "")
    if title:
        t = vcard.add("title")
        t.value = title

    # NOTE
    notes = contact.get("notes", "")
    if notes:
        note = vcard.add("note")
        note.value = notes

    # ADR
    addresses = contact.get("addresses", [])
    if isinstance(addresses, str):
        import json

        addresses = json.loads(addresses)
    for addr_str in addresses:
        adr = vcard.add("adr")
        # Store as street component since we flattened it
        adr.value = vobject.vcard.Address(street=addr_str)

    return vcard.serialize()
