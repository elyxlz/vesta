---
name: app-frontend
description: Conventions for the Vesta desktop app frontend (React + Tauri). Covers project structure, providers, hooks, components, pages, routing, and state management. Use when working in app/src/.
user-invocable: false
---

# App Frontend

React SPA (Vite + Tauri) using React Router, Zustand, and shadcn/ui.

## Directory Layout

```
app/src/
├── api/            # API client functions (fetch/WS helpers)
├── components/     # Reusable UI components (each in a folder)
├── hooks/          # Shared hooks (used across multiple files)
├── lib/            # Layouts, utilities, types, non-hook helpers
├── pages/          # Route-level page components
├── providers/      # React context providers + their private hooks
├── stores/         # Zustand stores
└── styles/         # Global CSS
```

## Components

Each component lives in its own folder with `index.tsx` and optionally `styles.ts`:

```
components/AgentIsland/
├── index.tsx
├── Collapsed.tsx
├── Expanded.tsx
└── transitions.ts
```

Self-contained components read from providers directly. prefer zero-prop components over prop drilling when the data comes from context.

## Providers

Providers live in `providers/<Name>/index.tsx` and export a `<NameProvider>` component plus a `useName()` consumer hook.

Private hooks that only serve one provider go **in that provider's folder**, not in `hooks/`:

```
providers/VoiceProvider/
├── index.tsx           # VoiceProvider + useVoice()
├── use-voice-input.ts  # private to this provider
├── use-voice-output.ts
└── use-voice-status.ts

providers/ChatProvider/
├── index.tsx           # ChatProvider + useChatContext()
└── use-chat.ts         # private to this provider
```

Providers read the agent name from `useSelectedAgent()` internally. don't pass it as a prop.

## Hooks

`hooks/` is **only** for hooks shared across multiple unrelated consumers:
- `use-mobile.ts`. responsive breakpoint detection
- `use-auto-scroll.ts`. scroll-to-bottom behavior
- `use-optimistic-toggle.ts`. optimistic boolean toggle

If a hook is only used by one provider or component, colocate it.

## Pages

Thin route-level components in `pages/<Name>/index.tsx`. Pages render components but own minimal state. shared state lives in providers.

## Routing & Layouts

```
RootLayout
└── NavigationGuard (auth + agent-list gates)
    ├── Home
    ├── CreateAgent
    └── AgentLayout (agent/:name)
        ├── AgentDashboard (index)
        ├── AgentChat (chat)
        └── AgentSettingsPage (settings)
```

`AgentLayout` renders the shared Navbar (with AgentIsland + AgentMenu) once above the `<Outlet />`, so these components persist across route changes without remounting.

Provider stack in `AgentLayout`:
```
SelectedAgentProvider → VoiceProvider → ChatProvider → ModalsProvider
```

## State Management

- **Server state** (agent info, voice status): fetched in providers, polled/refreshed
- **WebSocket state** (chat messages, connection): managed in `ChatProvider`
- **UI state** (modals, dialogs, menu open): owned by the relevant provider or component locally
- **Global layout state** (navbar height): Zustand stores in `stores/`

## Key Conventions

- "Agent" terminology everywhere. never "box"
- Minimize comments. only for truly complex logic
- Use shadcn/ui components wherever possible. never build custom markup when a shadcn component exists (Button, Dialog, Card, Badge, Separator, Skeleton, Alert, etc.). See the [shadcn skill](../shadcn/SKILL.md) for component selection and rules.
- Use `cn()` for conditional classes
- Use semantic colors (`bg-primary`, `text-muted-foreground`), never raw values
