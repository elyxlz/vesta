import httpx
import os
import time
import logging
import pathlib as pl
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from collections.abc import Iterator
from .auth import get_token
from .settings import MicrosoftSettings

logger = logging.getLogger(__name__)


def get_default_iana_timezone() -> str:
    """Detect the local IANA timezone, falling back to UTC.

    Order: TZ env var, /etc/localtime symlink, /etc/timezone, UTC.
    """
    if tz := os.environ.get("TZ"):
        return tz
    localtime = pl.Path("/etc/localtime")
    if localtime.is_symlink():
        target = os.readlink(localtime)
        if "/zoneinfo/" in target:
            return target.split("/zoneinfo/")[-1]
    tz_file = pl.Path("/etc/timezone")
    if tz_file.exists():
        return tz_file.read_text().strip()
    return "UTC"


def convert_utc_string_to_local(value: str, tz_name: str | None = None) -> str:
    """Convert a UTC ISO datetime string to local-TZ ISO format.

    Accepts strings like '2026-04-28T08:01:18Z' or '2026-04-28T08:01:18.123Z' or
    '2026-04-28T08:01:18+00:00'. Returns the same instant rendered in `tz_name`
    (or the system local TZ if None). Returns the input unchanged on parse failure.
    """
    if not value or not isinstance(value, str):
        return value
    if tz_name is None:
        tz_name = get_default_iana_timezone()
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        return value
    return dt.astimezone(zone).isoformat()


# Field names that hold UTC datetime strings in MS Graph responses
_DATETIME_FIELDS = (
    "receivedDateTime",
    "sentDateTime",
    "lastModifiedDateTime",
    "createdDateTime",
    "completedDateTime",
)


def localize_datetime_fields(record: dict[str, Any], tz_name: str | None = None) -> None:
    """Mutate `record` in place: convert any known UTC datetime fields to local TZ.

    Only touches the top-level keys listed in `_DATETIME_FIELDS`. Safe to call on
    arbitrary dicts; missing keys are skipped.
    """
    if not isinstance(record, dict):
        return
    for field in _DATETIME_FIELDS:
        if field in record and isinstance(record[field], str):
            record[field] = convert_utc_string_to_local(record[field], tz_name)


def _retry_http_call(call_func, max_retries: int = 3):
    """Helper to retry HTTP calls with exponential backoff and rate limit handling"""
    retry_count = 0
    while retry_count <= max_retries:
        try:
            response = call_func()

            if response.status_code == 429:
                retry_after = int(response.headers["Retry-After"] if "Retry-After" in response.headers else "5")
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
    extra_prefer: list[str] | None = None,
) -> dict[str, Any] | None:
    headers = {
        "Authorization": f"Bearer {get_token(cache_file, scopes, settings, account_id=account_id)}",
    }

    prefer_values: list[str] = []
    if method == "GET":
        if "$search" in (params or {}):
            prefer_values.append('outlook.body-content-type="text"')
        elif "body" in ((params or {})["$select"] if "$select" in (params or {}) else ""):
            prefer_values.append('outlook.body-content-type="text"')
    else:
        headers["Content-Type"] = "application/json" if json else "application/octet-stream"

    if extra_prefer:
        prefer_values.extend(extra_prefer)
    if prefer_values:
        headers["Prefer"] = ", ".join(prefer_values)

    p_filter = params["$filter"] if params and "$filter" in params else ""
    if params and ("$search" in params or "contains(" in p_filter or "/any(" in p_filter):
        headers["ConsistencyLevel"] = "eventual"
        params.setdefault("$count", "true")

    url = f"{base_url}{path}"
    logger.debug(f"Graph API {method} {url} params={params}")

    response = _retry_http_call(
        lambda: client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json,
            content=data,
        ),
        max_retries,
    )

    if response and response.content:
        result = response.json()
        logger.debug(f"Graph API {method} {url} returned {response.status_code}")
        return result

    logger.warning(f"Graph API {method} {url} returned empty response")
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
    extra_prefer: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Make paginated requests following @odata.nextLink"""
    items_returned = 0
    next_link = None
    page_num = 1

    logger.debug(f"Starting paginated request for {path} with params {params}")

    while True:
        if next_link:
            logger.debug(f"Fetching page {page_num} via nextLink")
            result = request(
                client,
                cache_file,
                scopes,
                settings,
                base_url,
                "GET",
                next_link.replace(base_url, ""),
                account_id,
                extra_prefer=extra_prefer,
            )
        else:
            logger.debug(f"Fetching page {page_num} for {path}")
            result = request(
                client,
                cache_file,
                scopes,
                settings,
                base_url,
                "GET",
                path,
                account_id,
                params=params,
                extra_prefer=extra_prefer,
            )

        if not result:
            logger.error(f"API request failed for path '{path}' with params {params}")
            raise ValueError(f"API request failed for path '{path}' with params {params}")

        if "value" not in result:
            logger.error(f"Invalid API response for path '{path}': missing 'value' field. Response keys: {list(result.keys())}")
            raise ValueError(f"Invalid API response for path '{path}': missing 'value' field. Response: {result}")

        page_size = len(result["value"])
        logger.debug(f"Page {page_num} returned {page_size} items")

        for item in result["value"]:
            if limit and items_returned >= limit:
                logger.debug(f"Reached limit of {limit} items")
                return
            yield item
            items_returned += 1

        next_link = result["@odata.nextLink"] if "@odata.nextLink" in result else None
        if not next_link:
            logger.debug(f"Pagination complete: {items_returned} total items across {page_num} pages")
            break

        page_num += 1


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
