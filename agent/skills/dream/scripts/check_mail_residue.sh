#!/usr/bin/env bash
# check_mail_residue.sh [--quiet] [domain ...]
#
# Answers one question: is there mailbox content sitting in a file the AGENT wrote, outside the
# stores meant to hold it? Run it before ever telling anyone that a mailbox is disconnected,
# removed, purged or gone. Pass the domain of any account that has been disconnected, e.g.
#
#   check_mail_residue.sh example.org
#
# WHY THIS EXISTS
# An agent was told to disconnect from a work mailbox. It removed the auth cache, the browser
# profiles, the notification rules, and confirmed the account was gone from the mail skill's
# account list. Every one of those checks came back clean, and the next morning it reported the
# mail "all removed and verified gone". That was false for three days: thousands of messages sat in
# JSON the agent had written by hand during the session, in a scratch directory, and were found by
# accident in an unrelated diff.
#
# The generalisable failure is not the missed directory. A skill's store has a name the agent
# remembers, so it gets checked. A scratch file written in a hurry has no name and belongs to no
# subsystem, so it is invisible to every check the agent would think to run. The only defence is a
# check that enumerates by CONTENT and does not depend on what the agent remembers doing.
#
# HOW IT DECIDES, tuned deliberately not to cry wolf:
#   1. DUMP MARKERS: mail API field names (bodyPreview, receivedDateTime, toRecipients,
#      internetMessageId, conversationId). These appear in machine-written mailbox data and
#      essentially never in prose. Source files are skipped, since code that mentions a field name
#      is the tool and not the data.
#   2. PROVIDER ITEM IDS: an Exchange/Graph item id survives every export format, so this catches a
#      TSV or plain-text dump that carries no JSON keys at all. The first version of this script
#      missed exactly such a file because it had been taught JSON; match the data, not the format.
#   3. ADDRESS DENSITY: a file naming many DISTINCT addresses is an index of a mailbox, not prose
#      about one. Notes legitimately name one or two addresses, so a disconnected-domain hit is
#      only reported as removable at three or more, and one-or-two hits are listed separately
#      rather than hidden.
#
# WHAT IT WILL NOT DO
# It never claims the box is clean. It prints the roots it scanned and the paths it pruned, because
# a null here means "these roots had no hits", never "there is none". That distinction is the whole
# reason the original claim was false: it was true about what was looked at.
#
# It also refuses to report clean without a POSITIVE CONTROL. It plants a synthetic file carrying
# every marker and requires the scan to find it; if the control does not fire, the scanner is broken
# and a clean result would be a lie, so it exits 2. An empty result is unverified, not evidence.
#
# Logs and conversation transcripts are reported but never treated as removable. Deleting the
# agent's own record to make a check go green is destroying evidence to protect a claim, and it is
# also why "gone" is usually not an achievable promise: say disconnected, no residual access,
# working copies removed.
#
# Exit 0 = control passed and nothing removable found.  1 = residue found.  2 = control failed.

set -uo pipefail

QUIET=0
DOMAINS=()
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) DOMAINS+=("$(printf '%s' "$arg" | sed 's/\./\\./g')") ;;
  esac
done

SELF="$(readlink -f "$0")"
SELF_BASE="$(basename "$SELF")"

DOMAIN_RE=""
if [ "${#DOMAINS[@]}" -gt 0 ]; then
  DOMAIN_RE="$(IFS='|'; printf '%s' "${DOMAINS[*]}")"
fi

DUMP_MARKERS='bodyPreview|receivedDateTime|toRecipients|internetMessageId|conversationId|ccRecipients'
PROVIDER_ID='AAMkAD[A-Za-z0-9+/=_-]{40,}'
ADDR_DENSITY=25

ROOTS=("$HOME/agent" "$HOME/.contacts" "$HOME/downloads" "/tmp" "$HOME/.claude")

# Reported but never removable: the agent's own operational record. The event database belongs here
# too, and testing this script is how that surfaced: reading a mailbox puts message fields into the
# events write-ahead log within the hour, so events.db* will legitimately match. Deleting it is not
# an option, and hiding it would be worse, so it is shown under the inherent heading with the rest.
INHERENT='(^'"$HOME"'/agent/logs/|^'"$HOME"'/\.claude/|^'"$HOME"'/agent/data/events\.db)'

# Code that mentions a mail field name is the tool, not the data.
CODE_EXT='\.(py|go|rs|ts|tsx|js|jsx|java|rb|c|h|cpp|sh)$'

PRUNE_NAMES=(.git node_modules .venv __pycache__ .cache .npm .cargo go target dist build)

# Outside ROOTS, so genuinely not looked at. Skill stores are supposed to hold mail; this script is
# about copies the agent made elsewhere. Anything under $HOME/agent is scanned even if it is a
# store, so it is deliberately not listed here.
SANCTIONED=("$HOME/.microsoft" "$HOME/.whatsapp" "$HOME/.email-client" "$HOME/.google")

build_find() {
  local root="$1"
  local args=(find "$root" -type d \()
  local first=1
  for n in "${PRUNE_NAMES[@]}"; do
    [ $first -eq 1 ] && first=0 || args+=(-o)
    args+=(-name "$n")
  done
  args+=(\) -prune -o -type f -size -20M -print0)
  "${args[@]}" 2>/dev/null
}

scan() {
  local root f cls dumps ids anyaddr addrs
  for root in "${ROOTS[@]}"; do
    [ -e "$root" ] || continue
    while IFS= read -r -d '' f; do
      [ "$(readlink -f "$f")" = "$SELF" ] && continue
      case "$f" in *"$SELF_BASE"*) continue ;; esac
      cls=''
      [[ "$f" =~ $INHERENT ]] && cls='INHERENT'

      # Source files are skipped for EVERY marker, not just the JSON one. A script that documents
      # these markers, or carries example addresses in a test fixture, is the tool and not the data;
      # the first version gated only the dump check and duly reported itself as residue.
      if ! [[ "$f" =~ $CODE_EXT ]]; then
        if [ -n "$DOMAIN_RE" ]; then
          addrs=$(grep -oiE "[A-Za-z0-9._%+-]+@($DOMAIN_RE)" "$f" 2>/dev/null | sort -u | wc -l)
          [ "${addrs:-0}" -gt 0 ] && printf '%s\t%s\t%s\n' "${cls:-ADDR}" "$addrs" "$f"
        fi

        dumps=$(grep -cE "\"($DUMP_MARKERS)\"" "$f" 2>/dev/null) || dumps=0
        [ "${dumps:-0}" -gt 0 ] && printf '%s\t%s\t%s\n' "${cls:-DUMP}" "$dumps" "$f"
        ids=$(grep -coE "$PROVIDER_ID" "$f" 2>/dev/null) || ids=0
        [ "${ids:-0}" -gt 0 ] && printf '%s\t%s\t%s\n' "${cls:-DUMP}" "$ids" "$f"
        anyaddr=$(grep -oiE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" "$f" 2>/dev/null | sort -u | wc -l)
        [ "${anyaddr:-0}" -ge "$ADDR_DENSITY" ] && printf '%s\t%s\t%s\n' "${cls:-DUMP}" "$anyaddr" "$f"
      fi
    done < <(build_find "$root")
  done
}

# Positive control. It exercises every marker, because a control that only proved the JSON path
# would have passed happily on the version that could not see a tab-separated dump.
#
# Sweep control files left behind by a run that died before its trap fired. Removal needs BOTH
# proofs, a dead owner AND the synthetic marker inside, because a file this script cannot prove
# it wrote is exactly the kind of thing it exists to show you. Anything else is left and reported.
for stale in "$HOME"/agent/.mail-residue-control.*.json; do
  [ -e "$stale" ] || continue
  spid=${stale##*.mail-residue-control.}; spid=${spid%.json}
  case "$spid" in ''|*[!0-9]*) continue ;; esac
  kill -0 "$spid" 2>/dev/null && continue
  grep -q '"bodyPreview":"synthetic"' "$stale" 2>/dev/null || continue
  rm -f "$stale"
  echo "check_mail_residue: removed a control file left by dead run $spid." >&2
done

CTRL="$HOME/agent/.mail-residue-control.$$.json"
trap 'rm -f "$CTRL"' EXIT INT TERM
CTRL_DOMAIN="control-probe.invalid"
[ -n "$DOMAIN_RE" ] && CTRL_DOMAIN="$(printf '%s' "${DOMAINS[0]}" | sed 's/\\//g')"
{
  echo '[{"subject":"control","bodyPreview":"synthetic","receivedDateTime":"2026-01-01T00:00:00Z",'
  echo "  \"toRecipients\":[{\"emailAddress\":{\"address\":\"control.one@$CTRL_DOMAIN\"}}],"
  echo "  \"ccRecipients\":[{\"emailAddress\":{\"address\":\"control.two@$CTRL_DOMAIN\"}}],"
  echo "  \"from\":{\"emailAddress\":{\"address\":\"control.three@$CTRL_DOMAIN\"}},"
  echo '  "conversationId":"x","internetMessageId":"y",'
  echo '  "id":"AAMkADcontrolcontrolcontrolcontrolcontrolcontrolcontrol0123456789="}]'
  for i in $(seq 1 "$ADDR_DENSITY"); do echo "control.addr$i@control-$i.example"; done
} > "$CTRL"

RAW="$(scan)"
rm -f "$CTRL"

cb="$(basename "$CTRL")"
ctrl_lines=$(printf '%s\n' "$RAW" | awk -F'\t' -v b="$cb" '$1=="DUMP" && index($3,b)' | wc -l)
if [ "$ctrl_lines" -lt 3 ]; then
  echo "check_mail_residue: POSITIVE CONTROL FAILED (matched $ctrl_lines markers, want >=3)." >&2
  echo "  The scanner missed a file handed to it on a plate, so a clean result would be a lie." >&2
  echo "  Fix the scanner before believing anything about mail residue." >&2
  exit 2
fi

# Drop EVERY control file, not just this run's. Filtering only "$cb" meant a control planted by a
# CONCURRENT run of this same script was indistinguishable from real mailbox residue, so the alarm
# that exists to prevent a false "the mail is gone" claim cried wolf at its own litter. This scan is
# slow enough (minutes) to outlive a tool timeout, which is how two runs come to overlap at all.
FOUND="$(printf '%s\n' "$RAW" | grep -vE '\.mail-residue-control\.[0-9]+\.json' | grep -v '^$')"

dump_hits=$(printf '%s\n' "$FOUND" | awk -F'\t' '$1=="DUMP"' | grep -c .)
addr_real=$(printf '%s\n' "$FOUND" | awk -F'\t' '$1=="ADDR" && $2>=3' | grep -c .)
addr_prose=$(printf '%s\n' "$FOUND" | awk -F'\t' '$1=="ADDR" && $2<3' | grep -c .)
inherent=$(printf '%s\n' "$FOUND" | awk -F'\t' '$1=="INHERENT"' | grep -c .)

report_inherent() {
  [ "$inherent" -eq 0 ] && return
  echo "  ---"
  echo "  $inherent file(s) in the logs and conversation transcripts also carry this content."
  echo "  NOT removable and NOT removed: that is the record of what the agent did and read, and"
  echo "  deleting it to make this check go green would be destroying evidence to protect a claim."
  echo "  This is also why 'gone' is rarely an achievable claim. Say: disconnected, no residual"
  echo "  access, working copies removed."
  printf '%s\n' "$FOUND" | awk -F'\t' '$1=="INHERENT"{printf "    %s (%s)\n", $3, $2}' | head -12
}

if [ "$dump_hits" -eq 0 ] && [ "$addr_real" -eq 0 ]; then
  if [ "$QUIET" -eq 0 ]; then
    echo "check_mail_residue: control PASSED, no removable dumps outside the sanctioned stores."
    printf '  scanned: %s\n' "${ROOTS[*]}"
    printf '  pruned : %s\n' "${PRUNE_NAMES[*]}"
    printf '  NOT scanned (skill stores, content there is expected): %s\n' "${SANCTIONED[*]}"
    echo "  Git history and any completed backups are NOT scanned either: deleting a file today"
    echo "  does not remove it from a commit or from a backup already taken."
    if [ "$addr_prose" -gt 0 ]; then
      echo "  $addr_prose file(s) name one or two addresses at a named domain (prose, expected):"
      printf '%s\n' "$FOUND" | awk -F'\t' '$1=="ADDR" && $2<3 {printf "    %s (%s)\n", $3, $2}' | head -20
    fi
    report_inherent
  fi
  exit 0
fi

echo "check_mail_residue: RESIDUE FOUND, in files the agent wrote."
printf '%s\n' "$FOUND" | awk -F'\t' '$1=="DUMP" {printf "  DUMP  %5s marker(s)  %s\n", $2, $3}'
printf '%s\n' "$FOUND" | awk -F'\t' '$1=="ADDR" && $2>=3 {printf "  ADDR  %5s distinct address(es)  %s\n", $2, $3}'
report_inherent
echo "  Read each file before deleting it: know what it is, then correct anyone told otherwise."
exit 1
