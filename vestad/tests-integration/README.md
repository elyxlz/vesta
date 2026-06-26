# Vesta Tests

Shared harness (`vesta-tests` crate) for `vestad`'s integration and live e2e tests.

The harness lives here; the **test suites live in `vestad/tests/`** so `cargo test -p vestad
--test <name>` builds the vestad binary first and passes its path via `CARGO_BIN_EXE_vestad`
(no separate build, no stale-binary risk). `vestad` dev-depends on this crate for the harness.

## Layout

```
vestad/tests-integration/src/   (this crate: harness only)
  lib.rs          shared harness (TestServer, TestAgent, docker helpers, unique_user)
  client.rs       HTTP client for the vestad API
  types.rs        response/request types

vestad/tests/                   (the actual suites — run via `cargo test -p vestad --test <name>`)
  server/         single-vestad API and lifecycle (49 tests)
    health.rs       health endpoints, port/api-key files, duplicate server rejection
    lifecycle.rs    create/start/stop/restart/destroy, creation flow, start_all
    auth.rs         OAuth flow, token injection
    rename.rs       agent rename flow, container renaming, rename notifications
    backup.rs       create/list/restore/delete, safety snapshots
    websocket.rs    WS connect, auth rejection
    ports.rs        port uniqueness, env files, agent tokens
    agent_code.rs   manage_agent_code mounts, rebuild
    layout.rs       fresh agent container filesystem structure

  multi_user/     multi-user isolation (6 tests)
    common.rs       start_pair helper (unique users per test)
    isolation.rs    server separation, agent visibility isolation
    containers.rs   user-prefixed container names
    ports.rs        WS port uniqueness across users
    lifecycle.rs    independent stop/destroy across users

  live/           live agent e2e — requires an OpenRouter key (4 tests)
    common.rs       shared live agent setup, notifications, container helpers
    file_ops.rs     notification-driven file create/modify
    interrupt.rs    interrupt mid-task: counting task aborted, redirect task completes
    mcp_tools.rs    in-conversation MCP tool use (cc_sdk stdio proxy + bridge with real claude)

  oauth/          Anthropic OAuth endpoint reachability (4 tests)
    common.rs       endpoint checker, constants
    endpoints.rs    authorize, token, callback endpoints
    token_exchange.rs  token exchange format validation
```

## Running

```bash
./check.sh integration                    # what CI runs: server + multi_user + oauth
./check.sh live                           # live e2e (needs OPENROUTER_KEY)
cargo test -p vestad --test server        # server tests only (builds vestad first)
cargo test -p vestad --test multi_user    # multi-user tests only
cargo test -p vestad --test live          # live e2e (needs OPENROUTER_KEY)
cargo test -p vestad --test oauth         # oauth endpoint checks
cargo test -p vestad --bins               # vestad unit tests only (NOT these suites)
```

## Notes

- Live tests skip when `OPENROUTER_KEY` is unset. Set it to an OpenRouter API key to run them; agents sign in to OpenRouter on `deepseek/deepseek-v4-flash` (override with `LIVE_TEST_MODEL`), and the harness restarts each agent after sign-in so the provider applies to the whole run.
- All live tests share ONE agent (`lock_shared_live_agent` in common.rs): real first-start runs once for the whole suite, the harness then waits for the agent to settle (first-start keeps going after the agent reports alive, so tests must not start until the log goes quiet), and the tests serialize against it via a mutex (notifications, especially interrupts, are global to the agent's conversation).
- In CI, the `test-live` job runs **only on the release event** (not on PRs — live tests are slow and spend API tokens) and **gates the release**: the `release` and `push-image` jobs depend on it, so a live-test failure blocks publishing artifacts and the `:latest` image. It passes the `OPENROUTER_KEY` secret (a static API key — nothing to refresh) to the suite. A **missing** secret (forks) skips the live tests.
- All tests require a working local Docker daemon.
- The agent image: vestad builds `vesta:local` from the checkout automatically (it finds `vestad/Dockerfile`). Set `VESTAD_AGENT_IMAGE` to pin a specific image instead — CI does this to test the image built from the PR.
- Multi-user and live tests use `unique_user()` for Docker container isolation across concurrent and repeated runs.
