import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    data_dir: Path = Path.home() / ".zoom"

    @property
    def credentials_file(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def token_cache_file(self) -> Path:
        return self.data_dir / "token_cache.json"

    def load_credentials(self) -> dict:
        try:
            return json.loads(self.credentials_file.read_text())
        except FileNotFoundError:
            raise RuntimeError(f"Credentials not found at {self.credentials_file}. Run 'zoom setup' first.")
