#!/usr/bin/env bash
# Open PRs by the vesta-upstream App with their touched files, grouped so PRs sharing a file
# print in one cluster. Usage: clusters.sh [author] (default app/vesta-upstream).
set -euo pipefail

author="${1:-app/vesta-upstream}"
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

gh pr list --state open --author "$author" --limit 200 --json number,title,mergeable \
  --jq '.[] | "\(.number)\t\(.mergeable)\t\(.title)"' | sort -n | while IFS=$'\t' read -r number mergeable title; do
  files="$(gh api "repos/$repo/pulls/$number/files" --paginate --jq '.[].filename' | sort | tr '\n' ' ')"
  printf '%s\t%s\t%s\t%s\n' "$number" "$mergeable" "$title" "$files"
done | awk -F'\t' '
  {
    pr[NR] = $1; title[NR] = $3; mergeable[NR] = $2; files[NR] = $4
    n = split($4, list, " ")
    for (i = 1; i <= n; i++) if (list[i] != "") owner[list[i]] = owner[list[i]] " " $1
  }
  END {
    # Union-find by shared file: two PRs are one cluster when any file is in both.
    for (r = 1; r <= NR; r++) parent[pr[r]] = pr[r]
    for (f in owner) {
      split(owner[f], members, " ")
      first = ""
      for (i in members) {
        if (members[i] == "") continue
        if (first == "") { first = members[i]; continue }
        a = find(first); b = find(members[i]); if (a != b) parent[b] = a
      }
    }
    for (r = 1; r <= NR; r++) { root = find(pr[r]); group[root] = group[root] SUBSEP r }
    for (root in group) {
      split(group[root], rows, SUBSEP)
      count = 0; for (i in rows) if (rows[i] != "") count++
      printf "== cluster (%d PR%s)\n", count, (count == 1 ? "" : "s")
      for (i in rows) {
        if (rows[i] == "") continue
        r = rows[i]
        printf "  #%s  %s  %s\n      %s\n", pr[r], mergeable[r], title[r], files[r]
      }
    }
  }
  function find(x) { while (parent[x] != x) x = parent[x]; return x }
'
