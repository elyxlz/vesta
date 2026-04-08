---
name: dashboard
description: Use when you need to build, modify, or customize anything on the user's dashboard — widgets, layouts, pages, views, or any custom UI.
serve: PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
---

# Dashboard

A React app embedded in the main Vesta app. You have full control over `App.tsx` and can build anything: widgets, custom layouts, multi-page views, interactive tools, data visualizations, or any other UI the user wants.

## Before building (REQUIRED)

You MUST ask the user clarifying questions before writing any code. Go through these:

1. **Goal** — if the request is vague, clarify what they actually want to see or do
2. **Interaction** — display-only, or do they want to tap/click/toggle/input things?
3. **Data** — should it show fixed sample data, or pull in live data from a skill or API? Does the info need to stay in sync and look the same across different Vesta apps (like mobile)?

Only start building once the user has answered. Don't assume — ask.

## Project structure

```
~/vesta/skills/dashboard/app/src/
├── App.tsx              ← entry point, you edit this freely
├── main.tsx             ← do NOT modify
├── globals.css          ← do NOT modify (synced from main app)
├── components/
│   ├── ui/              ← shadcn components (synced, do NOT modify)
│   └── FadeScroll.tsx   ← shared scroll wrapper
├── widgets/             ← widget components (one file per widget)
├── lib/
│   ├── parent-bridge.ts ← auth + API helpers
│   └── utils.ts         ← synced utility (do NOT modify)
└── hooks/               ← synced hooks (do NOT modify)
```

**You can freely edit:** `App.tsx`, anything in `widgets/`, and any new files/folders you create (custom components, helpers, etc.)

**Do NOT modify:** `main.tsx`, `globals.css`, `lib/utils.ts`, `hooks/`, `components/ui/`

## Building components

### Widgets

For self-contained UI blocks, create files in `src/widgets/`:

```tsx
export default function MyWidget() {
  return (
    <div className="p-4 bg-card border border-border rounded-lg shadow-sm">
      {/* widget content */}
    </div>
  );
}
```

### Custom components

For shared components, layouts, or anything more complex, create files anywhere in `src/` (e.g. `src/components/MyComponent.tsx`, `src/views/`, etc.). Organize however makes sense for what you're building.

### Editing App.tsx

`App.tsx` is the root component. Import your widgets/components and arrange them however the user wants — grid layouts, tabs, sidebars, stacked views, anything. You have full control over the layout and structure.

When adding the first component, set `SHOW_EMPTY_STATE = false` to disable the placeholder.

## After every change (IMPORTANT)

**Rebuild and restart the server:**

```bash
cd ~/vesta/skills/dashboard/app && npx vite build
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -S dashboard -X quit 2>/dev/null
screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
# Wait for the server to be ready before notifying the app
for i in $(seq 1 20); do curl -s -o /dev/null http://localhost:$PORT && break; sleep 0.5; done
curl -s -X POST http://localhost:$WS_PORT/events/service-update \
  -H 'Content-Type: application/json' -d '{"service":"dashboard","action":"updated"}'
```

## Data patterns

### Static data (habits, bookmarks, etc.)

Data that the user dictates and that only changes when they ask you to update it. Two approaches depending on whether the user wants persistence:

Hardcode defaults in the source. When the user asks to permanently add/remove items, edit the file and rebuild.

If the component has interactive state the user can change (checking items, toggling things, reordering), **always persist it to `localStorage`** so changes survive reloads. Pattern:

Always prefix keys with `vesta-dashboard-` to avoid collisions.

### Dynamic data (skill APIs, third-party services, etc.)

Data that comes from somewhere else and changes dynamically — an existing skill's API, a new skill you create, or a third-party service.

**Never fetch external APIs directly from widget code** — the browser will block cross-origin requests (CORS). Instead, create a skill that fetches the data server-side and exposes it as an endpoint, then call that endpoint from the widget.

To call your skills use `apiFetch` from `@/lib/parent-bridge`. It handles auth and the base URL automatically. `apiFetch` waits for the auth token from the parent app before making requests, so it's safe to call on mount.

Widgets that fetch data **must show a loading state** while waiting — use skeletons or spinners to provide a nice ux while data loads.


## Removing components

1. Remove the import and usage from `App.tsx`
2. Delete the source file(s)
3. Rebuild and restart (same as above)
4. If removing everything, set `SHOW_EMPTY_STATE = true` in `App.tsx`

## Syncing shared files

The dashboard reuses UI components, styles, and utilities from the main Vesta app. Run `sync-app.sh` to pull the latest versions into the dashboard automatically:

```bash
~/vesta/skills/dashboard/sync-app.sh
```

## UI components

The dashboard uses the same shadcn/ui components as the main Vesta app, synced via `sync-app.sh`. Before building, check `~/vesta/skills/dashboard/app/src/components/ui/` for what's available and read `~/vesta/skills/dashboard/shadcn/README.md` for usage patterns.

Import from `@/components/ui/<name>`:

```tsx
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
```

Styling uses Tailwind CSS. Use semantic color classes like `text-foreground`, `text-muted-foreground`, `bg-primary`, `bg-secondary`, `bg-accent`, `bg-destructive`.

Try to keep everything compact, dashboard space is at a premium.

## Rules

- **No client-side fetches to external APIs** — the dashboard runs in a browser, so cross-origin requests to third-party APIs (Yahoo Finance, weather services, etc.) will be blocked by CORS. Instead, create a skill that fetches the data server-side and expose it as a skill API endpoint, then call it from the widget using `apiFetch`.
- **Use the UI components** from `@/components/ui/` — read them before building
- **State**: `useState` / `useEffect` for local state
- **localStorage only when the user opts in**: use it for persisting UI state (checked items, preferences), not as a primary data store. Always have hardcoded defaults as fallback
- **No new dependencies**: only use packages in the dashboard's `package.json`

## Troubleshooting

- **Dashboard not showing?** `screen -ls | grep dashboard`
- **Check registration:** `curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services`
- **Restart server:** Rebuild, get port from vestad, restart screen (same as "After every change")
