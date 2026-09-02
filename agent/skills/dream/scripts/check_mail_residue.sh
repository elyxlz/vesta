#!/usr/bin/env bash
# Lists files outside the mail stores that hold mailbox content, so a disconnected account's mail
# is not left behind in a scratch file: a file carrying mail-API field names or Exchange item ids,
# or one naming ADDR_DENSITY or more distinct addresses (a roster, not prose). Scans ~/agent,
# ~/downloads and the temp dir ($TMPDIR, else /tmp), or the directories given as arguments. Code
# files are skipped (a program that names a field is the tool, not the data), and so is the events
# database, the agent's own record, which redact_secrets.sh covers. Exit 1 with one path per line
# on a hit, exit 0 and silent otherwise.
set -uo pipefail

FIELD_MARKERS='"(bodyPreview|receivedDateTime|toRecipients|ccRecipients|internetMessageId|conversationId)"|AAMkAD[A-Za-z0-9+/=_-]{40,}'
ADDRESS='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
ADDR_DENSITY=25
LIST_MATCHING_FILES=(grep -rlaZE --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__
    --exclude='*.py' --exclude='*.sh' --exclude='*.go' --exclude='*.ts' --exclude='*.js' --exclude='events.db*')

roots=("$@")
[ "$#" -eq 0 ] && roots=("$HOME/agent" "$HOME/downloads" "${TMPDIR:-/tmp}")
existing=()
for root in "${roots[@]}"; do
    [ -d "$root" ] && existing+=("$root")
done
[ "${#existing[@]}" -eq 0 ] && exit 0

hits=()
while IFS= read -r -d '' file; do
    hits+=("$file")
done < <("${LIST_MATCHING_FILES[@]}" "$FIELD_MARKERS" "${existing[@]}" 2>/dev/null)
while IFS= read -r -d '' file; do
    distinct=$(grep -aoE "$ADDRESS" "$file" 2>/dev/null | sort -uf | wc -l)
    [ "$distinct" -ge "$ADDR_DENSITY" ] && hits+=("$file")
done < <("${LIST_MATCHING_FILES[@]}" "$ADDRESS" "${existing[@]}" 2>/dev/null)

[ "${#hits[@]}" -eq 0 ] && exit 0
printf '%s\n' "${hits[@]}" | sort -u
exit 1
