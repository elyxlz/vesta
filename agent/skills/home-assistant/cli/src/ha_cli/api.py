import httpx
from .config import Config


class HAClient:
    def __init__(self, config: Config):
        config.validate()
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            headers=config.headers,
            timeout=15.0,
        )

    def get_state(self, entity_id: str) -> dict:
        r = self._client.get(f"/api/states/{entity_id}")
        r.raise_for_status()
        return r.json()

    def get_all_states(self) -> list[dict]:
        r = self._client.get("/api/states")
        r.raise_for_status()
        return r.json()

    def call_service(self, domain: str, service: str, data: dict | None = None) -> list[dict]:
        payload = data or {}
        r = self._client.post(f"/api/services/{domain}/{service}", json=payload)
        r.raise_for_status()
        return r.json()

    def get_history(self, entity_id: str, hours: int = 24) -> list[list[dict]]:
        from datetime import datetime, timedelta, UTC
        start = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        r = self._client.get(f"/api/history/period/{start}", params={
            "filter_entity_id": entity_id,
            "minimal_response": "",
            "significant_changes_only": "",
        })
        r.raise_for_status()
        return r.json()

    def get_services(self) -> dict:
        r = self._client.get("/api/services")
        r.raise_for_status()
        return r.json()

    def check_api(self) -> dict:
        r = self._client.get("/api/")
        r.raise_for_status()
        return r.json()
