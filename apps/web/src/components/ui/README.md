# ui/ — canonical shadcn registry

This directory is the **single source of truth** for the project's shadcn/ui
primitives. It is mirrored verbatim into the `dashboard` skill
(`agent/skills/dashboard/app/src/components/ui/`) by `scripts/sync-dashboard.sh`,
enforced 1-to-1 by CI's `dashboard-sync-check`.

**Do not delete a primitive here just because `apps/web` does not import it.**
The dashboard skill is the other consumer: the agent uses it to build arbitrary
UIs, so this set is intentionally the **full** shadcn library, not only what the
web app currently renders. Dead-code tools (knip) will flag these as unused —
that is expected, and why `knip.json` ignores this directory. Removing one breaks
the dashboard's available component set and the sync mirror.

To add a primitive, add it here (e.g. via the shadcn CLI), then run
`bash scripts/sync-dashboard.sh` to propagate it to the dashboard skill.
