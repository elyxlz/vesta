# Vesta Tests

Integration test harness for `vestad` and related end-to-end flows.

## Layout

```
src/
  lib.rs          shared harness (TestServer, TestAgent, docker helpers, unique_user)
  client.rs       HTTP client for the vestad API
  types.rs        response/request types

tests/
  server/         single-vestad API and lifecycle (43 tests)
    health.rs       health endpoints, port/api-key files, duplicate server rejection
    lifecycle.rs    create/start/stop/restart/destroy, creation flow, start_all
    auth.rs         OAuth flow, token injection
    names.rs        normalization, empty/special chars
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
    common.rs       setup_live_agent, notifications, container helpers
    file_ops.rs     notification-driven file create/modify
    mcp_tools.rs    in-conversation MCP tool use (cc_sdk stdio proxy + bridge with real claude)
    tree.rs         first-start migration (seeds old ~/vesta/ layout, verifies agent migrates it)

  oauth/          Anthropic OAuth endpoint reachability (4 tests)
    common.rs       endpoint checker, constants
    endpoints.rs    authorize, token, callback endpoints
    token_exchange.rs  token exchange format validation

  migrations/     upgrade path from latest release (1 test)
    common.rs       container lookup by label, wait helpers
    upgrade.rs      create agent under released vestad, upgrade to current, verify git state
```

## Running

```bash
cargo test -p vesta-tests                    # all tests
cargo test -p vesta-tests --test server      # server tests only
cargo test -p vesta-tests --test multi_user  # multi-user tests only
cargo test -p vesta-tests --test live        # live e2e (needs credentials)
cargo test -p vesta-tests --test oauth       # oauth endpoint checks
cargo test -p vesta-tests --test migrations  # upgrade path test
```

## Notes

- Live tests skip when `~/.claude/.credentials.json` is missing. Locally they use your own Claude session; agents run with `AGENT_MODEL=sonnet` (the harness restarts each agent after credential injection so the override applies to the whole run).
- In CI, the `test-live` job injects the `CLAUDE_CREDENTIALS` secret. That secret must hold its **own dedicated OAuth lineage** (seeded once from a separate `claude.ai/oauth/authorize` login, never copied from a developer's `~/.claude` — refresh tokens can rotate on use, so a shared lineage dies as soon as the other party refreshes). The `refresh-credentials.yml` workflow is the only thing allowed to refresh it: every 6h it refreshes whenever <8h of validity remain, so the secret always carries >=2h. `test-live` skips with a warning when the secret has <1h left, so agents in CI never need to refresh the token themselves.
- The live migration test (`tree.rs`) seeds an old-style `~/vesta/` layout before auth, then verifies the agent's first-start prompt (`migration.md` + `first_start_setup.md`) migrates it correctly. `wait_until_alive` returns only after first-start setup has been processed; the agent binds its WS port as its readiness signal.
- The upgrade test downloads the latest released `vestad` binary from GitHub at runtime.
- All tests require a working local Docker daemon.
- Multi-user and live tests use `unique_user()` for Docker container isolation across concurrent and repeated runs.
