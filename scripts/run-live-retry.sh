#!/usr/bin/env bash
# Run the live release-gate suite; on failure, retry ONLY the tests that failed, not the whole
# suite. The live suite shares one in-process 2-agent pool (tests/live/common.rs), so retries must
# stay at the suite/process level: cargo-nextest runs each test in its own process and would break
# that shared pool. Attempt 2 is a fresh cargo-test run filtered to the names that failed.
set -uo pipefail

run_live() { VESTAD_AGENT_IMAGE=vesta:local ./check.sh live; }

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

echo "live tests: attempt 1"
if run_live 2>&1 | tee "$log"; then
  exit 0
fi

# libtest ends a failed run with an indented list of failed test paths under a "failures:" header.
mapfile -t failed < <(
  sed -n '/^failures:$/,/^test result:/p' "$log" \
    | grep -E '^    [A-Za-z0-9_]+(::[A-Za-z0-9_]+)+$' \
    | tr -d ' ' | sort -u
)

if [ "${#failed[@]}" -eq 0 ]; then
  echo "live tests: could not identify the failed tests; retrying the full suite"
  retried="the full suite"
else
  echo "live tests: attempt 2 reruns only: ${failed[*]}"
  retried="${failed[*]}"
  export LIVE_TEST_FILTER="${failed[*]}"
fi

# Flakiness must stay visible, not be silently absorbed by the retry (mirrors ci.yml).
echo "::warning title=Flaky live tests::Live suite failed on attempt 1 and retried: ${retried}"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## ⚠️ Live test flakiness"
    echo ""
    echo "The live suite failed on attempt 1 and retried: **${retried}**."
    echo "Check attempt 1's logs above for a masked real failure."
  } >> "$GITHUB_STEP_SUMMARY"
fi

run_live
