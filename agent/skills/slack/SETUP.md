# Slack Setup

1. Install the CLI:
   ```bash
   uv tool install --editable ~/agent/skills/slack/cli
   ```
2. Have the user create the Slack app: open https://api.slack.com/apps, click **Create New App**, pick **From a manifest**, choose their workspace, and paste:
   ```yaml
   display_information:
     name: Vesta
   features:
     bot_user:
       display_name: Vesta
       always_online: true
   oauth_config:
     scopes:
       bot:
         - chat:write
         - channels:history
         - channels:read
         - groups:history
         - groups:read
         - im:history
         - im:read
         - im:write
         - mpim:history
         - mpim:read
         - users:read
   settings:
     event_subscriptions:
       bot_events:
         - message.channels
         - message.groups
         - message.im
         - message.mpim
     socket_mode_enabled: true
   ```
3. In **Install App**, install it to the workspace and copy the **Bot User OAuth Token** (`xoxb-...`).
4. In **Basic Information**, under **App-Level Tokens**, generate a token with the `connections:write` scope and copy it (`xapp-...`).
5. Store both tokens (also validates them):
   ```bash
   slack authenticate --bot-token "xoxb-..." --app-token "xapp-..."
   ```
6. Start the daemon:
   ```bash
   screen -dmS slack slack serve --notifications-dir ~/agent/notifications
   ```
7. Add that same line to the `## Services` section of `~/agent/skills/restart/SKILL.md` so the daemon survives restarts.
8. The user invites Vesta to the channels that matter (`/invite @Vesta` in Slack); DMs work immediately. Send a test DM both ways to confirm.
