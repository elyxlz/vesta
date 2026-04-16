# Vesta Tests

This crate contains the Rust integration test harness for `vestad` and related end-to-end flows.

## Layout

- `src/`
  Shared test harness code:
  - `lib.rs`: starts/stops test `vestad` servers, finds binaries, downloads released `vestad` builds, and provides `TestAgent` helpers
  - `client.rs`: HTTP client for the `vestad` API used by the tests
  - `types.rs`: response/request data types used by the harness

- `tests/server.rs`
  Main API and lifecycle coverage for a single `vestad` instance.
  Covers:
  - health/auth behavior
  - agent create/start/stop/restart/destroy
  - naming rules
  - WebSocket connectivity
  - backups and restore-related flows
  - rebuild and core-code-management behavior

- `tests/multi_user.rs`
  Multi-user isolation coverage.
  Covers:
  - separate `vestad` servers for different Unix users
  - agent visibility isolation between users
  - user-specific container naming
  - independent lifecycle operations across users
  - WS port uniqueness across both servers

- `tests/oauth.rs`
  OAuth and auth-session specific coverage.
  Covers:
  - auth session creation/refresh behavior
  - invalid or expired auth handling

- `tests/upgrade.rs`
  Upgrade-path coverage from the latest released `vestad` binary to the current repo build.
  Covers:
  - creating an agent under the latest release
  - starting current `vestad` against the same HOME/config state
  - reconciliation/rebuild of older containers
  - upgraded container git/layout invariants
  - ancestry against `VESTA_UPSTREAM_REF`
  - migration of legacy runtime/state directories into `/root/agent/...`

- `tests/live.rs`
  Entry point for live-agent tests that require real Claude credentials and available usage quota.
  The actual tests live under `tests/live/`.

- `tests/live/agent_e2e.rs`
  Ignored-by-default live agent E2E tests.
  Covers:
  - notification-driven file creation
  - notification-driven file modification
  - reporting the migrated `/root` tree after using `agent/skills/upstream-sync/SETUP.md`
  - reporting the default fresh-install `/root` tree

## Running

- Build/compile-only check:
  ```bash
  cargo test -p vesta-tests --no-run
  ```

- Run the normal integration suite:
  ```bash
  cargo test -p vesta-tests
  ```

- Run only the upgrade test:
  ```bash
  cargo test -p vesta-tests latest_released_vestad_upgrades_to_current_and_agent_git_state_is_valid -- --test-threads=1
  ```

- Run only multi-user tests:
  ```bash
  cargo test -p vesta-tests --test multi_user -- --test-threads=1
  ```

- Run the live ignored tests explicitly:
  ```bash
  cargo test -p vesta-tests --test live -- --ignored --test-threads=1
  ```

## Notes

- The live tests require `~/.claude/.credentials.json` and available Claude usage quota.
- The upgrade test downloads the latest released `vestad` binary from GitHub at runtime.
- Many tests use Docker directly; they expect a working local Docker daemon.
