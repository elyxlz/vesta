#!/usr/bin/env bash
# LEGACY(remove-when: no agent predating the release that ships this rename remains and
# the 2026-07 workspace migrations are fleet-applied): forwards to upstream-sync.
exec bash ~/agent/core/skills/upstream-sync/scripts/fetch-upstream.sh "$@"
