# Keeper Setup

1. Install: `uv tool install keepercommander`
2. First-time login (interactive - only needed once):
   ```bash
   keeper shell
   ```
   Inside the shell:
   ```
   login user@example.com
   this-device register
   this-device persistent-login on
   this-device timeout 30d
   quit
   ```
3. After this, all commands work non-interactively via `keeper "command"`

## First-Time Device Approval

When prompted during first login:
```
email_send                       # send approval email
email_code=<code>                # submit verification code
keeper_push                      # push notification to mobile
2fa_code=<code>                  # submit 2FA code
```

Region selection (before login): `server EU` (options: EU, US, AU, GOV, CA, JP)

IMPORTANT: Use `quit` (not `logout`) to exit - `logout` expires the session.
