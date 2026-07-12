# Telegram Setup

1. Install dependencies (gcc for CGO and Go from https://go.dev/dl/, NOT the system package manager):
   ```bash
   apt-get install -y gcc
   ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
   curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
   export PATH="/usr/local/go/bin:$PATH"
   ```
2. Install the launcher on PATH. It compiles `cli/` from source on every invocation, so no
   stale binary can ever drift (the send-message handler and its bubble lint run inside the
   daemon; a static binary left the daemon executing weeks-old code after the source changed).
   CGO/FTS5 build flags live in `cli/cgo-env.sh`, sourced by the launcher.
   ```bash
   mkdir -p ~/.local/bin && ln -sf ~/agent/skills/telegram/telegram ~/.local/bin/telegram
   telegram --help >/dev/null   # warm the build cache; a compile error surfaces HERE, loudly
   ```
   Never `go build` a static binary onto PATH; the launcher is the only entry point.
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

   **Deploying source changes:** there is no build step. The launcher recompiles `cli/` from
   source on every invocation (Go's build cache keeps an unchanged rebuild well under a second),
   so an edit is picked up by the next invocation. For the daemon (which holds the running
   process), `telegram daemon restart` bounces it onto the fresh build; the restart quits the
   watchdog first and brings it back after, so the watchdog can never race you into two daemons
   (two pollers, Telegram 409 Conflict).
