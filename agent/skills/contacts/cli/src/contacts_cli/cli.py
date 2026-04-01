"""Contacts CLI — import, lookup, search, and manage contacts from vCard files."""

import argparse
import json
import sys
from contextlib import closing
from pathlib import Path

from . import db
from .parser import parse_vcf_file, contact_to_vcf


def main():
    parser = argparse.ArgumentParser(prog="contacts", description="Contact management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # import
    p_import = sub.add_parser("import", help="Import contacts from a .vcf file")
    p_import.add_argument("file", help="Path to .vcf file")

    # lookup
    p_lookup = sub.add_parser("lookup", help="Look up a contact by name, phone, email, or org")
    p_lookup.add_argument("query", help="Name, phone number, email, or organization to search for")

    # list
    p_list = sub.add_parser("list", help="List all contacts")
    p_list.add_argument("--limit", type=int, default=50, help="Maximum number of contacts to show (default: 50)")

    # search
    p_search = sub.add_parser("search", help="Full-text search across all fields")
    p_search.add_argument("term", help="Search term")

    # get
    p_get = sub.add_parser("get", help="Get full details for a contact")
    p_get.add_argument("id", type=int, help="Contact ID")

    # delete
    p_delete = sub.add_parser("delete", help="Delete a contact")
    p_delete.add_argument("id", type=int, help="Contact ID")

    # count
    sub.add_parser("count", help="Show total number of contacts")

    # export
    sub.add_parser("export", help="Export all contacts as .vcf to stdout")

    args = parser.parse_args()

    # Initialize database
    db.init_db()

    try:
        result = _dispatch(args)
        if isinstance(result, str):
            # Raw output (e.g., VCF export)
            print(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Unexpected error: {e}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def _dispatch(args):
    if args.command == "import":
        return _cmd_import(args.file)
    elif args.command == "lookup":
        return _cmd_lookup(args.query)
    elif args.command == "list":
        return _cmd_list(args.limit)
    elif args.command == "search":
        return _cmd_search(args.term)
    elif args.command == "get":
        return _cmd_get(args.id)
    elif args.command == "delete":
        return _cmd_delete(args.id)
    elif args.command == "count":
        return _cmd_count()
    elif args.command == "export":
        return _cmd_export()


def _cmd_import(filepath: str) -> dict:
    """Import contacts from a .vcf file."""
    path = Path(filepath).expanduser().resolve()
    parsed = parse_vcf_file(path)

    if not parsed:
        return {"imported": 0, "updated": 0, "message": "No contacts found in file"}

    imported = 0
    updated = 0

    with closing(db.get_db()) as conn:
        for contact in parsed:
            _, was_update = db.upsert_contact(
                conn,
                full_name=contact.full_name,
                first_name=contact.first_name,
                last_name=contact.last_name,
                organization=contact.organization,
                title=contact.title,
                phones=contact.phones,
                emails=contact.emails,
                addresses=contact.addresses,
                notes=contact.notes,
                raw_vcf=contact.raw_vcf,
            )
            if was_update:
                updated += 1
            else:
                imported += 1

    return {
        "imported": imported,
        "updated": updated,
        "total_processed": len(parsed),
        "message": f"Imported {imported} new, updated {updated} existing contacts",
    }


def _cmd_lookup(query: str) -> dict:
    """Look up contacts by name, phone, email, or organization."""
    with closing(db.get_db()) as conn:
        results = db.lookup_contact(conn, query)

    if not results:
        return {"results": [], "count": 0, "message": f"No contacts found for '{query}'"}

    compact = []
    for c in results:
        compact.append(
            {
                "id": c["id"],
                "name": c["full_name"],
                "phones": c.get("phones", []),
                "emails": c.get("emails", []),
                "organization": c.get("organization") or None,
            }
        )

    return {"results": compact, "count": len(compact)}


def _cmd_list(limit: int) -> dict:
    """List all contacts in compact format."""
    with closing(db.get_db()) as conn:
        contacts = db.list_contacts(conn, limit=limit)
        total = db.count_contacts(conn)

    return {
        "contacts": contacts,
        "showing": len(contacts),
        "total": total,
    }


def _cmd_search(term: str) -> dict:
    """Full-text search across all fields."""
    with closing(db.get_db()) as conn:
        results = db.search_contacts(conn, term)

    compact = []
    for c in results:
        compact.append(
            {
                "id": c["id"],
                "name": c["full_name"],
                "phones": c.get("phones", []),
                "emails": c.get("emails", []),
                "organization": c.get("organization") or None,
            }
        )

    return {"results": compact, "count": len(compact)}


def _cmd_get(contact_id: int) -> dict:
    """Get full details for a contact."""
    with closing(db.get_db()) as conn:
        contact = db.get_contact(conn, contact_id)

    if not contact:
        raise ValueError(f"Contact with ID {contact_id} not found")

    # Remove raw_vcf from default output to keep it clean
    result = {k: v for k, v in contact.items() if k != "raw_vcf"}
    return result


def _cmd_delete(contact_id: int) -> dict:
    """Delete a contact by ID."""
    with closing(db.get_db()) as conn:
        deleted = db.delete_contact(conn, contact_id)

    if not deleted:
        raise ValueError(f"Contact with ID {contact_id} not found")

    return {"deleted": True, "id": contact_id}


def _cmd_count() -> dict:
    """Return total number of contacts."""
    with closing(db.get_db()) as conn:
        total = db.count_contacts(conn)

    return {"count": total}


def _cmd_export() -> str:
    """Export all contacts as .vcf."""
    with closing(db.get_db()) as conn:
        contacts = db.get_all_contacts(conn)

    if not contacts:
        return ""

    vcf_parts = []
    for contact in contacts:
        try:
            vcf_parts.append(contact_to_vcf(contact))
        except Exception:
            # Skip contacts that fail to serialize
            continue

    return "".join(vcf_parts)


if __name__ == "__main__":
    main()
