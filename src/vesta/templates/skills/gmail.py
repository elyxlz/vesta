"""Gmail skill template."""

SKILL_MD = """\
---
name: gmail
description: This skill should be used when the user asks about "Gmail", "Google email", or needs to read/send emails via a Google account.
---

# Gmail

## Status: Not yet set up

This skill needs a Gmail integration to be built. Vesta can build one using the Gmail API.

### Setup Notes
- Requires a Google Cloud project with the Gmail API enabled
- OAuth2 credentials (client_id, client_secret) for user authorization
- Scopes: `gmail.readonly`, `gmail.send`, `gmail.modify` as needed
- Token storage for persistent access

### Contact Communication Styles
[How to communicate with different contacts]

### Email Preferences
[User's preferred email handling patterns]
"""

SCRIPTS: dict[str, str] = {}
