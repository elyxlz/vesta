---
name: onedrive
description: This skill should be used when the user asks about "OneDrive", "cloud files", "sync files", "mount drive", or needs to access, mount, or manage OneDrive cloud storage.
---

# OneDrive

Access OneDrive files via rclone. FUSE mounting works if the container was created with `--privileged`.

## Setup

1. Install dependencies:
   ```bash
   apt-get install -y unzip fuse3
   curl https://rclone.org/install.sh | bash
   ```
   **unzip must be installed before rclone or the installer fails.**

2. Create an Azure App Registration at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
   - Name: anything (e.g. "Vesta")
   - Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
   - Redirect URI: leave blank (device flow doesn't need one)
   - Under "API permissions", add: `Files.ReadWrite.All`
   - Under "Authentication", enable "Allow public client flows"
   - Copy the **Application (client) ID**

3. Configure rclone with device code auth (NOT `rclone authorize` — that needs a browser redirect which doesn't work in the container):
   ```bash
   rclone config
   ```
   - Type: `onedrive`
   - Set `client_id` to the Application (client) ID from step 2
   - **Use tenant `common`** for personal Microsoft accounts (@outlook.com etc) — org tenant gives a cryptic identity provider error
   - Auth: choose **device code flow** — you get a code and a URL (`https://microsoft.com/devicelogin`), sign in there to authorize
   - You must also query `drive_id` from the Graph API or rclone fails with a useless error

4. Get the drive ID after auth:
   ```bash
   rclone lsd onedrive:
   ```
   If this works, the remote is configured correctly.

## Usage

```bash
# FUSE mount (requires --privileged container)
mkdir -p ~/onedrive
rclone mount onedrive: ~/onedrive --daemon --vfs-cache-mode full

# Direct access (always works, no FUSE needed)
rclone ls onedrive:
rclone copy onedrive:Documents/file.pdf /tmp/
rclone copy /tmp/file.pdf onedrive:Documents/
rclone tree onedrive: --max-depth 2
```

## Notes
- **Do NOT use `rclone authorize`** — it needs a localhost browser redirect, won't work with only port 7865 forwarded
- **Use device code flow** for auth — works headless in the container
- **Use tenant `common`** not org tenant for personal accounts
- **Set `client_id` and `drive_id`** in the rclone config or you get unhelpful errors
- **Install `unzip` before rclone** or the install script fails silently
- Direct rclone commands (ls, copy, tree) always work even without FUSE

### File Organization
[How the user organizes their OneDrive files]
