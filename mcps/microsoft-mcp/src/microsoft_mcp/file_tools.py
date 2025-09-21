"""OneDrive file-related tools for Microsoft MCP"""

import pathlib as pl
from typing import Any
from mcp.server.fastmcp import FastMCP
from . import graph

mcp = FastMCP("microsoft-mcp")


@mcp.tool()
def list_files(
    account_id: str, path: str = "/", limit: int = 50
) -> list[dict[str, Any]]:
    """List files and folders in OneDrive"""

    endpoint = (
        "/me/drive/root/children"
        if path == "/"
        else f"/me/drive/root:/{path}:/children"
    )
    params = {
        "$top": min(limit, 100),
        "$select": "id,name,size,lastModifiedDateTime,folder,file,@microsoft.graph.downloadUrl",
    }

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    return [
        {
            "id": item["id"],
            "name": item["name"],
            "type": "folder" if "folder" in item else "file",
            "size": item.get("size", 0),
            "modified": item.get("lastModifiedDateTime"),
            "download_url": item.get("@microsoft.graph.downloadUrl"),
        }
        for item in items
    ]


@mcp.tool()
def get_file(file_id: str, account_id: str, download_path: str) -> dict[str, Any]:
    """Download a file from OneDrive to local path"""
    import subprocess

    metadata = graph.request("GET", f"/me/drive/items/{file_id}", account_id)
    if not metadata:
        raise ValueError(f"File with ID {file_id} not found")

    download_url = metadata.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise ValueError("No download URL available for this file")

    try:
        subprocess.run(
            ["curl", "-L", "-o", download_path, download_url],
            check=True,
            capture_output=True,
        )

        return {
            "path": download_path,
            "name": metadata.get("name", "unknown"),
            "size_mb": round(metadata.get("size", 0) / (1024 * 1024), 2),
            "mime_type": metadata.get("file", {}).get("mimeType") if metadata else None,
        }
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to download file: {e.stderr.decode()}")


@mcp.tool()
def create_file(
    onedrive_path: str, local_file_path: str, account_id: str
) -> dict[str, Any]:
    """Upload a local file to OneDrive"""
    path = pl.Path(local_file_path).expanduser().resolve()
    data = path.read_bytes()
    result = graph.upload_large_file(
        f"/me/drive/root:/{onedrive_path}:", data, account_id
    )
    if not result:
        raise ValueError(f"Failed to create file at path: {onedrive_path}")
    return result


@mcp.tool()
def update_file(file_id: str, local_file_path: str, account_id: str) -> dict[str, Any]:
    """Update OneDrive file content from a local file"""
    path = pl.Path(local_file_path).expanduser().resolve()
    data = path.read_bytes()
    result = graph.upload_large_file(f"/me/drive/items/{file_id}", data, account_id)
    if not result:
        raise ValueError(f"Failed to update file with ID: {file_id}")
    return result


@mcp.tool()
def delete_file(file_id: str, account_id: str) -> dict[str, str]:
    """Delete a file or folder"""
    graph.request("DELETE", f"/me/drive/items/{file_id}", account_id)
    return {"status": "deleted"}


@mcp.tool()
def search_files(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search for files in OneDrive using the modern search API."""

    items = list(graph.search_query(query, ["driveItem"], account_id, limit))

    return [
        {
            "id": item["id"],
            "name": item["name"],
            "type": "folder" if "folder" in item else "file",
            "size": item.get("size", 0),
            "modified": item.get("lastModifiedDateTime"),
            "download_url": item.get("@microsoft.graph.downloadUrl"),
        }
        for item in items
    ]
