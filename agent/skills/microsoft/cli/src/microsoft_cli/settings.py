from pydantic_settings import BaseSettings, SettingsConfigDict

# First-party, pre-authorized Microsoft public client ("Microsoft Office"). It is
# trusted tenant-wide on every Microsoft 365 tenant, so it works without the user
# registering an Azure app, and it slips past the common "block third-party apps"
# admin control that otherwise stops a custom registration. This is what makes the
# reverse-engineered OWA path usable on locked-down company tenants. Override with
# MICROSOFT_MCP_CLIENT_ID to use your own Azure app registration (the purist
# "official" path).
FIRST_PARTY_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"


class MicrosoftSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    microsoft_mcp_client_id: str | None = None
    # "organizations" binds the grant to a work/school tenant up front, which is what
    # custom-domain M365 mailboxes need for token refresh to stick. Personal accounts
    # should set MICROSOFT_MCP_TENANT_ID=consumers (or common).
    microsoft_mcp_tenant_id: str = "organizations"

    @property
    def graph_client_id(self) -> str:
        """Client id for the official Graph path: the user's Azure app if configured,
        otherwise the first-party client so the skill works with zero Azure setup."""
        return self.microsoft_mcp_client_id or FIRST_PARTY_CLIENT_ID

    @property
    def owa_client_id(self) -> str:
        """Client id for the reverse-engineered OWA path. Always the first-party
        client: a custom Azure app is rarely authorized for the outlook.office.com
        resource that service.svc / EWS require."""
        return FIRST_PARTY_CLIENT_ID
