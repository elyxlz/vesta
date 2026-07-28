# Telegram Setup

Everything the build needs (Go, gcc) ships in the agent image; install nothing,
download nothing.

1. Warm the launcher's build cache. Agent startup puts `telegram` on PATH, and the launcher
   compiles `cli/` from source on every invocation, so no stale binary can ever drift (the
   send-message handler and its bubble lint run inside the daemon; a static binary left the
   daemon executing weeks-old code after the source changed). CGO/FTS5 build flags live in
   `cli/cgo-env.sh`, sourced by the launcher.
   ```bash
   telegram --help >/dev/null   # a compile error surfaces HERE, loudly
   ```
   Never `go build` a static binary onto PATH; the launcher is the only entry point.
2. Create a Telegram bot and authenticate:
   - Tell the user to message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow the prompts to create a bot
   - Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
   - Save the token:
     ```bash
     telegram authenticate --token "<BOT_TOKEN>"
     ```
3. Start the daemon:
   ```bash
   telegram daemon start
   ```
   Idempotent (a running daemon is a no-op) and defaults `--notifications-dir` to `~/agent/notifications`. Check with `telegram daemon status`.
4. Then have them open the bot and send any message (hitting Start counts). Wait for that first inbound notification and confirm back on the new channel before declaring it live: the channel does not exist until you have replied to them on it.
5. Add to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`, on its own line:
   ```
   telegram daemon start
   ```
   That one line covers the watchdog too: `telegram daemon start` brings up
   `telegram-watchdog.sh` alongside the daemon, and `telegram daemon stop` ends both. The
   watchdog restarts the daemon if it dies, independent of the agent loop, so the channel
   self-heals even while the agent is busy or mid-restart. It is rate-limited (backs off after
   repeated restarts) and drops a notification when it acts. Especially important when Telegram
   is the primary/only channel.

   **Deploying source changes:** there is no build step. The launcher recompiles `cli/` from
   source on every invocation (Go's build cache keeps an unchanged rebuild well under a second),
   so an edit is picked up by the next invocation. For the daemon (which holds the running
   process), `telegram daemon restart` bounces it onto the fresh build; the watchdog goes down
   with the daemon and comes back with it, so it can never race you into two daemons (two
   pollers, Telegram 409 Conflict).
