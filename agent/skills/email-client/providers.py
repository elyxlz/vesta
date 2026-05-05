#!/usr/bin/env python3
"""Provider profiles for the email-client skill.

Each provider profile describes how to talk IMAP/SMTP to one mail
host: where to connect, which OAuth client to use (if any), which
scopes to request, and which auth strategy the daemon and CLI should
follow.

Auth strategies:

    "device-flow"      OAuth2 device-code flow (used by Microsoft personal
                       accounts; works headlessly because the user
                       completes the browser step on a separate device).
    "loopback-oauth"   OAuth2 with a localhost redirect URI. Google
                       requires this for desktop/CLI clients now that
                       device-flow is restricted to TV / limited input
                       devices.
    "app-password"     Plain LOGIN with an app-specific password the
                       user generates in their account settings (Yahoo,
                       iCloud, Fastmail, custom IMAP servers).

Defaults can be overridden per environment variable so any one
profile can be reshaped without touching the dict (or use the
"generic" profile, which has no defaults at all).
"""
from __future__ import annotations

# Mozilla Thunderbird's published public OAuth client IDs. These are
# baked into Thunderbird's source and are the canonical "open-source
# mail client" choice for personal Microsoft and Google accounts.
THUNDERBIRD_MS_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
THUNDERBIRD_GOOGLE_CLIENT_ID = (
    "406964657835-aq8lmia8j95dhl1a2bvharmfk3t1glqf.apps.googleusercontent.com"
)


PROVIDERS: dict[str, dict] = {
    "microsoft-personal": {
        "label": "Microsoft personal (Outlook.com, Hotmail, Live)",
        "auth_strategy": "device-flow",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_starttls": True,
        "oauth_client_id": THUNDERBIRD_MS_CLIENT_ID,
        "oauth_authority": "https://login.microsoftonline.com/consumers",
        "oauth_scopes": [
            "https://outlook.office.com/IMAP.AccessAsUser.All",
            "https://outlook.office.com/SMTP.Send",
        ],
    },
    "gmail": {
        "label": "Gmail (personal Google account)",
        "auth_strategy": "loopback-oauth",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_starttls": True,
        "oauth_client_id": THUNDERBIRD_GOOGLE_CLIENT_ID,
        # Google does not use this field but we keep the shape uniform.
        "oauth_authority": "https://accounts.google.com",
        "oauth_auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "oauth_token_url": "https://oauth2.googleapis.com/token",
        "oauth_scopes": ["https://mail.google.com/"],
    },
    "yahoo-app-password": {
        "label": "Yahoo Mail (app password)",
        "auth_strategy": "app-password",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
        "smtp_starttls": True,
    },
    "icloud-app-password": {
        "label": "iCloud Mail (app password)",
        "auth_strategy": "app-password",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.me.com",
        "smtp_port": 587,
        "smtp_starttls": True,
    },
    "fastmail-app-password": {
        "label": "Fastmail (app password)",
        "auth_strategy": "app-password",
        "imap_host": "imap.fastmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.fastmail.com",
        "smtp_port": 587,
        "smtp_starttls": True,
    },
    "generic": {
        "label": "Generic IMAP/SMTP (env-driven, no defaults)",
        "auth_strategy": "app-password",
        "imap_host": None,
        "imap_port": 993,
        "smtp_host": None,
        "smtp_port": 587,
        "smtp_starttls": True,
    },
}


# Map an email domain (or domain suffix) to a provider key. The first
# match wins, so put the most specific entries first if you ever add
# overlapping ones.
DOMAIN_TO_PROVIDER: list[tuple[str, str]] = [
    ("gmail.com", "gmail"),
    ("googlemail.com", "gmail"),
    ("yahoo.com", "yahoo-app-password"),
    ("yahoo.co.uk", "yahoo-app-password"),
    ("yahoo.fr", "yahoo-app-password"),
    ("yahoo.de", "yahoo-app-password"),
    ("yahoo.it", "yahoo-app-password"),
    ("yahoo.es", "yahoo-app-password"),
    ("ymail.com", "yahoo-app-password"),
    ("rocketmail.com", "yahoo-app-password"),
    ("icloud.com", "icloud-app-password"),
    ("me.com", "icloud-app-password"),
    ("mac.com", "icloud-app-password"),
    ("fastmail.com", "fastmail-app-password"),
    ("fastmail.fm", "fastmail-app-password"),
    ("outlook.com", "microsoft-personal"),
    ("outlook.co.uk", "microsoft-personal"),
    ("hotmail.com", "microsoft-personal"),
    ("hotmail.co.uk", "microsoft-personal"),
    ("hotmail.fr", "microsoft-personal"),
    ("hotmail.de", "microsoft-personal"),
    ("hotmail.it", "microsoft-personal"),
    ("hotmail.es", "microsoft-personal"),
    ("live.com", "microsoft-personal"),
    ("live.co.uk", "microsoft-personal"),
    ("msn.com", "microsoft-personal"),
]


def detect_provider(email: str) -> str | None:
    """Return a provider key for the given email address, or None.

    Matches on the lower-cased domain. A match on either the exact
    domain or a parent domain wins (e.g. ``foo@inbox.gmail.com`` would
    not match ``gmail.com`` here; we only do exact-domain matches to
    avoid surprising users with corporate vanity domains).
    """
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    for d, key in DOMAIN_TO_PROVIDER:
        if domain == d:
            return key
    return None


def get_profile(name: str) -> dict:
    """Return a copy of the named provider profile.

    Raises ``KeyError`` if the profile name is unknown. Callers
    typically pass the result through :func:`apply_env_overrides` to
    let the user override defaults via environment variables.
    """
    if name not in PROVIDERS:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(PROVIDERS)}")
    return dict(PROVIDERS[name])


def apply_env_overrides(profile: dict, env: dict) -> dict:
    """Overlay ``EMAIL_CLIENT_*`` env vars onto a provider profile.

    Any field set via env wins. Unset fields keep the profile default.
    """
    p = dict(profile)
    overrides = {
        "imap_host": env.get("EMAIL_CLIENT_HOST"),
        "smtp_host": env.get("EMAIL_CLIENT_SMTP_HOST"),
        "smtp_port": env.get("EMAIL_CLIENT_SMTP_PORT"),
        "oauth_client_id": env.get("EMAIL_CLIENT_OAUTH_CLIENT_ID"),
        "oauth_authority": env.get("EMAIL_CLIENT_OAUTH_AUTHORITY"),
    }
    for k, v in overrides.items():
        if v:
            p[k] = int(v) if k.endswith("_port") else v
    scopes = env.get("EMAIL_CLIENT_OAUTH_SCOPES")
    if scopes:
        p["oauth_scopes"] = [s for s in scopes.split() if s]
    return p


def resolve_provider(env: dict) -> tuple[str, dict]:
    """Pick a provider for the current environment.

    Resolution order:
      1. ``EMAIL_CLIENT_PROVIDER``
      2. Auto-detect from ``EMAIL_CLIENT_USER``'s domain
      3. Fall back to ``microsoft-personal``.

    Returns ``(provider_name, profile_with_overrides)``.
    """
    name = (env.get("EMAIL_CLIENT_PROVIDER") or "").strip()
    if not name:
        user = env.get("EMAIL_CLIENT_USER") or ""
        name = detect_provider(user) or "microsoft-personal"
    profile = apply_env_overrides(get_profile(name), env)
    return name, profile
