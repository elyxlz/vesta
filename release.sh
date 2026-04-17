#!/usr/bin/env bash
set -euo pipefail

BUMP="${1:-patch}"

case "$BUMP" in
  patch|minor|major) ;;
  *) echo "Usage: ./release.sh [patch|minor|major]"; exit 1 ;;
esac

# Ensure we're on master and clean
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "master" ]; then
  echo "❌ Must be on master branch (currently on $BRANCH)"
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "❌ Working tree is dirty — commit or stash changes first"
  exit 1
fi

git pull --ff-only origin master

# Compute new version (vestad/Cargo.toml is the source of truth)
CURRENT=$(grep -A2 '^\[package\]' vestad/Cargo.toml | grep '^version = ' | cut -d'"' -f2)
IFS='.' read -r major minor patch_v <<< "$CURRENT"

case "$BUMP" in
  patch) NEW="${major}.${minor}.$((patch_v + 1))" ;;
  minor) NEW="${major}.$((minor + 1)).0" ;;
  major) NEW="$((major + 1)).0.0" ;;
esac

echo "Bumping ${CURRENT} -> ${NEW}"

# Bump version in all sources
sed -i "s|^version = \"${CURRENT}\"|version = \"${NEW}\"|" agent/pyproject.toml
sed -i "0,/^version = \"${CURRENT}\"/s|^version = \"${CURRENT}\"|version = \"${NEW}\"|" vestad/Cargo.toml
sed -i "0,/^version = \"${CURRENT}\"/s|^version = \"${CURRENT}\"|version = \"${NEW}\"|" vestad/tests-integration/Cargo.toml
sed -i "0,/^version = \"${CURRENT}\"/s|^version = \"${CURRENT}\"|version = \"${NEW}\"|" cli/Cargo.toml
sed -i "0,/^version = \"${CURRENT}\"/s|^version = \"${CURRENT}\"|version = \"${NEW}\"|" apps/desktop/src-tauri/Cargo.toml
sed -i "s|\"version\": \"${CURRENT}\"|\"version\": \"${NEW}\"|" apps/desktop/src-tauri/tauri.conf.json
sed -i "s|\"version\": \"${CURRENT}\"|\"version\": \"${NEW}\"|" apps/web/package.json
sed -i "s|\"version\": \"${CURRENT}\"|\"version\": \"${NEW}\"|" apps/desktop/package.json

# Update lockfiles
(cd vestad && cargo check --quiet)
(cd cli && cargo check --quiet)
(cd apps/desktop/src-tauri && cargo check --quiet)
(cd agent && uv lock --quiet)

# Commit, push, create release
TAG="v${NEW}"
git add -A
git commit -m "Bump version to ${NEW}"
git push origin master
gh release create "$TAG" --title "$TAG" --generate-notes --target master --prerelease

echo "✅ Created prerelease ${TAG}"
echo "CI will build artifacts, publish the release, and push to production."
