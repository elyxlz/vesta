---
name: contacts
description: This skill should be used when the user asks about "contacts", "contact", "who is", "phone number", "email address", "vcard", "vcf", "address book", or needs to look up, import, or manage contacts. Also use when encountering an unknown phone number or name that might be in the address book. No daemon required — queries local SQLite database on demand.
---

# Contacts — CLI: contacts

## Quick Reference
```bash
contacts import ~/contacts.vcf        # import vCard file (single or multi-contact)
contacts lookup "Mario Rossi"          # search by name
contacts lookup "+39 333 1234567"      # search by phone number
contacts lookup "mario@example.com"    # search by email
contacts search "Milano"              # full-text search across all fields
contacts list                          # list all contacts (default limit 50)
contacts list --limit 100              # list with custom limit
contacts get <id>                      # full details for a contact
contacts delete <id>                   # delete a contact
contacts count                         # total number of contacts
contacts export                        # export all as .vcf to stdout
```

## Commands

### Import
- `contacts import <file>` — import a .vcf file containing one or more vCards
  - Reports count of imported/updated contacts
  - Handles duplicates by updating existing records (matches on phone or email)

### Lookup
- `contacts lookup <query>` — smart search by name, phone, email, or organization
  - Phone numbers are normalized before matching (strips spaces, dashes, handles +39/0039 prefixes)
  - Returns compact results with name, phones, and emails

### Search
- `contacts search <term>` — full-text search across all fields (name, org, phones, emails, addresses, notes)

### List / Get / Delete
- `contacts list` — all contacts, compact format. `--limit N` to control count (default 50)
- `contacts get <id>` — full contact details including all fields
- `contacts delete <id>` — remove a contact by ID

### Export
- `contacts export` — dump all contacts as valid .vcf to stdout

### Count
- `contacts count` — total contacts in database

## Setup
```bash
uv tool install ~/vesta/skills/contacts/cli
```

## Patterns
- When WhatsApp or other messaging mentions an unknown number, use `contacts lookup` to identify the person
- When someone says "call Mario" or "email the accountant", look up the contact first
- Phone numbers from Italy often come as +39 XXX XXXXXXX or 0039 XXX XXXXXXX — normalization handles both
