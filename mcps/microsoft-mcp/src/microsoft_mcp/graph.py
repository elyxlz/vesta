import httpx
import time
import pathlib as pl
from typing import Any
from collections.abc import Iterator
from .auth import get_token
from .settings import MicrosoftSettings


def _retry_http_call(call_func, max_retries: int = 3):
    """Helper to retry HTTP calls with exponential backoff and rate limit handling"""
    retry_count = 0
    while retry_count <= max_retries:
        try:
            response = call_func()

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                if retry_count < max_retries:
                    time.sleep(min(retry_after, 60))
                    retry_count += 1
                    continue

            if response.status_code >= 500 and retry_count < max_retries:
                wait_time = (2**retry_count) * 1
                time.sleep(wait_time)
                retry_count += 1
                continue

            response.raise_for_status()
            return response

        except httpx.HTTPStatusError as e:
            if retry_count < max_retries and e.response.status_code >= 500:
                wait_time = (2**retry_count) * 1
                time.sleep(wait_time)
                retry_count += 1
                continue
            raise

    return None


def request(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    method: str,
    path: str,
    account_id: str | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: bytes | None = None,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    headers = {
        "Authorization": f"Bearer {get_token(cache_file, scopes, settings, account_id=account_id)}",
    }

    if method == "GET":
        if "$search" in (params or {}):
            headers["Prefer"] = 'outlook.body-content-type="text"'
        elif "body" in (params or {}).get("$select", ""):
            headers["Prefer"] = 'outlook.body-content-type="text"'
    else:
        headers["Content-Type"] = "application/json" if json else "application/octet-stream"

    if params and ("$search" in params or "contains(" in params.get("$filter", "") or "/any(" in params.get("$filter", "")):
        headers["ConsistencyLevel"] = "eventual"
        params.setdefault("$count", "true")

    response = _retry_http_call(
        lambda: client.request(
            method=method,
            url=f"{base_url}{path}",
            headers=headers,
            params=params,
            json=json,
            content=data,
        ),
        max_retries,
    )

    if response and response.content:
        return response.json()
    return None


def request_paginated(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    path: str,
    account_id: str | None = None,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Make paginated requests following @odata.nextLink"""
    items_returned = 0
    next_link = None

    while True:
        if next_link:
            result = request(client, cache_file, scopes, settings, base_url, "GET", next_link.replace(base_url, ""), account_id)
        else:
            result = request(client, cache_file, scopes, settings, base_url, "GET", path, account_id, params=params)

        if not result:
            break

        if "value" in result:
            for item in result["value"]:
                if limit and items_returned >= limit:
                    return
                yield item
                items_returned += 1

        next_link = result.get("@odata.nextLink")
        if not next_link:
            break


def download_raw(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    path: str,
    account_id: str | None = None,
    max_retries: int = 3,
) -> bytes:
    headers = {"Authorization": f"Bearer {get_token(cache_file, scopes, settings, account_id=account_id)}"}

    response = _retry_http_call(lambda: client.get(f"{base_url}{path}", headers=headers), max_retries)
    if not response:
        raise ValueError("Failed to download file after all retries")
    return response.content


def _do_chunked_upload(
    client: httpx.Client,
    upload_url: str,
    data: bytes,
    headers: dict[str, str],
    upload_chunk_size: int,
) -> dict[str, Any]:
    """Internal helper for chunked uploads"""
    file_size = len(data)

    for i in range(0, file_size, upload_chunk_size):
        chunk_start = i
        chunk_end = min(i + upload_chunk_size, file_size)
        chunk = data[chunk_start:chunk_end]

        chunk_headers = headers.copy()
        chunk_headers["Content-Length"] = str(len(chunk))
        chunk_headers["Content-Range"] = f"bytes {chunk_start}-{chunk_end - 1}/{file_size}"

        response = _retry_http_call(lambda: client.put(upload_url, content=chunk, headers=chunk_headers), 3)
        if response:
            if response.status_code in (200, 201):
                return response.json()
            break

    raise ValueError("Upload completed but no final response received")


def create_upload_session(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    path: str,
    account_id: str | None = None,
    item_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an upload session for large files"""
    payload = {"item": item_properties or {}}
    result = request(client, cache_file, scopes, settings, base_url, "POST", f"{path}/createUploadSession", account_id, json=payload)
    if not result:
        raise ValueError("Failed to create upload session")
    return result


def upload_large_file(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    upload_chunk_size: int,
    path: str,
    data: bytes,
    account_id: str | None = None,
    item_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upload a large file using upload sessions"""
    file_size = len(data)

    if file_size <= upload_chunk_size:
        result = request(client, cache_file, scopes, settings, base_url, "PUT", f"{path}/content", account_id, data=data)
        if not result:
            raise ValueError("Failed to upload file")
        return result

    session = create_upload_session(client, cache_file, scopes, settings, base_url, path, account_id, item_properties)
    upload_url = session["uploadUrl"]

    headers = {"Authorization": f"Bearer {get_token(cache_file, scopes, settings, account_id=account_id)}"}
    return _do_chunked_upload(client, upload_url, data, headers, upload_chunk_size)


def create_mail_upload_session(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    message_id: str,
    attachment_item: dict[str, Any],
    account_id: str | None = None,
) -> dict[str, Any]:
    """Create an upload session for large mail attachments"""
    result = request(
        client,
        cache_file,
        scopes,
        settings,
        base_url,
        "POST",
        f"/me/messages/{message_id}/attachments/createUploadSession",
        account_id,
        json={"AttachmentItem": attachment_item},
    )
    if not result:
        raise ValueError("Failed to create mail attachment upload session")
    return result


def upload_large_mail_attachment(
    client: httpx.Client,
    cache_file: pl.Path,
    scopes: list[str],
    settings: MicrosoftSettings,
    base_url: str,
    upload_chunk_size: int,
    message_id: str,
    name: str,
    data: bytes,
    account_id: str | None = None,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    """Upload a large mail attachment using upload sessions"""
    file_size = len(data)

    attachment_item = {
        "attachmentType": "file",
        "name": name,
        "size": file_size,
        "contentType": content_type,
    }

    session = create_mail_upload_session(client, cache_file, scopes, settings, base_url, message_id, attachment_item, account_id)
    upload_url = session["uploadUrl"]

    headers = {"Authorization": f"Bearer {get_token(cache_file, scopes, settings, account_id=account_id)}"}
    return _do_chunked_upload(client, upload_url, data, headers, upload_chunk_size)
