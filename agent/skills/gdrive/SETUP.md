# Google Drive Setup

Headless OAuth using rclone's built-in Google client (no Google Cloud project needed). The user signs in on their phone; the agent never needs a browser.

1. Check rclone: `rclone version`. If missing, install `unzip` first, then `curl -fsSL https://rclone.org/install.sh | bash` (the installer fails silently without unzip).

2. Ask the user which access they want:
   - `drive` (default): full read/write. Needed for uploads and edits.
   - `drive.readonly`: read and download only. Safer if they only want you to look things up.

3. Start sign-in:
   ```bash
   python3 ~/agent/skills/gdrive/scripts/gdrive_setup.py auth-start --scope drive
   ```
   This runs `rclone authorize drive --auth-no-open-browser` in the background (listener on `127.0.0.1:53682`), resolves its local link to the real `accounts.google.com` URL, checks the requested scope, and prints it.

4. Send the user the Google URL with these instructions:
   - Open it on your phone, pick your Google account, tap Allow.
   - You'll land on a page that won't load (`http://127.0.0.1:53682/?state=...&code=...`). That is expected.
   - Copy the whole address from the address bar and send it to me.

   Google may show an "rclone wants access" screen; that's rclone's own verified app.

5. Finish with the pasted URL:
   ```bash
   python3 ~/agent/skills/gdrive/scripts/gdrive_setup.py auth-finish 'http://127.0.0.1:53682/?state=...&code=...'
   ```
   This replays the URL to the local listener, which exchanges the code for a token. The script then writes a `[gdrive]` remote (`type = drive`, `scope`, `token`) into the default rclone config (`rclone config file`, mode 600) and runs `status`.

6. Verify: `rclone lsf gdrive: --max-depth 1`

## Troubleshooting
- **Code expired / state mismatch / listener not reachable**: the code is single-use and the listener only lives for one attempt. Run `cancel`, then `auth-start` again and send a fresh link.
- **Port 53682 busy**: `gdrive_setup.py cancel`, or kill whatever holds the port.
- **User pasted only the code, or a truncated URL**: ask for the full address bar contents, including `state=` and `code=`.
- **Switch scope later**: rerun `auth-start --scope ...` and `auth-finish`; it overwrites the `[gdrive]` section.
- Remote name and data dir can be overridden with `GDRIVE_REMOTE_NAME` and `GDRIVE_DATA_DIR`.
