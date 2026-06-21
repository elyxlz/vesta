---
name: reduce-loc
description: Shrink a codebase's line count without changing behavior; dead code, dedup, then architectural simplification. Use when asked to reduce LOC, simplify, or trim a repo.
---

# Reduce LOC

Make a repo smaller while keeping it simple, clean, and behavior-identical. Not code golf:
every change must read as clean or cleaner to a senior engineer. The result must end
*simpler*, not denser. Bias to net deletion; a change that adds indirection to save lines is
a regression.

## Method

Work area by area in **parallel, isolated git worktrees** so passes never collide, then merge
each into one branch.

```bash
base=refactor/reduce-loc
git worktree add -b "$base" ../wt-reduce origin/master
for area in <areas>; do git worktree add -b "reduce-loc/$area" "../wt-rl-$area" "$base"; done
# one subagent per worktree -> commit on its branch -> merge all into $base -> push
bash scripts/worktrees.sh setup <repo-root> <area>...   # helper for the above
```

Dispatch one subagent per area. Each: reduces LOC in its scope only, **verifies against that
area's `./check.sh` subcommand before committing**, commits to its branch, does not push.
Then merge every area branch into the base branch and open one PR. Review each diff before
merging; never accept a bold deletion on trust.

## What to cut, in order

1. **Dead code**: unused functions, imports, fields, files, unreachable branches. Confirm with
   tooling, not eyeballing: `vulture` (Python), `knip` (TS), `clippy -D warnings` (Rust forbids
   dead code structurally). Grep every symbol repo-wide before deleting.
2. **Surface dedup**: a literal/constant/block repeated 2+ times moves to one owner; idiomatic
   collapse (guard clauses, `?`/`map`/comprehensions) *only when it reads cleaner*.
3. **Architecture** (where the real wins are once 1-2 are exhausted):
   - **Single source of truth**: one owner per constant, format, type, validation, event shape.
   - **Smaller stacks**: inline single-caller wrappers; delete barrel/re-export indirection;
     flatten deep call chains and over-layered error mapping.
   - **Collapse structural boilerplate**: many handlers/commands repeating the same
     parse->guard->call->respond shape share one small typed helper.
   - **External libraries**: replace hand-rolled retry/backoff, date math, arg parsing,
     pagination, table formatting with a maintained lib *when* it nets a real deletion, reads
     cleaner, and adds little risk. Prefer a lib already in the dependency tree; if adding one,
     update the lockfile so the freshness check passes. Justify every new dependency.

## Hard rules

- **No behavior change.** No wire/HTTP/CLI/env/event-shape changes, no error-message text that
  tests assert on, no public signature changes.
- **"Zero importers" is not enough**: check for *implicit* consumers before deleting: sync
  scripts that `cp`/mirror files, codegen inputs, reflection, dynamic dispatch, a canonical
  registry feeding another tree. (A registry deleted because one app didn't import it can still
  feed a generated mirror.)
- **Leave DAMP tests alone.** Test setup is intentionally explicit; do not DRY it for a few lines.
  Remove only genuinely dead/duplicate tests.
- **Don't touch generated code** (shadcn `components/ui/`, vendored, `@ts-nocheck`) beyond
  deleting truly unreferenced whole files, and respect any "do not delete" guard.
- **Surgical**: every changed line traces to LOC reduction; don't refactor adjacent working code.
- Honor the repo's own conventions (see its CLAUDE.md / CONTRIBUTING.md).

## Verify

Run the affected `./check.sh` subcommands; they must pass. Prove exhaustion with the dead-code
tools above rather than asserting it. Never report done until CI is green.
