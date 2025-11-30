# Browser Agent Memory

## How to Use Playwright

### Key Principle: Accessibility-Based Navigation
Playwright MCP uses the accessibility tree, NOT screenshots or vision. You interact with elements by their `ref` from snapshots, not pixel coordinates.

**CRITICAL WORKFLOW:**
1. Navigate to URL with `browser_navigate`
2. ALWAYS call `browser_snapshot` to see the page structure
3. Use `ref` values from snapshot to interact with elements
4. Re-snapshot after EVERY action that changes the page

### Available Tools

#### Navigation
- `browser_navigate` - Go to a URL
- `browser_navigate_back` - Go back
- `browser_tabs` - Manage tabs
- `browser_close` - Close browser

#### Page Understanding
- `browser_snapshot` - Get accessibility tree with refs (PRIMARY TOOL)
- `browser_take_screenshot` - Save visual for user review
- `browser_console_messages` - Get console output
- `browser_network_requests` - List network requests

#### Interaction
- `browser_click` - Click element using ref
- `browser_type` - Type text into element
- `browser_fill_form` - Fill multiple fields at once
- `browser_select_option` - Select dropdown
- `browser_hover` - Hover over element
- `browser_press_key` - Press keyboard key
- `browser_file_upload` - Upload files
- `browser_handle_dialog` - Accept/dismiss dialogs
- `browser_drag` - Drag between elements

#### Waiting
- `browser_wait_for` - Wait for text/time

### Snapshot-First Workflow
```
1. browser_navigate({ url: "https://example.com" })
2. browser_snapshot()  # See page structure
3. browser_click({ element: "Sign In", ref: "s2" })
4. browser_snapshot()  # ALWAYS re-snapshot after actions!
```

### Form Filling
Single field:
```
browser_type({ element: "Email", ref: "s3", text: "user@example.com" })
```

Multiple fields:
```
browser_fill_form({
  fields: [
    { element: "Email", ref: "s3", text: "user@example.com" },
    { element: "Password", ref: "s4", text: "password123" }
  ]
})
```

### Best Practices
1. ALWAYS snapshot before any interaction
2. Refs are ephemeral - never reuse across snapshots
3. Re-snapshot after any DOM-changing action
4. Screenshots for user review, snapshots for navigation
5. Close browser when task complete

## Learned Patterns

### Navigation Patterns
[Sites and workflows discovered through use]

### Known Site Behaviors
[Sites requiring special handling]

### Screenshot Preferences
[User's preferred formats and locations]
