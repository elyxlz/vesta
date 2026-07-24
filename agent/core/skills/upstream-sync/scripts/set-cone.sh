#!/usr/bin/env bash
# LEGACY(remove-when: the 2026-07-workspace-conversion and 2026-07-workspace-resync migrations
# are fleet-applied and no pre-flat box remains): the flat checkout has no sparse cone, so there
# is nothing to set. Released migrations still call this path directly or via workspace-sync;
# keep it as a no-op so those steps don't error on an already-converted box.
exit 0
