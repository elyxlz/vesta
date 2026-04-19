#!/usr/bin/env bash
# Run the fast, local-runnable subset of CI checks before opening a PR.
# Mirrors .github/workflows/{ci,pr-checks}.yml — catches the "insta-fail on
# ruff/ty/clippy/lockfile" cases without waiting for CI.
#
# Skipped (out of scope for local): test-integration (Docker + slow),
# Windows/macOS/iOS/Android builds, Tauri bundling, install-script-check
# (PowerShell-only).
#
# Usage:
#   scripts/prepare-for-pr.sh          # run everything
#   SKIP_RUST=1 scripts/prepare-for-pr.sh   # skip cargo (slow on cold cache)
#   SKIP_WEB=1 scripts/prepare-for-pr.sh    # skip npm
#   SKIP_AGENT=1 scripts/prepare-for-pr.sh  # skip uv

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
FAILED=()

section() { printf "\n${BOLD}── %s ──${RESET}\n" "$1"; }
pass()    { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
fail()    { printf "  ${RED}✗${RESET} %s\n" "$1"; FAILED+=("$1"); }
skip()    { printf "  ${DIM}- %s (skipped)${RESET}\n" "$1"; }

run_in() {
  # run_in <dir> <label> <cmd> [args...] — runs in a subshell but updates FAILED in the parent
  local dir="$1"; shift
  local label="$1"; shift
  local log
  log=$(mktemp)
  if (cd "$dir" && "$@") >"$log" 2>&1; then
    pass "$label"
    rm -f "$log"
    return 0
  fi
  fail "$label"
  printf "${DIM}--- output ---${RESET}\n"
  sed 's/^/    /' "$log"
  printf "${DIM}--------------${RESET}\n"
  rm -f "$log"
  return 1
}

# ── version-check ─────────────────────────────────────────────
section "version-check"
AGENT=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)
VESTAD=$(grep '^version = ' vestad/Cargo.toml | head -1 | cut -d'"' -f2)
CLI=$(grep '^version = ' cli/Cargo.toml | head -1 | cut -d'"' -f2)
TESTS=$(grep '^version = ' vestad/tests-integration/Cargo.toml | head -1 | cut -d'"' -f2)
TAURI_CONF=$(python3 -c "import json; print(json.load(open('apps/desktop/src-tauri/tauri.conf.json'))['version'])")
TAURI_CARGO=$(grep '^version = ' apps/desktop/src-tauri/Cargo.toml | head -1 | cut -d'"' -f2)
APP=$(python3 -c "import json; print(json.load(open('apps/web/package.json'))['version'])")
MISMATCH=0
for nv in "vestad:$VESTAD" "cli:$CLI" "tests:$TESTS" "tauri.conf:$TAURI_CONF" "tauri-cargo:$TAURI_CARGO" "app:$APP"; do
  if [ "$AGENT" != "${nv#*:}" ]; then
    printf "  ${RED}✗${RESET} agent (%s) != %s (%s)\n" "$AGENT" "${nv%%:*}" "${nv#*:}"
    MISMATCH=1
  fi
done
if [ "$MISMATCH" = "0" ]; then pass "all versions match: $AGENT"; else FAILED+=("version-check"); fi

# ── vite-base-check ───────────────────────────────────────────
section "vite-base-check"
if grep -q 'base:\s*"\.\/"' apps/web/vite.config.ts; then
  fail "apps/web/vite.config.ts has base \"./\" — must be \"/\""
else
  pass "vite base is \"/\""
fi

# ── lockfile (uv) ─────────────────────────────────────────────
section "lockfile (agent/uv.lock)"
if [ "${SKIP_AGENT:-0}" = "1" ]; then
  skip "uv lockfile"
elif ! command -v uv >/dev/null 2>&1; then
  fail "uv not installed"
else
  (
    cd agent
    cp uv.lock uv.lock.before
    if uv lock >/dev/null 2>&1 && diff -q uv.lock.before uv.lock >/dev/null; then
      mv uv.lock.before uv.lock
      exit 0
    fi
    mv uv.lock.before uv.lock
    exit 1
  ) && pass "uv.lock up to date" || fail "uv.lock stale — run 'cd agent && uv lock' and commit"
fi

# ── skills-index-check ────────────────────────────────────────
section "skills-index-check"
if [ "${SKIP_AGENT:-0}" = "1" ]; then
  skip "skills index"
else
  before=$(sha256sum agent/skills/index.json | cut -d' ' -f1)
  if uv run python agent/skills/generate-index.py >/dev/null 2>&1; then
    after=$(sha256sum agent/skills/index.json | cut -d' ' -f1)
    if [ "$before" = "$after" ]; then
      pass "skills/index.json up to date"
    else
      fail "skills/index.json stale — regenerated (commit the change)"
    fi
  else
    fail "generate-index.py failed"
  fi
fi

# ── dashboard-sync-check ──────────────────────────────────────
section "dashboard-sync-check"
if bash scripts/sync-dashboard.sh >/dev/null 2>&1; then
  if git diff --quiet agent/skills/dashboard/app/; then
    pass "dashboard shared files in sync"
  else
    fail "dashboard shared files stale — ran sync-dashboard.sh (commit the change)"
  fi
else
  fail "sync-dashboard.sh failed"
fi

# ── agent-tests ───────────────────────────────────────────────
section "agent-tests"
if [ "${SKIP_AGENT:-0}" = "1" ]; then
  skip "agent-tests"
else
  run_in agent "ruff check"          uv run ruff check
  run_in agent "ruff format --check" uv run ruff format --check
  run_in agent "ty check"            uv run ty check
  run_in agent "pytest"              uv run pytest tests/ --ignore=tests/test_e2e.py -q
fi

# ── test-frontend ─────────────────────────────────────────────
section "test-frontend"
if [ "${SKIP_WEB:-0}" = "1" ]; then
  skip "frontend"
else
  if [ ! -d apps/node_modules ]; then
    printf "  ${YELLOW}!${RESET} apps/node_modules missing — running npm install\n"
    run_in apps "npm install" npm install
  fi
  run_in apps "web lint"         npm -w @vesta/web run lint
  run_in apps "web format check" npm -w @vesta/web run format -- --check
  run_in apps "web type check"   npm -w @vesta/web run check
  run_in apps "web tests"        npm -w @vesta/web run test
fi

# ── check-vesta (clippy + unit tests, cli + vestad) ───────────
section "check-vesta"
if [ "${SKIP_RUST:-0}" = "1" ]; then
  skip "cargo clippy/test"
else
  run_in cli    "cli clippy"    cargo clippy -- -D warnings
  run_in cli    "cli tests"     cargo test
  run_in vestad "vestad clippy" env VESTAD_SKIP_APP_BUILD=1 cargo clippy -p vestad -- -D warnings
  run_in vestad "vestad tests"  env VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad
fi

# ── go-checks (only if whatsapp CLI changed) ──────────────────
section "go-checks"
if git diff --quiet origin/master...HEAD -- agent/skills/whatsapp/cli/ 2>/dev/null; then
  skip "no changes under agent/skills/whatsapp/cli/"
else
  if ! command -v gofmt >/dev/null 2>&1; then
    fail "gofmt not installed"
  else
    unformatted=$(cd agent/skills/whatsapp/cli && gofmt -l .)
    if [ -z "$unformatted" ]; then
      pass "gofmt clean"
    else
      fail "unformatted go files: $unformatted"
    fi
  fi
fi

# ── summary ───────────────────────────────────────────────────
printf "\n"
if [ ${#FAILED[@]} -eq 0 ]; then
  printf "${GREEN}${BOLD}✅ all checks passed — ready to open PR${RESET}\n"
  exit 0
fi
printf "${RED}${BOLD}❌ %d check(s) failed:${RESET}\n" "${#FAILED[@]}"
for f in "${FAILED[@]}"; do printf "   ${RED}-${RESET} %s\n" "$f"; done
exit 1
