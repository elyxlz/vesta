#!/usr/bin/env bash
set -euo pipefail

CURRENT=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)

if [ $# -eq 0 ]; then
  IFS='.' read -r major minor patch <<< "$CURRENT"
  NEW="${major}.${minor}.$((patch + 1))"
elif [ $# -eq 1 ]; then
  NEW="$1"
else
  echo "Usage: ./bump.sh [version]"
  echo "  No args: bump patch (${CURRENT} -> next)"
  echo "  With arg: set exact version"
  exit 1
fi

echo "${CURRENT} -> ${NEW}"

# agent/pyproject.toml
sed -i "s/^version = \"${CURRENT}\"/version = \"${NEW}\"/" agent/pyproject.toml

# cli/Cargo.toml (first occurrence)
sed -i "0,/^version = \"${CURRENT}\"/s//version = \"${NEW}\"/" cli/Cargo.toml

# app/src-tauri/Cargo.toml (first occurrence)
sed -i "0,/^version = \"${CURRENT}\"/s//version = \"${NEW}\"/" app/src-tauri/Cargo.toml

# app/src-tauri/tauri.conf.json
sed -i "s/\"version\": \"${CURRENT}\"/\"version\": \"${NEW}\"/" app/src-tauri/tauri.conf.json

# app/package.json
sed -i "s/\"version\": \"${CURRENT}\"/\"version\": \"${NEW}\"/" app/package.json

# Update Cargo.lock files
(cd cli && cargo check --quiet 2>/dev/null) || true
(cd app/src-tauri && cargo check --quiet 2>/dev/null) || true

# Update uv.lock
(cd agent && uv lock --quiet 2>/dev/null) || true

echo "Bumped to ${NEW}"
