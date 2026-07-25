# Plex skill setup

The CLI needs the Plex server address and an auth token.

## 1. PLEX_URL

The base URL of the Plex Media Server, including port. Examples:
- Local network: `http://192.168.1.50:32400`
- Same host as this container (host networking): `http://localhost:32400`
- Remote/DNS: `https://plex.yourdomain.com`

## 2. PLEX_TOKEN

An `X-Plex-Token`. Easiest way to grab one:
1. Sign in to Plex in a browser.
2. Open any library item, click the `...` menu → **Get Info** → **View XML**.
3. In the URL that opens, copy the value of `X-Plex-Token=...`.

(Alternatively: Plex account settings, or any authenticated Plex Web API URL contains the token.)

## 3. Store it

Two options (env wins if both present):

**A. Config file (recommended, survives restarts):**
```bash
mkdir -p ~/.plex
cat > ~/.plex/config.json <<'EOF'
{ "url": "http://localhost:32400", "token": "YOURTOKEN" }
EOF
chmod 600 ~/.plex/config.json
```

**B. Environment (add to `~/.bashrc` so it persists):**
```bash
export PLEX_URL="http://localhost:32400"
export PLEX_TOKEN="YOURTOKEN"
```

## 4. Verify

```bash
cd ~/agent/skills/plex && ./plex.py sections
```
Should list the libraries. If it errors on connection, check the URL/port is reachable from this container and the token is current.

## Notes

- The token is a credential, keep it in `~/.plex/config.json` (chmod 600) or `~/.bashrc`, never in MEMORY.md or a shared/committed file.
- First run installs `plexapi` via uv automatically.
