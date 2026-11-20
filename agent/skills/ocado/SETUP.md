# Ocado setup

1. Link the CLI (stdlib only, idempotent):
   ```bash
   chmod +x ~/agent/skills/ocado/ocado && ln -sf ~/agent/skills/ocado/ocado ~/.local/bin/ocado
   ```
2. Credential: the user sends it (or a 1Password share). Save it as `~/.ocado/cred.json`
   (`{"username": "...", "password": "..."}`, dir 700, file 600). Never echo it.
3. Needs the `browser` skill (session `ocado`, Chromium) and the `microsoft` skill on the account
   the Ocado codes go to.
4. `ocado login`, then `ocado status` should answer `"loggedIn": true`.
