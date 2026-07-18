#!/usr/bin/env bash
# LEGACY(remove-when: the 2026-07-workspace-conversion migration is fleet-applied and no
# pre-flat box remains): the flat checkout has no sparse cone, so there is nothing to set.
# A released migration (2026-07-workspace-conversion.md, unchangeable) still calls this at
# its final step; keep it as a no-op so that step doesn't error on an already-converted box.
exit 0
