from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MicrosoftSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    microsoft_mcp_client_id: str | None = None
    microsoft_mcp_tenant_id: str = "common"

    @model_validator(mode="after")
    def _check_client_id(self):
        if not self.microsoft_mcp_client_id:
            raise ValueError(
                "MICROSOFT_MCP_CLIENT_ID environment variable is required. "
                "Get one from https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
            )
        return self
