#!/usr/bin/env python3
"""
Sync ~/vesta to OneDrive using Microsoft Graph API.
Uses the existing MSAL token cache from the microsoft skill.

Provides failsafe file-level recovery independent of container backups.
OneDrive retains version history for each file, so every sync creates
a recoverable snapshot without manual intervention.
"""

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path.home() / 'vesta' / 'skills' / 'microsoft' / 'cli' / 'src'))

LOCAL_DIR = pathlib.Path(os.environ.get('ONEDRIVE_BACKUP_SOURCE', str(pathlib.Path.home() / 'vesta')))
ONEDRIVE_FOLDER = os.environ.get('ONEDRIVE_BACKUP_FOLDER', 'Okami/okami-vesta')
CHUNK_SIZE = 3932160  # 3.75MB — must be multiple of 320KB for Graph API chunked upload

# Files/dirs to exclude from sync
EXCLUDE = {
    '.venv', '__pycache__', '.git', 'node_modules',
    'uv.lock', '.lock', 'CACHEDIR.TAG',
}


def get_token():
    """Acquire a Graph API token using the microsoft skill's MSAL cache."""
    from microsoft_cli.settings import MicrosoftSettings
    import msal

    settings = MicrosoftSettings()
    cache_file = pathlib.Path.home() / '.microsoft' / 'auth_cache.bin'

    cache = msal.SerializableTokenCache()
    try:
        cache.deserialize(cache_file.read_text())
    except Exception:
        pass

    app = msal.PublicClientApplication(
        settings.microsoft_mcp_client_id,
        authority='https://login.microsoftonline.com/common',
        token_cache=cache
    )

    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("No authenticated accounts — run: microsoft auth add --account <email>")

    result = app.acquire_token_silent(['Files.ReadWrite'], account=accounts[0])
    if not result or 'access_token' not in result:
        raise RuntimeError("Could not refresh Files.ReadWrite token — re-authenticate with microsoft skill")

    if cache.has_state_changed:
        cache_file.write_text(cache.serialize())

    return result['access_token']


def graph_request(token, method, path, data=None, content_type='application/json'):
    """Make a Microsoft Graph API request."""
    url = f'https://graph.microsoft.com/v1.0{path}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': content_type,
    }
    body = None
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = data
        else:
            body = json.dumps(data).encode()

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors='replace')
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {body_text[:200]}")


def ensure_folder(token, onedrive_path):
    """Create folder and all parents if they don't exist."""
    parts = onedrive_path.strip('/').split('/')
    for i in range(len(parts)):
        partial = '/'.join(parts[:i + 1])
        try:
            graph_request(token, 'GET', f"/me/drive/root:/{partial}")
        except RuntimeError:
            parent = '/'.join(parts[:i]) if i > 0 else ''
            parent_path = f"/me/drive/root:/{parent}:/children" if parent else "/me/drive/root/children"
            graph_request(token, 'POST', parent_path, {
                'name': parts[i],
                'folder': {},
                '@microsoft.graph.conflictBehavior': 'replace'
            })


def upload_file(token, local_path, onedrive_path):
    """Upload a file to OneDrive. Uses simple upload for small files, chunked for large."""
    size = local_path.stat().st_size
    encoded_path = urllib.parse.quote(onedrive_path)

    if size == 0:
        # Skip empty files — Graph API rejects zero-byte uploads via upload sessions
        graph_request(
            token, 'PUT',
            f"/me/drive/root:/{encoded_path}:/content",
            data=b'',
            content_type='application/octet-stream'
        )
        return

    if size < CHUNK_SIZE:
        # Simple upload (< 3.75MB)
        data = local_path.read_bytes()
        graph_request(
            token, 'PUT',
            f"/me/drive/root:/{encoded_path}:/content",
            data=data,
            content_type='application/octet-stream'
        )
    else:
        # Chunked upload session (>= 3.75MB)
        session = graph_request(token, 'POST',
            f"/me/drive/root:/{encoded_path}:/createUploadSession",
            {'item': {'@microsoft.graph.conflictBehavior': 'replace'}}
        )
        upload_url = session['uploadUrl']
        with open(local_path, 'rb') as f:
            offset = 0
            while offset < size:
                chunk = f.read(CHUNK_SIZE)
                end = offset + len(chunk) - 1
                req = urllib.request.Request(
                    upload_url,
                    data=chunk,
                    headers={
                        'Content-Range': f'bytes {offset}-{end}/{size}',
                        'Content-Length': str(len(chunk)),
                        'Content-Type': 'application/octet-stream'
                    },
                    method='PUT'
                )
                with urllib.request.urlopen(req) as r:
                    r.read()
                offset += len(chunk)


def should_exclude(path):
    """Check if a path should be excluded from sync."""
    return any(part in EXCLUDE for part in path.parts)


def sync():
    """Sync local directory to OneDrive."""
    print(f"[OneDrive sync] starting — {LOCAL_DIR} → OneDrive/{ONEDRIVE_FOLDER}/")
    token = get_token()
    print("[OneDrive sync] token OK")

    # Ensure root folder exists
    ensure_folder(token, ONEDRIVE_FOLDER)

    uploaded = 0
    skipped = 0
    errors = 0

    for local_file in sorted(LOCAL_DIR.rglob('*')):
        if not local_file.is_file():
            continue
        rel = local_file.relative_to(LOCAL_DIR)
        if should_exclude(rel):
            skipped += 1
            continue

        remote_path = f"{ONEDRIVE_FOLDER}/{rel.as_posix()}"

        for attempt in range(3):
            try:
                upload_file(token, local_file, remote_path)
                uploaded += 1
                if uploaded % 50 == 0:
                    print(f"[OneDrive sync] {uploaded} files uploaded...")
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                print(f"[OneDrive sync] ERROR {rel}: {e}")
                errors += 1

    print(f"[OneDrive sync] done — {uploaded} uploaded, {skipped} skipped, {errors} errors")


if __name__ == '__main__':
    sync()
