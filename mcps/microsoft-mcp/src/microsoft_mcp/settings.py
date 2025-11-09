from pydantic_settings import BaseSettings, SettingsConfigDict


class MicrosoftSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    microsoft_mcp_client_id: str
    microsoft_mcp_tenant_id: str = "common"
