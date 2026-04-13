# Telegram Setup

1. Install dependencies (gcc for CGO and Go from https://go.dev/dl/. NOT the system package manager):
   ```bash
   apt-get install -y gcc
   ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
   curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
   export PATH="/usr/local/go/bin:$PATH"
   ```
2. Build the Telegram CLI (CGO required for SQLite with FTS5):
   ```bash
   cd ~/vesta/skills/telegram/cli && CGO_ENABLED=1 CGO_CFLAGS="-DSQLITE_ENABLE_FTS5" CGO_LDFLAGS="-lm" go build -o /usr/local/bin/telegram .
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
   screen -dmS telegram telegram serve --notifications-dir ~/vesta/notifications
   ```
5. **Important**: The user must `/start` the bot from their Telegram account before Vesta can send them messages. After that first interaction, Vesta can message them anytime (including autonomously, e.g., morning reports).
6. Add to `~/vesta/prompts/restart.md`:
   ```
   screen -dmS telegram telegram serve --notifications-dir ~/vesta/notifications
   ```
