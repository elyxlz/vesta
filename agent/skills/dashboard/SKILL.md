---
name: dashboard
description: Use when the you need to add, remove, or modify dashboard widgets and or customize the dashboard layout.
serve: see SETUP.md
---

# Dashboard

A React app that renders the dashboard consisting of widgets embedded in the main Vesta app. 

## Current widgets

[current_widgets <!-- Keep this list up to date. After adding or removing a widget, update this section. -->]

## Important

- After creating or editing a widget, you MUST rebuild and restart the server.
- If the dashboard server is not running yet, follow [SETUP.md](SETUP.md) first — but only once.
- You only need to edit files in `src/widgets/` — do NOT read or modify `globals.css`, `main.tsx`, `theme-sync.ts`, `App.tsx`, or `index.html`.

## Before creating a widget

When the user asks for a widget, ask enough to build it well. Don't ask open-ended questions — suggest concrete options for things like data source (static vs fetched), interactivity (display-only vs actionable), size, etc. Get it right the first time so there's less back-and-forth.

## Creating a widget

Three steps: write the component, register it, rebuild.

**Step 1.** Create `~/vesta/skills/dashboard/app/src/widgets/<widget-id>.tsx`:

```tsx
import { useState } from "react";

export const meta = {
  id: "my-widget",
  title: "My Widget",
  width: 1,   // 1 = small, 2 = medium, 3 = full width
  height: 1,  // 1 = short, 2 = tall
};

export default function MyWidget() {
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-muted-foreground">{meta.title}</h3>
      {/* widget content */}
    </div>
  );
}
```

**Step 2.** Add the import and entry to `~/vesta/skills/dashboard/app/src/widgets/index.ts`:

```ts
import MyWidget, { meta as myWidgetMeta } from "./my-widget";

export const widgets: WidgetEntry[] = [
  { ...myWidgetMeta, component: MyWidget },
];
```

**Step 3.** Rebuild and restart the server:

```bash
cd ~/vesta/skills/dashboard/app && npx vite build
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -S dashboard -X quit 2>/dev/null
screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```

**Step 4.** Update the "Current widgets" section at the top of this SKILL.md — add a line like `- **My Widget** (`my-widget.tsx`) — brief description`.

Do this for removals too — keep the list in sync.

## Widget data patterns

### Static data (habits, bookmarks, etc.)

Data that the user dictates and that only changes when they ask you to update it. Hardcode it directly in the component source — when the user asks to add/remove items, edit the file and rebuild.

```tsx
const bookmarks = [
  { label: "Google News", url: "https://news.google.com" },
  { label: "YouTube", url: "https://youtube.com" },
];
```

### Dynamic data (skill APIs, third-party services, etc.)

Data that comes from somewhere else and changes dynamically — an existing skill's HTTP API, a third-party service, or a dedicated data skill you create. Use `fetch()` inside `useEffect`.

```tsx
useEffect(() => {
  fetch("/agents/{name}/reminders/list")
    .then(r => r.json())
    .then(setReminders);
}, []);
```

If no existing skill provides the data a widget needs, create a new skill with an HTTP API that the widget can fetch from.

## Removing a widget

1. Remove the import and entry from `widgets/index.ts`
2. Delete the widget `.tsx` file
3. Rebuild and restart (same as Step 3 above)

## Syncing shared files

The dashboard reuses UI components, styles, and utilities from the main Vesta app. Run `sync-app.sh` to pull the latest versions into the dashboard:

```bash
~/vesta/skills/dashboard/sync-app.sh
```

This copies `globals.css`, `lib/utils.ts`, `hooks/use-mobile.ts`, and all `components/ui/*.tsx` from the main app. Run it during initial setup and whenever the main app updates its shared files.

## UI components

The dashboard uses the same shadcn/ui components as the main Vesta app, synced via `sync-app.sh`. Before creating a widget, check `~/vesta/skills/dashboard/app/src/components/ui/` for what's available and read `~/vesta/skills/dashboard/shadcn/README.md` for usage patterns.

Import from `@/components/ui/<name>`:

```tsx
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
```

Styling uses Tailwind CSS with the same theme as the main app. Use semantic color classes like `text-foreground`, `text-muted-foreground`, `bg-primary`, `bg-secondary`, `bg-accent`, `bg-destructive`. The widget container already applies `bg-card border border-border rounded-lg shadow-sm` — don't duplicate those.

Do not run the shadcn CLI — components are synced from the main app.

## Widget rules

- **One file per widget** in `~/vesta/skills/dashboard/app/src/widgets/`
- **Self-contained**: no shared state between widgets
- **Use the UI components** from `@/components/ui/` — read them before building widgets
- **State**: `useState` / `useEffect` for local state
- **No localStorage for data**: the dashboard is accessed from multiple devices. Static data goes in the source, dynamic data comes from skill APIs via `fetch()`
- **No new dependencies**: only use packages in the dashboard's `package.json`

## Widget sizes

| width | Span | Good for |
|-------|------|----------|
| 1     | 1/3  | Counters, stats, toggles |
| 2     | 2/3  | Charts, lists, calendars |
| 3     | Full | Timelines, tables |

Height works the same (1 = compact, 2 = tall, 3 = extra tall).

## Troubleshooting

- **Dashboard not showing?** `screen -ls | grep dashboard`
- **Check registration:** `curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services`
- **Restart server:** Same as Step 3 in Creating a widget — rebuild, get port from vestad, restart screen
