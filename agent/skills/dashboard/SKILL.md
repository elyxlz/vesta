---
name: dashboard
description: Use when the user asks to add, remove, or modify dashboard widgets, customize their dashboard layout, or build visual components like counters, charts, reminders, or status displays. Each widget is a self-contained React component. Do NOT register new services for widgets — widgets are files inside the existing dashboard app, not separate services.
---

# Dashboard

A React app that renders widgets in the main Vesta app. The dashboard is ONE service called "dashboard" — do NOT register additional services. Widgets are `.tsx` files you add to the existing app.

## Current widgets

<!-- Keep this list up to date. After adding or removing a widget, update this section. -->

_None yet._

## Important

- Widgets are NOT services. They are `.tsx` files inside `~/vesta/skills/dashboard/app/src/widgets/`.
- Never run `curl` to register services when creating widgets.
- After creating or editing a widget, you MUST rebuild and restart the server.
- If the dashboard server is not running yet, follow [SETUP.md](SETUP.md) first — but only once.
- You only need to edit files in `src/widgets/` — do NOT read or modify `globals.css`, `main.tsx`, `theme-sync.ts`, `App.tsx`, or `index.html`.
- **Never hardcode ports.** Register with vestad and it returns a port (see Port allocation below).

## Port allocation

Multiple agents share the host network, so ports must not conflict. Vestad allocates ports automatically — just register the service name without a port:

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
```

Vestad picks a free port, persists it, and returns it. On restart, re-registering the same service name reuses the same port.

## Before creating a widget

When the user asks for a widget, ask enough to build it well. Don't ask open-ended questions — suggest options:

- **What to show**: "Want me to keep the list updated for you whenever you tell me, or should it pull from your reminders automatically?"
- **Interaction**: "Should it just show your info, or do you want to be able to check things off / tap buttons on it?"
- **Size**: "I'll make this a small card — unless you'd prefer it bigger with more detail?"
- **Starting items**: "Want me to add anything to it now? Like which medicines, which habits, etc."
- **Connections**: "You already have reminders set up — want me to link this to those so it stays in sync?"

Get it right the first time so there's less back-and-forth.

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

### Static data (medicines, habits, bookmarks, etc.)

Hardcode data directly in the component source. When the user asks to add/remove items, edit the component and rebuild.

```tsx
// GOOD: data lives in the source
const medicines = [
  { name: "Paracetamol", schedule: "afternoon" },
  { name: "Vitamin D", schedule: "morning" },
];
```

### Dynamic data (reminders, tasks, weather, etc.)

Use `fetch()` inside `useEffect` to get data from an existing skill's API or a dedicated data skill. The dashboard is accessed from multiple devices — never use `localStorage` for persistent data.

```tsx
// GOOD: fetch from a skill API
useEffect(() => {
  fetch("/agents/{name}/reminders/list")
    .then(r => r.json())
    .then(setReminders);
}, []);
```

If no existing skill provides the data a widget needs, create a new skill with an HTTP API that the widget can fetch from.

### localStorage for UI state only

`localStorage` is only for transient UI state that should survive navigation (e.g., which tab is selected, whether a section is collapsed). Never store user data there — it doesn't sync across devices.

## Removing a widget

1. Remove the import and entry from `widgets/index.ts`
2. Delete the widget `.tsx` file
3. Rebuild and restart (same as Step 3 above)

## UI components

The dashboard ships with the same shadcn/ui component library as the main Vesta app. **Before creating a widget, read `~/vesta/skills/dashboard/shadcn/README.md`** — it has the rules, patterns, and component selection guide. Then check `~/vesta/skills/dashboard/app/src/components/ui/` for available components.

Import them as `@/components/ui/<name>`:

```tsx
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Checkbox } from "@/components/ui/checkbox";
```

Do NOT run the shadcn CLI. All components are already installed.

## Widget rules

- **One file per widget** in `~/vesta/skills/dashboard/app/src/widgets/`
- **Self-contained**: no shared state between widgets
- **Use the UI components** from `@/components/ui/` — read them before building widgets
- **Tailwind CSS** for styling — same theme as the main app
  - Colors: `text-foreground`, `text-muted-foreground`, `bg-primary`, `text-primary-foreground`, `bg-secondary`, `bg-accent`, `bg-destructive`
  - The widget container already has `bg-card border border-border rounded-lg shadow-sm` — don't duplicate
- **State**: `useState` / `useEffect` for local state
- **No localStorage for data**: the dashboard is accessed from multiple devices. Static data goes in the source, dynamic data comes from skill APIs via `fetch()`
- **Icons**: import from `lucide-react`
- **Charts**: import from `recharts`
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
