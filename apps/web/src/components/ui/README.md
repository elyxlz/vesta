# ui/: canonical shadcn registry. Not dead code, do not remove.

This directory is the single source of truth for the project's shadcn/ui
primitives. `scripts/sync-dashboard.sh` mirrors it verbatim into the dashboard
skill (`agent/skills/dashboard/app/src/components/ui/`), enforced 1-to-1 by CI's
`dashboard-sync-check`.

Do not remove a primitive just because `apps/web` does not import it. This is
intentionally the full shadcn set, kept for the dashboard skill and for future
use; `knip` flags them as unused (which is why `knip.json` ignores this dir), but
they are not dead code. To add one, add it here then run `bash scripts/sync-dashboard.sh`.
