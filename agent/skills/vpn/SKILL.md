---
name: vpn
description: This skill should be used when the user asks about "vpn", "proxy", "socks5", "nordvpn", "tunnel", "proxy url", or needs to route traffic through a VPN/proxy, check proxy status, or configure proxy settings for other skills.
---

# VPN / Proxy Skill

Provider-agnostic VPN and proxy management. Other skills use this as the canonical source for proxy configuration instead of reading raw environment variables.

## CLI

```bash
~/agent/skills/vpn/vpn status        # Show active provider and test connectivity
~/agent/skills/vpn/vpn test          # Test connectivity through the proxy
~/agent/skills/vpn/vpn proxy-url     # Output the proxy URL (socks5://user:pass@host:port)
~/agent/skills/vpn/vpn providers     # List available providers
~/agent/skills/vpn/vpn set-provider <name>   # Set the active provider
~/agent/skills/vpn/vpn config        # Show current config (credentials masked)
```

## Usage from Other Skills

Any skill that needs proxy/VPN access should call:

```bash
PROXY_URL=$(~/agent/skills/vpn/vpn proxy-url)
curl --proxy "$PROXY_URL" https://example.com
```

This replaces the old pattern of reading `SOCKS5_*` env vars directly.

## Config

Config is stored at `~/.vpn/config.json`. It holds a `providers` object and an `active_provider` field. Credentials are resolved from environment variables (referenced by name in the config) so secrets stay in `.bashrc` and out of the config file.

## Providers

On first run, a default config is created at `~/.vpn/config.json` with a placeholder provider. Edit it to add your actual proxy/VPN details.

Example provider (NordVPN SOCKS5):
- **Type:** SOCKS5 proxy
- **Host:** `your-region.socks.nordhold.net`
- **Port:** 1080
- **Credentials:** Read from `SOCKS5_USER` / `SOCKS5_PASS` env vars

## Adding a New Provider

1. Add an entry to `~/.vpn/config.json` under `providers` with `type`, `host`, `port`, and credential references.
2. Set it active with `vpn set-provider <name>`.
