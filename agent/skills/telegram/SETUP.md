# Telegram Setup

1. Install dependencies (gcc for CGO and Go from https://go.dev/dl/, NOT the system package manager):
   ```bash
   apt-get install -y gcc
   ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
   curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
   export PATH="/usr/local/go/bin:$PATH"
   ```
2. Build the Telegram CLI (CGO required for SQLite with FTS5):
   ```bash
   cd ~/agent/skills/telegram/cli && CGO_ENABLED=1 CGO_CFLAGS="-DSQLITE_ENABLE_FTS5" CGO_LDFLAGS="-lm" go build -o /usr/local/bin/telegram .
   ```
3. Create a Telegram bot and authenticate:
   - Tell the user to message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow the prompts to create a bot
   - Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
   - Save the token:
     ```bash
     telegram authenticate --token "<BOT_TOKEN>"
     ```
4. Start the daemon:
   ```bash
   telegram daemon start
   ```
   Idempotent (a running daemon is a no-op) and defaults `--notifications-dir` to `~/agent/notifications`. Check with `telegram daemon status`.
5. Then have them open the bot and send any message (hitting Start counts). Wait for that first inbound notification and confirm back on the new channel before declaring it live: the channel does not exist until you have replied to them on it.
6. Add to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
   ```
   running telegram || { telegram daemon start; sleep 1; }
   running telegram-watchdog || { screen -dmS telegram-watchdog bash ~/agent/skills/telegram/telegram-watchdog.sh; sleep 1; }
   ```
   The watchdog (`telegram-watchdog.sh`) runs in its own screen session and restarts the daemon
   if it dies, independent of the agent loop, so the channel self-heals even while the agent is
   busy or mid-restart. It is rate-limited (backs off after repeated restarts) and drops a
   notification when it acts. Especially important when Telegram is the primary/only channel.

   **Deploying a new binary:** build it, then `telegram daemon restart`. The restart quits the
   watchdog first, restarts the daemon, and brings the watchdog back, so the watchdog can never
   race you into two daemons (two pollers, Telegram 409 Conflict).
