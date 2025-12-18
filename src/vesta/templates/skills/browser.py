"""Browser & Web skill template."""

SKILL_MD = """\
---
name: browser
description: This skill should be used when the user asks to "browse", "open a website", "navigate to", "click", "fill form", "take screenshot", "scrape", or needs to interact with web pages, automate browser actions, or extract information from websites.
---

# Browser & Web

You have access to browser automation tools through MCP. Use them to interact with web pages on behalf of the user.

## Best Practices

- Take screenshots to verify actions completed correctly
- Handle login flows carefully, respecting security
- Wait for pages to load before interacting
- Report errors clearly when navigation fails

## Memory

### Frequently Visited Sites
[Sites the user often accesses]

### Login Patterns
[How to handle authentication for different sites]

### Screenshot Preferences
[User's preferred formats and locations]
"""

SCRIPTS: dict[str, str] = {}
