---
name: onedrive
description: This skill should be used when the user asks about "OneDrive", "cloud files", "sync files", "mount drive", or needs to access, mount, or manage OneDrive cloud storage.
---

# OneDrive

Access OneDrive files via rclone. FUSE mounting works if the container was created with `--privileged`.

**Setup**: See [SETUP.md](SETUP.md)

**Mount on restart**: `rclone mount onedrive: ~/onedrive --daemon --vfs-cache-mode full`

## Usage

```bash
rclone ls onedrive:
rclone copy onedrive:Documents/file.pdf /tmp/
rclone copy /tmp/file.pdf onedrive:Documents/
rclone tree onedrive: --max-depth 2
```

## Notes
- Do NOT use `rclone config` or `rclone authorize` — neither handles device code flow in a headless container
- Use tenant `common` not org tenant for personal accounts
- Keep scopes minimal (`Files.ReadWrite.All offline_access`) — extra scopes can cause the device code to fail with a misleading "expired" error
- Install `unzip` before rclone or the install script fails silently
- rclone refreshes tokens automatically once the initial config is set up

### File Organization
[How the user organizes their OneDrive files]
