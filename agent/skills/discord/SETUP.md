# Discord Setup

1. Install the CLI:
   ```bash
   uv tool install --editable ~/agent/skills/discord/cli
   ```
2. Have the user create the bot: open https://discord.com/developers/applications, click **New Application**, name it Vesta.
3. In the **Bot** tab:
   - copy the **token** (shown once; use **Reset Token** to re-reveal),
   - under **Privileged Gateway Intents**, toggle **MESSAGE CONTENT INTENT** on (required to read channel messages; no review needed at personal scale).
4. Store the token (also validates it and prints the invite url):
   ```bash
   discord authenticate --token "<BOT_TOKEN>"
   ```
5. The user opens the printed invite url, picks their server, and authorizes. DMs additionally require sharing at least one server with Vesta.
6. Start the daemon:
   ```bash
   screen -dmS discord discord serve --notifications-dir ~/agent/notifications
   ```
7. Add that same line to the `## Services` section of `~/agent/skills/restart/SKILL.md` so the daemon survives restarts.
8. Send a test message both ways (channel and DM) to confirm.
