# Provider ownership refactor + sign-out

## Goal

Make **all provider-related settings flow through the provider endpoints and `provider.py`**, instead of being lumped into the generic config store API. Concretely: `agent_model`, `max_context_tokens`, and `thinking` become provider-owned (joining the credentials / `agent_provider` / `openrouter_key` that already are), while `agent_personality` and the operational knobs stay general config. Also add a **sign-out** action that unauthenticates an agent.

This also closes a real bug found en route: provisioning fired `POST /provider` (restart) then `PUT /config`, and the config call hit the agent mid-restart and 502'd — silently dropping the chosen model/context. A single combined write + one restart designs that race out of existence.

## Motivation

- `agent_model`'s valid values are provider-specific (`opus`/`sonnet`/`haiku` vs OpenRouter slugs); `max_context_tokens` is interpreted per-provider (Claude 1M-beta threshold vs OpenRouter window cap); `thinking` is a model capability. They belong with the provider, not generic prefs.
- Today they're written via `PUT /config`, conceptually mislabeled and (for onboarding) racing the provider restart.

## Current state (verified)

- All of `agent_model`, `max_context_tokens`, `thinking`, `agent_personality`, `agent_provider`, `openrouter_key` live in **one config store** (`~/agent/data/config.json`), layered into `VestaConfig` (store > env > `defaults.json`).
- `provider.py` already owns provider writes: `set_claude` / `set_openrouter` write `agent_provider`/`openrouter_key` (and `set_openrouter` already writes `agent_model`). `ProviderStatus` already reports `model` + `max_context_tokens`.
- Read sites consume via `VestaConfig`: `client.py` (model into the SDK), compaction (`max_context_tokens`), SDK (`thinking`). **These are agnostic to who writes — they keep working unchanged.**
- An interim combined endpoint `POST /agents/{name}/provider/config` already exists (added during the bug fix) but currently proxies prefs to the agent's `PUT /config`. This refactor evolves it.

## Ownership split

| Setting | Owner (code) | Write endpoint | Read |
|---|---|---|---|
| Claude OAuth blob / OpenRouter key, `agent_provider` | `provider.py` | `POST /provider` | `GET /provider` |
| `agent_model`, `max_context_tokens`, `thinking` | `provider.py` (new write fn) | `/provider/config` | `GET /provider` |
| `agent_personality`, operational knobs | `config.py` | `PUT /config` | `GET /config` |

**No data migration:** values stay physically in `config.json`. Only the write path + the API surface that exposes them move.

## Agent (Python)

- `config.py`: `PROVIDER_PREF_FIELDS = {agent_model, max_context_tokens, thinking}` (+ the auth fields `agent_provider`/`openrouter_key`). `validate_config_updates` (PUT /config) **rejects** these with a clear error; new `validate_provider_prefs` accepts **only** `PROVIDER_PREF_FIELDS`. Both share a `_merge_validate` core.
- `provider.py`: add `set_provider_prefs(updates, *, config)` (thin owned wrapper writing provider prefs to the store, so all provider settings flow through `provider.py`) and `clear_provider(*, config, persisted)` (sign-out).
- New HTTP endpoint **`PUT /provider/config`** (`api.py`): sparse body `{agent_model?, max_context_tokens?, thinking?}` → `validate_provider_prefs` → `set_provider_prefs`. Returns `{ok, restart_required}` like `PUT /config`.
- New HTTP endpoint **`DELETE /provider`** (`api.py`): clears everything provider-owned — the Claude OAuth blob (`.credentials.json`), `openrouter_key`, and the provider prefs (model, context, thinking) — keeping only general config (personality) and the last `agent_provider` choice as a hint; sets status to `not_authenticated`.
- `thinking` is **write-only** through `/provider/config` (no `ProviderStatus`/`GET /provider` field — it has no reader; still readable via the full `GET /config` dump). `GET /provider/status` keeps reporting model/context as today.

## vestad (the proxy stays dumb — the caller specifies the split)

- **`POST /agents/{name}/provider/config`** body becomes three optional parts:
  ```
  { provider?: <auth>, provider_config?: {agent_model?, max_context_tokens?, thinking?}, config?: {agent_personality?} }
  ```
  Handler: ensure running → if `provider` proxy to agent `POST /provider`; if `provider_config` non-empty proxy to agent `PUT /provider/config`; if `config` non-empty proxy to agent `PUT /config`; then **one** `restart_agent`. Used for onboarding (all parts) and standalone provider-pref changes (`provider_config` only). vestad carries no field taxonomy — each named part maps to one agent endpoint.
- **`DELETE /agents/{name}/provider`**: proxy to agent `DELETE /provider`, restart once.
- Keep `POST /agents/{name}/provider` (re-auth), `PUT /agents/{name}/config` (general prefs), and the `GET`s.

## Clients

### Web app
- `setProvider`: send `{ provider, provider_config: {agent_model?, max_context_tokens?}, config: {agent_personality?} }` to `POST /provider/config`.
- `ProviderCard`: the model and context dialogs call `POST /provider/config` with `provider_config` only (not `setConfig`). Read current model/context from `getProvider` (`ProviderInfo` already exposes them), not `getConfig`.
- `thinking` has no dedicated app control today (read-only/debug), so nothing to rewire there — it simply becomes settable via `/provider/config` (CLI/future use).
- Add a **Sign out** button in `ProviderCard` behind an `AlertDialog` confirm ("sign out {name}? it won't be able to respond until you reconnect a provider"), calling `DELETE /agents/{name}/provider`. On success the agent reports `not_authenticated` and the existing unprovisioned-agent UI surfaces the provider picker.

### CLI
- `set_provider_credentials`: send model/context via `provider_config` in the `POST /provider/config` body (already a single call after the bug fix; just moves the keys into `provider_config`).
- `vesta settings --model/--context-window`: route through `POST /provider/config` (`provider_config`). Personality and other settings stay on `PUT /config`.
- Add **`vesta logout <name>`** → `DELETE /agents/{name}/provider`.

## Error handling

- `PUT /config` returns a 400 with an explicit message if a provider-owned key is sent (guides any stale caller).
- All proxied writes return `502` (`BAD_GATEWAY`) if the agent is unreachable, as today; the single-restart ordering removes the known race.
- `DELETE /provider` is idempotent: clearing already-absent creds is a no-op success.

## Testing

- **Agent (pytest):** `PUT /config` rejects `agent_model`/`max_context_tokens`/`thinking`; `PUT /provider/config` writes them and they surface in `GET /provider/status`; `clear_provider` clears creds + key + provider prefs (model/context) and flips status to `not_authenticated`, keeping personality.
- **vestad:** unit-test the three-part `provider/config` proxy splits to the right agent endpoints (mock agent); `DELETE /provider` path. Integration (Docker-gated) extends the existing provision helper.
- **Web:** contract types for `ProviderInfo` (thinking), `ProviderConfigRequest` body shape.
- **CLI:** `logout` and settings-routing covered by existing client tests where feasible.

## Out of scope

- Moving values to a separate on-disk provider store (explicitly rejected — keep in `config.json`).
- Changing how `thinking`/model/context are *read* by the agent runtime.
- Reworking the provider picker UI beyond wiring sign-out + the new request shape.

## Rollout / compatibility

- Clients and vestad ship together (CI version sync), so the `PUT /config` rejection of provider keys won't strand the app. A skewed older CLI sending model via `PUT /config` would get a clear 400 — acceptable and self-explanatory.
- No agent-state migration; `LEGACY` markers unaffected.
