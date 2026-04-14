#!/bin/sh
# Scan events DB for secrets. Usage: redact_secrets.sh [--delete]
DB="$HOME/vesta/data/events.db"
[ ! -f "$DB" ] && echo "No database at $DB" && exit 1

REGEX='sk-[a-zA-Z0-9_-]{20,}|xox[bp]-[0-9A-Za-z-]+|gh[po]_[A-Za-z0-9]{36,}|glpat-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|BEGIN [A-Z ]+ PRIVATE KEY|(password|secret|api[_-]?key)[\"'"'"': =]+[^ "'"'"']{4,}|(mongodb(\+srv)?|postgres(ql)?|mysql|redis)://[^ "'"'"']+'

MATCHES=$(sqlite3 "$DB" "SELECT id, substr(data, 1, 200) FROM events;" | grep -E "$REGEX")
[ -z "$MATCHES" ] && echo "No secrets found." && exit 0

IDS=$(echo "$MATCHES" | cut -d'|' -f1 | sort -un)
COUNT=$(echo "$IDS" | wc -l | tr -d ' ')
echo "Found $COUNT events with potential secrets:"
echo "$MATCHES" | head -20

if [ "$1" = "--delete" ]; then
    sqlite3 "$DB" "DELETE FROM events WHERE id IN ($(echo "$IDS" | paste -sd','));"
    echo "Deleted $COUNT events."
fi
