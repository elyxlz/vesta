#!/usr/bin/env bash
# Single entry point for every test suite and lint check.
# CI calls these exact subcommands, so CI and local checks can never drift.
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage: ./check.sh <suite> [<suite> ...]

Suites:
  agent          ruff check + ruff format --check + ty check + pytest
                 (cc_sdk transport tests need tmux; they skip locally without it)
  cli            cargo clippy -D warnings + cargo test
  vestad         cargo clippy -p vestad -D warnings + cargo test -p vestad
  vestad-docker  vestad #[ignore] Docker tests (needs Docker + an agent image:
                 set VESTAD_AGENT_IMAGE or docker pull ghcr.io/elyxlz/vesta:latest)
  web            eslint + prettier --check + tsc + vitest
  guards         skills index, uv.lock, and dashboard-sync freshness + the vite base check
  integration    vestad integration tests (needs Docker)
  live           live agent e2e tests, incl. the upgrade gate (needs Docker + ~/.claude/.credentials.json; real Claude)
  upgrade        just the upgrade e2e: create an agent on the previous release, update in place
                 to this build, assert migrations converge (needs Docker + credentials; real Claude)
                   ./check.sh upgrade                       # previous release -> this build
                   ./check.sh upgrade --from v0.1.155        # from a specific release
                   ./check.sh upgrade --from v0.1.155 --to v0.1.159   # both released versions
                 Note: a debug build syncs the agent from the CURRENT BRANCH ref, so when the
                 target is this build, push your branch first (else the agent's migration sync
                 can't fetch it). The release gate builds in release mode and uses the version
                 tag, so it needs no push.
  all            agent + cli + vestad + web

Environment:
  TARGET=<triple>  cross-compilation target for cargo suites, e.g.
                   TARGET=x86_64-pc-windows-msvc ./check.sh cli
  VESTA_UPGRADE_FROM / VESTA_UPGRADE_TO  release tags for the upgrade suite
                   (the `upgrade` subcommand's --from/--to set these)
EOF
  exit 1
}

check_agent() {
  (
    cd agent
    # The engine project lives at core/ (published to boxes); dev-tool configs
    # (ruff.toml, pytest.ini, ty.toml) live here and are never published.
    export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
    uv run --project core ruff check
    uv run --project core ruff format --check
    uv sync --project core
    for tool in skills/*/cli/; do
      if [ -f "$tool/pyproject.toml" ]; then
        uv pip install -e "$tool"
      fi
    done
    uv run --project core ty check
    uv run --project core pytest tests/ -v
    # Each skill CLI is its own standalone uv project (own venv, own lockfile), so
    # its suite runs against that project, not the shared core venv above.
    for tool in skills/*/cli core/skills/*/cli; do
      if [ -d "$tool/tests" ]; then
        uv run --project "$tool" pytest "$tool/tests" -q
      fi
    done
  )
}

check_cli() {
  (
    cd cli
    cargo clippy ${TARGET:+--target "$TARGET"} -- -D warnings
    cargo test ${TARGET:+--target "$TARGET"}
  )
}

check_vestad() {
  (
    cd vestad
    cargo clippy -p vestad ${TARGET:+--target "$TARGET"} -- -D warnings
    # --bins: unit tests only. The Docker/live integration suites also live in this package
    # now (vestad/tests/), so a bare `cargo test -p vestad` would try to run them.
    cargo test -p vestad --bins ${TARGET:+--target "$TARGET"}
  )
}

check_vestad_docker() {
  (
    cd vestad
    cargo test -p vestad --bins -- --ignored
  )
}

check_web() {
  (
    cd apps
    if [ ! -d node_modules ]; then
      npm install
    fi
    npm -w @vesta/web run lint
    npm -w @vesta/web run format:check
    npm -w @vesta/web run check
    npm -w @vesta/web run test
  )
}

check_guards() {
  # Fast repo-hygiene checks ci.yml otherwise runs as raw steps outside this
  # entry point: skills index, uv.lock, and dashboard-sync freshness, plus the
  # vite base path check. All run from the repo root; none need Docker.
  local failed=0

  uv run python agent/skills/generate-index.py
  git diff --exit-code agent/skills/index.json || {
    echo "error: agent/skills/index.json is stale — run 'uv run python agent/skills/generate-index.py' and commit the result" >&2
    failed=1
  }

  cp agent/core/uv.lock agent/core/uv.lock.before
  uv lock --project agent/core
  diff -q agent/core/uv.lock.before agent/core/uv.lock >/dev/null || {
    echo "error: agent/core/uv.lock is out of date — run 'cd agent && uv lock --project core' and commit the changes" >&2
    failed=1
  }
  rm -f agent/core/uv.lock.before

  bash scripts/sync-dashboard.sh
  git diff --quiet agent/skills/dashboard/app/ || {
    echo "error: dashboard shared files are out of sync with apps/web/ — run 'bash scripts/sync-dashboard.sh' and commit the changes" >&2
    failed=1
  }

  if grep -q 'base:\s*"\.\/"' apps/web/vite.config.ts; then
    echo 'error: apps/web/vite.config.ts has base: "./" — must be "/" for Cloudflare deployments' >&2
    failed=1
  fi

  [ "$failed" = 0 ]
}

check_integration() {
  (
    cd vestad
    # `cargo test -p vestad --test ...` builds the vestad binary first and passes its path to
    # the tests via CARGO_BIN_EXE_vestad — always fresh, never a stale binary.
    cargo test -p vestad --test server --test multi_user --test oauth -- --test-threads=8
  )
}

check_live() {
  (
    cd vestad
    # The live tests use a 2-agent pool (see tests/live/common.rs); run enough threads that
    # every test starts and self-organizes onto its pool's mutex, so the two agents run in
    # parallel instead of serializing on one. The upgrade e2e (tests/live/upgrade.rs) is part of
    # this suite, so the release gate covers it alongside the other live tests.
    cargo test -p vestad --test live -- --test-threads=8
  )
}

check_upgrade() {
  (
    cd vestad
    # Just the upgrade e2e from the live suite. --nocapture streams the agent's container log live.
    # Skip the embedded web app build: this is a backend/daemon test that never serves the app, and
    # building it would couple the run to apps/ npm deps being installed and current.
    VESTAD_SKIP_APP_BUILD=1 cargo test -p vestad --test live upgrade -- --test-threads=8 --nocapture
  )
}

if [ $# -lt 1 ]; then
  usage
fi

# `upgrade` takes optional --from/--to flags, so handle it before the plain suite loop.
if [ "${1:-}" = "upgrade" ]; then
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --from) export VESTA_UPGRADE_FROM="${2:?--from needs a release tag}"; shift 2 ;;
      --to) export VESTA_UPGRADE_TO="${2:?--to needs a release tag}"; shift 2 ;;
      *) echo "error: unknown upgrade flag '$1'" >&2; usage ;;
    esac
  done
  check_upgrade
  exit $?
fi

for suite in "$@"; do
  case "$suite" in
    agent) check_agent ;;
    cli) check_cli ;;
    vestad) check_vestad ;;
    vestad-docker) check_vestad_docker ;;
    web) check_web ;;
    guards) check_guards ;;
    integration) check_integration ;;
    live) check_live ;;
    all) check_agent && check_cli && check_vestad && check_web ;;
    *)
      echo "error: unknown suite '$suite'" >&2
      usage
      ;;
  esac
done
