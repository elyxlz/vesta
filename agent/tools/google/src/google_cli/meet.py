from . import api
from .config import Config


def create_space(config: Config) -> dict:
    service = api.meet_service(config)
    space = api.retry(lambda: service.spaces().create(body={}).execute())
    return {"meeting_uri": space["meetingUri"], "meeting_code": space["meetingCode"]}
