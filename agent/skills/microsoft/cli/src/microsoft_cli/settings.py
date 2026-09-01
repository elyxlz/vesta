import json
import os
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

# Per-account client-id override: let one account authenticate against its OWN Azure app
# registration (e.g. one granted Mail.Send) while every other account keeps the global
# `microsoft_mcp_client_id`. Two ways, in precedence order:
#   1. MICROSOFT_MCP_CLIENT_ID__<EMAIL>: email upper-cased, every non-alphanumeric -> "_"
#      (okami@pascarelli.com -> MICROSOFT_MCP_CLIENT_ID__OKAMI_PASCARELLI_COM). A real env var.
#   2. MICROSOFT_MCP_ACCOUNT_CLIENT_IDS: JSON map email -> client id, e.g. {"a@b.com": "<id>"}.
# An account in neither falls back to `microsoft_mcp_client_id` (i.e. today's behavior).
_ACCOUNT_CLIENT_ID_ENV_PREFIX = "MICROSOFT_MCP_CLIENT_ID__"


def _normalize_email(email: str) -> str:
    """Turn an email into the suffix of a MICROSOFT_MCP_CLIENT_ID__ env var: upper-case, and every
    character that is not a letter or digit becomes '_' (so '@' and '.' are both '_')."""
    return "".join(ch if ch.isalnum() else "_" for ch in email.strip()).upper()


class MicrosoftSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    microsoft_mcp_client_id: str = DEFAULT_CLIENT_ID
    microsoft_mcp_tenant_id: str = "common"
    # JSON object mapping account email -> client id. Empty (no per-account overrides) by default.
    microsoft_mcp_account_client_ids: str = ""

    def _json_overrides(self) -> dict[str, str]:
        """Parse microsoft_mcp_account_client_ids into a lower-cased email -> client id map.
        A blank, malformed, or non-object value yields an empty map (never raises)."""
        raw = (self.microsoft_mcp_account_client_ids or "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k).strip().lower(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}

    def account_client_id_override(self, account_email: str | None) -> str | None:
        """The per-account client-id override for this email, or None when it has none.
        Precedence: the MICROSOFT_MCP_CLIENT_ID__<normalized-email> env var, then the JSON map."""
        if not account_email:
            return None
        env_value = os.environ.get(_ACCOUNT_CLIENT_ID_ENV_PREFIX + _normalize_email(account_email))
        if env_value and env_value.strip():
            return env_value.strip()
        return self._json_overrides().get(account_email.strip().lower())

    def client_id_for_account(self, account_email: str | None) -> str:
        """Resolve the OAuth client id for one account: its per-account override if configured,
        otherwise the global microsoft_mcp_client_id. An account with no override is unchanged."""
        return self.account_client_id_override(account_email) or self.microsoft_mcp_client_id

    def has_account_overrides(self) -> bool:
        """True if any per-account override is configured (JSON map or a per-email env var). Lets the
        token path skip all per-account work when nothing is configured, preserving prior behavior."""
        return bool(self._json_overrides()) or any(k.startswith(_ACCOUNT_CLIENT_ID_ENV_PREFIX) for k in os.environ)


@lru_cache(maxsize=1)
def get_settings() -> MicrosoftSettings:
    """Single owner of the env-derived settings; read once per process."""
    return MicrosoftSettings()


def client_id_for_account(account_email: str | None) -> str:
    """Module-level shortcut for get_settings().client_id_for_account(...)."""
    return get_settings().client_id_for_account(account_email)


def account_client_id_override(account_email: str | None) -> str | None:
    """Module-level shortcut for get_settings().account_client_id_override(...)."""
    return get_settings().account_client_id_override(account_email)
