#!/usr/bin/env bash
set -euo pipefail

CURRENT=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)
IFS='.' read -r major minor patch <<< "$CURRENT"

case "${1:-patch}" in
  patch) NEW="${major}.${minor}.$((patch + 1))" ;;
  minor) NEW="${major}.$((minor + 1)).0" ;;
  major) NEW="$((major + 1)).0.0" ;;
  *)
    echo "Usage: ./bump.sh [patch|minor|major]"
    exit 1
    ;;
esac

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
