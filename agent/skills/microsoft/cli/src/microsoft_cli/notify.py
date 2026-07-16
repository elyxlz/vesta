"""Per-account notify-folder selection for the monitor.

The watch list lives at ~/.microsoft/notify.json as {"<email>": ["inbox", ...]}.
When an account has no entry the monitor watches INBOX only, so existing
installs keep their current behavior with no migration. The monitor re-reads
this file every cycle, so edits apply without a restart.
"""

import json
from pathlib import Path

import httpx

from . import auth, folders
from .config import Config

DEFAULT_NOTIFY_FOLDERS = ["inbox"]


def notify_file_for(config: Config) -> Path:
    return config.data_dir / "notify.json"


def _load(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(path: Path, data: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def get_notify_folders(path: Path, account_email: str) -> list[str]:
    data = _load(path)
    return data[account_email] if account_email in data else list(DEFAULT_NOTIFY_FOLDERS)


def list_notify(config: Config, client: httpx.Client, *, account_email: str) -> dict[str, object]:
    auth.get_account_id_by_email(account_email, config.cache_file)
    return {"account": account_email, "folders": get_notify_folders(notify_file_for(config), account_email)}


def add_notify(
    config: Config, client: httpx.Client, *, account_email: str, folder: str | None = None, all_folders: bool = False
) -> dict[str, object]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    path = notify_file_for(config)
    data = _load(path)

    if all_folders:
        server_folders = folders.fetch_folders_cfg(config, client, account_id)
        data[account_email] = [f["displayName"] for f in server_folders if "displayName" in f]
        _save(path, data)
        return {"account": account_email, "folders": data[account_email]}

    if not folder:
        raise ValueError("Specify --folder or --all")

    server_folders = folders.fetch_folders_cfg(config, client, account_id)
    known_names = set(config.folders) | {f["displayName"].casefold() for f in server_folders if "displayName" in f}
    known_ids = {f["id"] for f in server_folders if "id" in f}
    if folder.casefold() not in known_names and folder not in known_ids:
        raise ValueError(f"Folder '{folder}' not found on the server")

    current = data[account_email] if account_email in data else list(DEFAULT_NOTIFY_FOLDERS)
    if not any(f.casefold() == folder.casefold() for f in current):
        current.append(folder)
    data[account_email] = current
    _save(path, data)
    return {"account": account_email, "folders": current}


def remove_notify(config: Config, client: httpx.Client, *, account_email: str, folder: str) -> dict[str, object]:
    auth.get_account_id_by_email(account_email, config.cache_file)
    path = notify_file_for(config)
    data = _load(path)
    current = data[account_email] if account_email in data else list(DEFAULT_NOTIFY_FOLDERS)
    current = [f for f in current if f.casefold() != folder.casefold()]
    data[account_email] = current
    _save(path, data)
    return {"account": account_email, "folders": current}
