from dataclasses import dataclass
from pathlib import Path


ALL_SCOPES = " ".join(
    [
        "playlist-read-private",
        "playlist-read-collaborative",
        "playlist-modify-public",
        "playlist-modify-private",
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "user-library-read",
        "user-library-modify",
    ]
)

REDIRECT_URI = "https://example.com"


@dataclass
class Config:
    data_dir: Path = Path.home() / ".spotify"
    redirect_uri: str = REDIRECT_URI
    scopes: str = ALL_SCOPES

    @property
    def token_cache(self) -> Path:
        return self.data_dir / "token.json"

    @property
    def credentials_file(self) -> Path:
        return self.data_dir / "credentials.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
