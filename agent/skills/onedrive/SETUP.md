# OneDrive Setup

1. Install dependencies:
   ```bash
   apt-get install -y unzip fuse3
   curl https://rclone.org/install.sh | bash
   ```
   unzip must be installed before rclone or the installer fails silently.

2. You need an Azure App Registration with `Files.ReadWrite.All` permission and "Allow public client flows" enabled. If the Microsoft skill is already set up, reuse that app — just add the `Files.ReadWrite.All` permission to it.

3. Write a minimal rclone config (do NOT use `rclone config` or `rclone authorize` — neither supports device code flow properly in a headless container):
   ```bash
   mkdir -p ~/.config/rclone
   cat > ~/.config/rclone/rclone.conf << EOF
   [onedrive]
   type = onedrive
   client_id = <CLIENT_ID>
   tenant = common
   EOF
   ```

4. Authenticate using the Microsoft device code flow directly:
   ```bash
   curl -s -X POST "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "client_id=<CLIENT_ID>&scope=Files.ReadWrite.All%20offline_access"
   ```
   This returns a `user_code` and `device_code`. Tell the user to go to microsoft.com/devicelogin and enter the `user_code`.

5. Poll for the token:
   ```bash
   curl -s -X POST "https://login.microsoftonline.com/common/oauth2/v2.0/token" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=<CLIENT_ID>&device_code=<DEVICE_CODE>"
   ```
   Poll every 5 seconds. Returns `authorization_pending` until the user signs in, then returns the token JSON.

6. Write the token into rclone config and get drive info:
   - Format token as JSON with `access_token`, `token_type`, `refresh_token`, `expiry` fields
   - Get `drive_id` from: `curl -H "Authorization: Bearer <ACCESS_TOKEN>" "https://graph.microsoft.com/v1.0/me/drive"`
   - Write everything into `rclone.conf`: token, drive_id, drive_type

7. Mount:
   ```bash
   mkdir -p ~/onedrive
   rclone mount onedrive: ~/onedrive --daemon --vfs-cache-mode full
   ```
8. Add to `~/vesta/prompts/restart.md`:
   ```
   rclone mount onedrive: ~/onedrive --daemon --vfs-cache-mode full
   ```
