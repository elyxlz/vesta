"""Mail-folder commands for Microsoft CLI (list, counts, create/rename/delete).

Folder resolution follows the graph.py primitive/`_cfg` split so the monitor
thread (which holds raw connection primitives, not a Config) and the command
modules (which hold a Config) can both resolve a user-supplied folder token to a
Graph folder path segment.
"""

from typing import Any

import httpx

from . import auth, graph
from .config import Config

_FOLDER_FIELDS = ("id", "displayName", "parentFolderId", "totalItemCount", "unreadItemCount")
_FOLDER_SELECT = ",".join(_FOLDER_FIELDS)


def _project(folder: dict[str, Any]) -> dict[str, Any]:
    return {k: folder[k] for k in _FOLDER_FIELDS if k in folder}


def _flatten(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten top-level folders plus one expanded level of child folders."""
    out: list[dict[str, Any]] = []
    for folder in raw:
        out.append(_project(folder))
        out.extend(_project(child) for child in (folder["childFolders"] if "childFolders" in folder else []))
    return out


def fetch_folders(
    client: httpx.Client,
    cache_file,
    scopes: list[str],
    base_url: str,
    account_id: str,
) -> list[dict[str, Any]]:
    result = graph.request(
        graph.GraphConn(client, cache_file, scopes, base_url),
        "GET",
        "/me/mailFolders",
        account_id,
        params={"$top": 100, "$expand": "childFolders", "$select": _FOLDER_SELECT},
    )
    return _flatten(result["value"] if result and "value" in result else [])


def resolve_folder_id(
    client: httpx.Client,
    cache_file,
    scopes: list[str],
    base_url: str,
    folders_map: dict[str, str],
    account_id: str,
    folder: str,
) -> str:
    """Map a well-known key, a display name, or a raw folder id to a path segment."""
    key = folder.casefold()
    if key in folders_map:
        return folders_map[key]
    for candidate in fetch_folders(client, cache_file, scopes, base_url, account_id):
        if "displayName" in candidate and candidate["displayName"].casefold() == key:
            return candidate["id"]
    return folder


def fetch_folders_cfg(config: Config, client: httpx.Client, account_id: str) -> list[dict[str, Any]]:
    return fetch_folders(client, config.cache_file, config.scopes, config.base_url, account_id)


def resolve_folder_id_cfg(config: Config, client: httpx.Client, account_id: str, folder: str) -> str:
    return resolve_folder_id(client, config.cache_file, config.scopes, config.base_url, config.folders, account_id, folder)


def list_folders(config: Config, client: httpx.Client, *, account_email: str) -> list[dict[str, Any]]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    return fetch_folders_cfg(config, client, account_id)


def folder_status(config: Config, client: httpx.Client, *, account_email: str, folder: str) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    folder_id = resolve_folder_id_cfg(config, client, account_id, folder)
    result = graph.request_cfg(
        config,
        client,
        "GET",
        f"/me/mailFolders/{folder_id}",
        account_id,
        params={"$select": "id,displayName,totalItemCount,unreadItemCount"},
    )
    if not result:
        raise ValueError(f"Folder '{folder}' not found")
    return result


def create_folder(config: Config, client: httpx.Client, *, account_email: str, name: str, parent_id: str | None = None) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    path = f"/me/mailFolders/{parent_id}/childFolders" if parent_id else "/me/mailFolders"
    result = graph.request_cfg(config, client, "POST", path, account_id, json={"displayName": name})
    if not result:
        raise ValueError(f"Failed to create folder '{name}'")
    return result


def rename_folder(config: Config, client: httpx.Client, *, account_email: str, folder_id: str, name: str) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    result = graph.request_cfg(config, client, "PATCH", f"/me/mailFolders/{folder_id}", account_id, json={"displayName": name})
    return result or {"status": "renamed", "id": folder_id, "displayName": name}


def delete_folder(config: Config, client: httpx.Client, *, account_email: str, folder_id: str) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    graph.request_cfg(config, client, "DELETE", f"/me/mailFolders/{folder_id}", account_id)
    return {"status": "deleted", "id": folder_id}
