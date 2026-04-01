import os
from dataclasses import dataclass, field


@dataclass
class Config:
    base_url: str = field(default_factory=lambda: os.environ.get("HASS_URL", os.environ.get("HOME_ASSISTANT_URL", "http://192.168.4.5:8123")))
    token: str = field(default_factory=lambda: os.environ.get("HASS_TOKEN", ""))

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def validate(self):
        if not self.token:
            raise ValueError("HASS_TOKEN environment variable not set")
