# Vesta Tests

Integration test harness for `vestad` and related end-to-end flows.

## Layout

```
src/
  lib.rs          shared harness (TestServer, TestAgent, docker helpers, unique_user)
  client.rs       HTTP client for the vestad API
  types.rs        response/request types

tests/
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

  live/           live agent e2e — requires Claude credentials (4 tests)
    common.rs       shared live agent setup, notifications, container helpers
    file_ops.rs     notification-driven file create/modify
    interrupt.rs    interrupt mid-task: counting task aborted, redirect task completes
    mcp_tools.rs    in-conversation MCP tool use (cc_sdk stdio proxy + bridge with real claude)

  oauth/          Anthropic OAuth endpoint reachability (4 tests)
    common.rs       endpoint checker, constants
    endpoints.rs    authorize, token, callback endpoints
    token_exchange.rs  token exchange format validation

  migrations/     filesystem/skill layout migrations (3 tests)
    normalize.rs        legacy ~/vesta/ layout normalization (mirrors LEGACY_LAYOUT_NORMALIZE_SCRIPT)
    sparse_checkout.rs  installed-skills sparse-checkout pattern (mirrors upstream-sync SETUP.md)
```

## Running

```bash
./check.sh integration                       # what CI runs: server + multi_user + oauth + migrations
./check.sh live                              # live e2e (needs credentials)
cargo test -p vesta-tests                    # all tests
cargo test -p vesta-tests --test server      # server tests only
cargo test -p vesta-tests --test multi_user  # multi-user tests only
cargo test -p vesta-tests --test live        # live e2e (needs credentials)
cargo test -p vesta-tests --test oauth       # oauth endpoint checks
cargo test -p vesta-tests --test migrations  # layout migration tests
```

## Notes

- Live tests skip when `~/.claude/.credentials.json` is missing. Locally they use your own Claude session; agents run with `AGENT_MODEL=sonnet` (the harness restarts each agent after credential injection so the override applies to the whole run).
- All live tests share ONE agent (`lock_shared_live_agent` in common.rs): real first-start runs once for the whole suite, the harness then waits for the agent to settle (first-start keeps going after the agent reports alive, so tests must not start until the log goes quiet), and the tests serialize against it via a mutex (notifications, especially interrupts, are global to the agent's conversation).
- In CI, the `test-live` job runs **only on the release event** (not on PRs — live tests are slow and spend API tokens) and **gates the release**: the `release` and `push-image` jobs depend on it, so a live-test failure blocks publishing artifacts and the `:latest` image. It injects the `CLAUDE_CREDENTIALS` secret, which must hold its **own dedicated OAuth lineage** (seeded once from a separate `claude.ai/oauth/authorize` login, never copied from a developer's `~/.claude` — refresh tokens can rotate on use, so a shared lineage dies as soon as the other party refreshes). The `refresh-credentials.yml` workflow is the only thing allowed to refresh it: every 6h it refreshes whenever <8h of validity remain, so the secret always carries >=2h. A **missing** secret (forks) skips the live tests; a **present-but-stale/malformed** secret **fails** the release, since shipping without live coverage having run means the credential pipeline is broken.
- All tests require a working local Docker daemon.
- The agent image: vestad builds `vesta:local` from the checkout automatically (it finds `vestad/Dockerfile`). Set `VESTAD_AGENT_IMAGE` to pin a specific image instead — CI does this to test the image built from the PR.
- Multi-user and live tests use `unique_user()` for Docker container isolation across concurrent and repeated runs.
