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
  integration    vestad integration tests (needs Docker)
  all            agent + cli + vestad + web

Environment:
  TARGET=<triple>  cross-compilation target for cargo suites, e.g.
                   TARGET=x86_64-pc-windows-msvc ./check.sh cli
EOF
  exit 1
}

check_agent() {
  (
    cd agent
    uv run ruff check
    uv run ruff format --check
    uv sync
    for tool in skills/*/cli/; do
      if [ -f "$tool/pyproject.toml" ]; then
        uv pip install -e "$tool"
      fi
    done
    uv run ty check
    uv run pytest tests/ -v
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
    cargo test -p vestad ${TARGET:+--target "$TARGET"}
  )
}

check_vestad_docker() {
  (
    cd vestad
    cargo test -p vestad -- --ignored
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

check_integration() {
  (
    cd vestad
    cargo test -p vesta-tests --test server --test multi_user --test oauth --test migrations -- --test-threads=8
  )
}

if [ $# -lt 1 ]; then
  usage
fi

for suite in "$@"; do
  case "$suite" in
    agent) check_agent ;;
    cli) check_cli ;;
    vestad) check_vestad ;;
    vestad-docker) check_vestad_docker ;;
    web) check_web ;;
    integration) check_integration ;;
    all) check_agent && check_cli && check_vestad && check_web ;;
    *)
      echo "error: unknown suite '$suite'" >&2
      usage
      ;;
  esac
done
