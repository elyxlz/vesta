---
name: vpn
description: This skill should be used when the user asks about their VPN, proxy, or SOCKS5 connection: checking status, fetching the proxy URL for another skill, or switching the active provider.
---

# VPN / Proxy

Provider-agnostic VPN/proxy management. Other skills should call this rather than reading `SOCKS5_*` env vars directly, so the active provider can change in one place.

## Connection

Provider config lives at `~/.vpn/config.json`. Credentials are referenced by env-var name (e.g. `username_env: SOCKS5_USER`) so secrets stay in `.bashrc` / shell, not in the config file.

A default config is created on first run with a placeholder `default` provider. Edit it before using the skill in earnest.

## CLI

```bash
~/agent/skills/vpn/vpn status                # Active provider + connectivity check
~/agent/skills/vpn/vpn test                  # Connectivity test through the proxy
~/agent/skills/vpn/vpn proxy-url             # Print the proxy URL (socks5://user:pass@host:port)
~/agent/skills/vpn/vpn providers             # List configured providers
~/agent/skills/vpn/vpn set-provider <name>   # Switch active provider
~/agent/skills/vpn/vpn config                # Show current config (credentials masked)
```

## Using from other skills

```bash
PROXY_URL=$(~/agent/skills/vpn/vpn proxy-url)
curl --proxy "$PROXY_URL" https://example.com
```

This is the canonical way for any skill that needs proxied traffic. Do not read `SOCKS5_*` directly in new code; the user might switch providers and expect everything to follow.

## Adding a provider

Edit `~/.vpn/config.json` and add an entry under `providers`:

```json
{
  "type": "socks5",
  "host": "amsterdam.nl.socks.nordhold.net",
  "port": 1080,
  "username_env": "SOCKS5_USER",
  "password_env": "SOCKS5_PASS"
}
```

Make sure the named env vars are exported in your shell, then activate it: `vpn set-provider <name>`.

## Troubleshooting

**`proxy-url` prints with `(unset)` in place of credentials.** The env vars referenced in the provider's `username_env` / `password_env` are not exported. Add them to `.bashrc` / `.zshrc` and reload the shell.

**`vpn test` fails but `vpn status` says configured.** Proxy host or credentials are wrong, or the provider is down. Try `vpn providers` to confirm the active one, `vpn config` to inspect, then test against the provider's own status page.

**Wrong region / want to switch.** `vpn providers` to list, `vpn set-provider <name>` to switch. Skills calling `vpn proxy-url` will pick up the new value on the next call.
