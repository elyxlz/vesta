import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Config
from . import auth


def gmail_service(config: Config):
    creds = auth.get_credentials(config.token_file, config.credentials_file, config.scopes)
    return build("gmail", "v1", credentials=creds)


def calendar_service(config: Config):
    creds = auth.get_credentials(config.token_file, config.credentials_file, config.scopes)
    return build("calendar", "v3", credentials=creds)


def meet_service(config: Config):
    creds = auth.get_credentials(config.token_file, config.credentials_file, config.scopes)
    return build("meet", "v2", credentials=creds)


def retry(func, *, max_retries: int = 3, config: "Config | None" = None):
    retried_401 = False
    for attempt in range(max_retries + 1):
        try:
            return func()
        except HttpError as e:
            if attempt == max_retries:
                raise
            if e.resp.status == 401 and not retried_401 and config:
                retried_401 = True
                auth.get_credentials(config.token_file, config.credentials_file, config.scopes)
                continue
            if e.resp.status == 429:
                retry_after = int(e.resp["retry-after"] if "retry-after" in e.resp else "5")
                time.sleep(min(retry_after, 60))
            elif e.resp.status >= 500:
                time.sleep(2**attempt)
            else:
                raise
