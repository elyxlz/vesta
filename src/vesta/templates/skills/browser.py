"""Browser & Web skill template."""

SKILL_MD = """\
---
name: browser
description: Use for "browse", "open a website", "navigate to", "click", "fill form",
  "take screenshot", "scrape", or any web page interaction.
---

# Browser & Web

Use Playwright to automate browser interactions via bash scripts.

## Setup

Install dependencies (first time only):
```bash
npm install -g playwright
npx playwright install --with-deps chromium
```

## Taking Screenshots

```bash
npx playwright screenshot --browser chromium "https://example.com" ~/screenshot.png
```

## Automation Scripts

For clicks, forms, and multi-step flows, write a script to `/tmp/browser_task.js`:

```javascript
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('https://example.com');
  // await page.click('#btn');
  // await page.fill('#input', 'value');
  await page.screenshot({ path: '/tmp/result.png' });
  await browser.close();
})();
```

Run it:
```bash
node /tmp/browser_task.js
```

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
"""

SCRIPTS: dict[str, str] = {}
