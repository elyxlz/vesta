---
name: gdrive
description: Google Drive files: list, search, read, download, upload, and sync via rclone.
---

# Google Drive

Access the user's Google Drive via rclone (remote `gdrive:`). No daemon needed.

**Setup**: See [SETUP.md](SETUP.md)

**Check it works**: `python3 ~/agent/skills/gdrive/scripts/gdrive_setup.py status`

## Usage

```bash
rclone lsf gdrive:                                   # top level
rclone lsf gdrive:Documents --max-depth 2            # browse
rclone lsf -R gdrive: --include "*invoice*" --ignore-case --files-only   # search by name
rclone lsf -R gdrive: --include "*.pdf" --max-age 30d                    # recent PDFs
rclone cat gdrive:Notes/todo.txt                     # read a file to stdout
rclone cat gdrive:big.log --head 2000                # first 2000 chars only
rclone copy gdrive:Documents/report.pdf /tmp/gdrive/ # download
rclone copy /tmp/out.pdf gdrive:Documents/           # upload
rclone about gdrive:                                 # quota
```

**Google Docs/Sheets/Slides** have no native file. rclone exports them on download, picking the first matching format from `--drive-export-formats` (default `docx,xlsx,pptx,svg`):
```bash
rclone copy gdrive:Plans /tmp/plans --drive-export-formats docx,xlsx,pdf
rclone cat "gdrive:Meeting notes.docx" --drive-export-formats txt   # read a Doc as text
```
Listings show Docs with the export extension (e.g. `Meeting notes.docx`).

**Shared with me**: add `--drive-shared-with-me`, e.g. `rclone lsf gdrive: --drive-shared-with-me`.

## Safety
- Never run `rclone sync`, `delete`, `deletefile`, `purge`, `rmdir(s)`, or `move` against `gdrive:` without explicit user approval. `sync` deletes files on the destination.
- Prefer `rclone copy` (never deletes). Copy to a local scratch dir rather than editing in place.
- Run anything that writes to the remote with `--dry-run` first and show the user what would change.
- If set up with `drive.readonly`, writes fail with a permission error; that is expected.

## Notes
- Search is by name/path only; there is no full-text search. Narrow with a folder path and `--max-depth` on big drives.
- Quote paths with spaces. Drive allows duplicate names in one folder; rclone warns about them.
- Token refreshes automatically. If it is revoked or expires (`invalid_grant`), rerun the setup flow.

### File Organization
[How the user organizes their Google Drive files]

## Known issues
- rclone's shared Google client_id is being retired. If `rclone about gdrive:` starts failing with `invalid_client`, create your own client_id (https://rclone.org/drive/#making-your-own-client-id) and re-auth.
- `authorize.log` in the data dir holds the token while a sign-in is pending. Never print it.
- Drives often hold sensitive documents (bank statements, IDs, credentials). Open only what a task needs, and never quote contents elsewhere.
