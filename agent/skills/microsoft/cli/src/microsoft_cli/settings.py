from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Microsoft Graph Command Line Tools: a Microsoft-published, multitenant public client that
# supports device-code flow. It is the default so the skill works with no Azure setup; users
# who want their own app registration (e.g. to restrict scopes or clear a Conditional Access
# block) override it with MICROSOFT_MCP_CLIENT_ID. The default client requests explicit Graph
# scopes (dynamic consent); a user's own app uses ".default" (its configured permissions).
DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

# First-party, pre-authorized "Microsoft Office" public client. It is trusted tenant-wide
# and authorized for the outlook.office.com resource, so it can mint OWA REST tokens via
# device-code flow on tenants that block third-party Graph apps. This is what lets the OWA
# REST fallback authenticate with a code (no browser) instead of a browser token capture.
OWA_REST_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"


class MicrosoftSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    microsoft_mcp_client_id: str = DEFAULT_CLIENT_ID
    microsoft_mcp_tenant_id: str = "common"


@lru_cache(maxsize=1)
def get_settings() -> MicrosoftSettings:
    """Single owner of the env-derived settings; read once per process."""
    return MicrosoftSettings()
