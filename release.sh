#!/usr/bin/env bash
set -euo pipefail

#
# Two-step release process:
#   1. ./release.sh [patch|minor|major]  — creates version bump PR
#   2. ./release.sh --tag                — after PR merge, tags and creates GitHub release
#

if [ "${1:-}" = "--tag" ]; then
  # Step 2: tag the current version on master and create GitHub release
  BRANCH=$(git branch --show-current)
  if [ "$BRANCH" != "master" ]; then
    echo "Must be on master branch (currently on $BRANCH)"
    exit 1
  fi
  git pull --ff-only origin master

  VERSION=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)
  TAG="v${VERSION}"

  if gh release view "$TAG" &>/dev/null; then
    echo "Release ${TAG} already exists"
    exit 1
  fi

  git tag "$TAG"
  git push origin "$TAG"
  echo "Releasing ${TAG}..."
  gh release create "$TAG" --title "$TAG" --generate-notes
  exit 0
fi

# Step 1: create version bump PR
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "master" ]; then
  echo "Must be on master branch (currently on $BRANCH)"
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty — commit or stash changes first"
  exit 1
fi

git pull --ff-only origin master

./bump.sh "${1:-patch}"

VERSION=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)
TAG="v${VERSION}"

if gh release view "$TAG" &>/dev/null; then
  echo "Release ${TAG} already exists"
  git checkout -- .
  exit 1
fi

RELEASE_BRANCH="release/${TAG}"
git checkout -b "$RELEASE_BRANCH"
git add -A
git commit -m "Bump version to ${VERSION}"
git push -u origin "$RELEASE_BRANCH"

PR_URL=$(gh pr create \
  --title "Release ${TAG}" \
  --body "Version bump to ${VERSION} for release." \
  --base master \
  --head "$RELEASE_BRANCH")

git checkout master

echo ""
echo "Created release PR: $PR_URL"
echo "After merging, run: ./release.sh --tag"
