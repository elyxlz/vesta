# WhatsApp Setup

1. Install dependencies (gcc for CGO, ffmpeg for voice note transcription, and Go from https://go.dev/dl/ — NOT the system package manager):
   ```bash
   apt-get install -y gcc ffmpeg
   ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
   curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
   export PATH="/usr/local/go/bin:$PATH"
   ```
2. Build the WhatsApp CLI (CGO required for SQLite with FTS5):
   ```bash
   cd ~/vesta/skills/whatsapp/cli && CGO_ENABLED=1 CGO_CFLAGS="-DSQLITE_ENABLE_FTS5" CGO_LDFLAGS="-lm" go build -o /usr/local/bin/whatsapp .
   ```
3. Download the whisper model for voice memo transcription (~466 MB):
   ```bash
   curl -fSL "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" -o /usr/local/share/ggml-small.bin
   ```
4. Start the daemon and authenticate:
   ```bash
   screen -dmS whatsapp whatsapp serve
   sleep 3
   whatsapp authenticate
   ```
   **Before showing the QR code**, confirm with the user that they should scan it from a dedicated WhatsApp account for the assistant — NOT their personal WhatsApp. This can be a throwaway phone with a new SIM, a work profile (Android) WhatsApp with an eSIM, or any separate number. Scanning from their personal account would link their own WhatsApp to Vesta and she'd be reading/sending from their personal chats.

   If not authenticated, a QR code image is saved to `~/vesta/data/whatsapp/qr-code.png`.
   Serve it on any available port (host network is shared):
   ```bash
   screen -dmS qr-server bash -c 'cd ~/vesta/data/whatsapp && uv run python3 -m http.server 8888'
   ```
   Tell the user to open `http://localhost:8888/qr-code.png` and scan immediately.

   **QR codes expire in ~20 seconds.** Warn the user to have WhatsApp ready before opening the link.

   After the user says they scanned, wait 10 seconds then check:
   ```bash
   sleep 10 && whatsapp authenticate
   ```
   **NEVER restart the daemon after the user has scanned** — restarting invalidates the session. If `authenticate` still says not authenticated, wait longer and check again (up to 30 seconds). Only restart the daemon if the user confirms they didn't scan in time or the QR visually expired.

   Kill the HTTP server once authenticated: `screen -S qr-server -X quit`
5. Add to `~/vesta/prompts/restart.md`:
   ```
   screen -dmS whatsapp whatsapp serve --notifications-dir ~/vesta/notifications
   ```
