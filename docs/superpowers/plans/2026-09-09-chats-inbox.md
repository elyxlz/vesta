# Chats Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/chats` route on web (split view: conversation list beside the open room) and a `chats` screen on mobile (agent orb row above the conversation list), both reached from a button on Home, with Home's own chats list removed.

**Architecture:** Web adds a `ChatsLayout` with two routes whose selection lives in the URL; the room body is lifted out of `RoomLayout` into a shared `RoomPane`. Mobile adds one screen and moves the branch's list under `src/chats/`. Nothing changes on the wire: both read the room list `/sync` already carries through `useGateway().rooms` / `useRoster().rooms` (ordered by core's `selectRooms`).

**Tech Stack:** React 19 + react-router-dom (web), Expo Router + React Native (mobile), `@vesta/core` (`roomKind`, `roomLabel`, `relativeTime`, `agentVisualStatus`) and `@vesta/core/react` (`useAgentVisualStatus`, `useAgentRequest`), vitest, Playwright and Maestro visual harnesses.

**Spec:** `docs/superpowers/specs/2026-09-09-chats-inbox-design.md`

## Global Constraints

- Work in the worktree `/Users/epasca/vesta-worktrees/chats-inbox` on branch `feat/chats-inbox` (cut from `feat/chat-rooms`). Run `npm` commands from `apps/`, `./check.sh` from the worktree root.
- Web copy is lowercase ("chats", "new group", "pick a conversation"). No spaced dashes in any string or comment. "Agent" is the product noun, never "box".
- Strict TS: no `as`, no `!`, no `any`; named exports only; annotate object literals rather than asserting.
- Comment blocks at most 8 lines. Files at most 400 lines (tests exempt).
- Web: a `.tsx` sibling inside a folder is private to that folder; a helper `.ts` may be imported across folders; a hook lives beside its one consumer; knip fails an export with no non-test importer.
- Web tests: `.test.tsx` runs in jsdom with `src/vitest.setup.ts` (which stubs `matchMedia` to `matches: false`, so `useIsMobile()` reads false, the wide layout); `.test.ts` runs in node.
- Mobile tests: `src/**/*.test.ts` only, pure models, no native rendering.
- Every visual scenario needs both a card in `visual/scenarios.json` and a drive; `visual/registry.test.ts` asserts the two sets of ids are equal. Web scenario `group` must be one of the existing groups; use `"Chat"`.
- Commit messages: Conventional Commits, imperative, no trailing period, and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File map

Web (`apps/web`):

| Path | Responsibility |
|---|---|
| `src/components/RoomPane/index.tsx` (create) | `RoomProvider` → `RoomSocketProvider` → optional children → the `Chat fullscreen` body. Used by `RoomLayout` and `ChatsLayout`. |
| `src/layouts/RoomLayout/index.tsx` (modify) | Keeps its navbar, renders it as `RoomPane`'s child so it can read `useRoom()`. |
| `src/layouts/ChatsLayout/room-route.ts` (create) | `roomRoute(room, wide)`: the one owner of where a row goes. |
| `src/layouts/ChatsLayout/room-route.test.ts` (create) | Node test of the four targets. |
| `src/layouts/ChatsLayout/ConversationList.tsx` (create, private) | Header with the "new group" button; one `NavLink` row per room with orb avatar, label, second line, time. |
| `src/layouts/ChatsLayout/index.tsx` (create) | `ChatsLayout` (navbar, list column, outlet column), `ChatsIndex` (empty pane), `ChatsRoom` (param → `RoomPane`, or the narrow redirect). |
| `src/layouts/ChatsLayout/index.test.tsx` (create) | jsdom tests: rows, active link, "+" opens the dialog, narrow redirect. |
| `src/router.tsx` (modify) | Registers `chats` and `chats/:roomId`. |
| `src/components/Navbar/HomeNavbar/index.tsx` (modify) | Adds the chats button beside "+" on Home. |
| `src/components/Home/index.tsx` (modify), `src/components/Home/ChatsList/` (delete) | Home stops listing conversations. |
| `visual/drives/chats.ts` (create), `visual/drives/home.ts`, `visual/drives/chat.ts`, `visual/drives/index.ts`, `visual/scenarios.json` (modify) | The inbox scenarios; the Home chats scenario removed; the new-room dialog scenario moved to the inbox. |

Mobile (`apps/mobile`):

| Path | Responsibility |
|---|---|
| `src/chats/chats-model.ts` (create) | `roomTarget(room)`: the push target for a row. |
| `src/chats/chats-model.test.ts` (create) | Targets per room kind. |
| `src/chats/chats-list.tsx` (create, moved from `src/home/chats-list.tsx`) | The full-height list with orb avatars and status words; no heading. |
| `src/chats/agents-row.tsx` (create) | The horizontal row of every agent's orb. |
| `app/chats.tsx` (create) | The screen: header (title, back, "+"), `AgentsRow`, `ChatsList`. |
| `app/_layout.tsx` (modify) | Registers `chats`; the route needs agents. |
| `app/index.tsx` (modify), `src/home/chats-list.tsx` (delete) | Home drops the list, gains the header button. |
| `visual/scenarios.json`, `maestro/visual/chat-states.yml` (modify) | `chats-screen` replaces `home-chats-section`; `new-room` opens from the chats screen. |

---

### Task 1: `roomRoute` (web)

**Files:**
- Create: `apps/web/src/layouts/ChatsLayout/room-route.ts`
- Test: `apps/web/src/layouts/ChatsLayout/room-route.test.ts`

**Interfaces:**
- Consumes: `Room`, `roomKind` from `@vesta/core`.
- Produces: `roomRoute(room: Room, wide: boolean): string`.

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/src/layouts/ChatsLayout/room-route.test.ts
import { describe, expect, it } from "vitest";
import type { Room } from "@vesta/core";
import { roomRoute } from "./room-route";

const direct: Room = {
  id: "dm:luna",
  name: null,
  agents: ["luna"],
  createdAt: 1_755_000_000,
  lastMessageAt: null,
};
const peer: Room = { ...direct, id: "peer-1", agents: ["atlas", "iris"] };
const group: Room = { ...direct, id: "grp-trip", name: "lisbon trip", agents: ["luna", "atlas"] };

describe("roomRoute", () => {
  it("selects any room inside the inbox at wide width", () => {
    expect(roomRoute(direct, true)).toBe("/chats/dm%3Aluna");
    expect(roomRoute(group, true)).toBe("/chats/grp-trip");
  });

  it("opens a direct room on its agent's page at narrow width", () => {
    expect(roomRoute(direct, false)).toBe("/agent/luna/chat");
  });

  it("opens a peer or group room on its own page at narrow width", () => {
    expect(roomRoute(peer, false)).toBe("/chat/peer-1");
    expect(roomRoute(group, false)).toBe("/chat/grp-trip");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run from `apps/`: `npm -w @vesta/web run test -- src/layouts/ChatsLayout/room-route.test.ts`
Expected: FAIL, cannot resolve `./room-route`.

- [ ] **Step 3: Write the implementation**

```ts
// apps/web/src/layouts/ChatsLayout/room-route.ts
import { roomKind, type Room } from "@vesta/core";

// Where a conversation row goes. Wide, every room is selected inside the inbox. Narrow, a direct
// room is its agent's own page and every other room has its own full-page route.
export function roomRoute(room: Room, wide: boolean): string {
  if (wide) return `/chats/${encodeURIComponent(room.id)}`;
  const first = room.agents[0];
  if (roomKind(room) === "direct" && first !== undefined) {
    return `/agent/${encodeURIComponent(first)}/chat`;
  }
  return `/chat/${encodeURIComponent(room.id)}`;
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm -w @vesta/web run test -- src/layouts/ChatsLayout/room-route.test.ts`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/layouts/ChatsLayout/room-route.ts apps/web/src/layouts/ChatsLayout/room-route.test.ts
git commit -m "feat(web): route a conversation row by width"
```

(knip will flag `roomRoute` as unused until Task 3 imports it; run `check.sh app-web` only after Task 3.)

---

### Task 2: `RoomPane` and `RoomLayout` (web)

**Files:**
- Create: `apps/web/src/components/RoomPane/index.tsx`
- Modify: `apps/web/src/layouts/RoomLayout/index.tsx`

**Interfaces:**
- Consumes: `RoomProvider` (`@/providers/RoomProvider`), `RoomSocketProvider` (`@/providers/RoomSocketProvider`), `Chat` (`@/components/Chat`), `useRoom` (`@/providers/RoomProvider/context`).
- Produces: `RoomPane({ roomId: string; children?: ReactNode })`. Children render inside both providers, above the chat body.

- [ ] **Step 1: Create `RoomPane`**

```tsx
// apps/web/src/components/RoomPane/index.tsx
import type { ReactNode } from "react";
import { Chat } from "@/components/Chat";
import { RoomProvider } from "@/providers/RoomProvider";
import { RoomSocketProvider } from "@/providers/RoomSocketProvider";

// One conversation's providers and its full-height transcript. Children mount inside the
// providers, so a navbar rendered here can read the room; the inbox passes none.
export function RoomPane({
  roomId,
  children,
}: {
  roomId: string;
  children?: ReactNode;
}) {
  return (
    <RoomProvider roomId={roomId}>
      <RoomSocketProvider>
        {children}
        <div className="relative flex min-h-0 flex-1 flex-col">
          <div className="absolute inset-0 flex flex-col">
            <Chat fullscreen />
          </div>
        </div>
      </RoomSocketProvider>
    </RoomProvider>
  );
}
```

- [ ] **Step 2: Rewrite `RoomLayout` on top of it**

Replace the whole file with:

```tsx
// apps/web/src/layouts/RoomLayout/index.tsx
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { Home } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { RoomPane } from "@/components/RoomPane";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useRoom } from "@/providers/RoomProvider/context";

// A conversation that is not one agent's own page: its whole screen is the chat, titled by the
// room and led by the way back to Home. The agent page keeps its own navbar and panes.
export function RoomLayout() {
  const { roomId } = useParams<{ roomId: string }>();
  if (roomId === undefined) return <Navigate to="/" replace />;

  return (
    <RoomPane roomId={roomId}>
      <RoomNavbar />
    </RoomPane>
  );
}

function RoomNavbar() {
  const { label } = useRoom();
  const navigate = useNavigate();

  return (
    <Navbar
      leading={
        <Button
          variant="outline"
          size="icon-lg"
          aria-label="home"
          onClick={() => {
            void navigate("/");
          }}
        >
          <Home />
        </Button>
      }
      center={<span className="truncate text-sm font-medium">{label}</span>}
      trailing={<StatusPill showHostname={false} />}
    />
  );
}
```

- [ ] **Step 3: Type-check and run the existing tests**

Run from `apps/`: `npm -w @vesta/web run check && npm -w @vesta/web run test -- src/providers/RoomProvider`
Expected: tsc clean; RoomProvider tests pass.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/RoomPane/index.tsx apps/web/src/layouts/RoomLayout/index.tsx
git commit -m "refactor(web): lift the room body into RoomPane"
```

---

### Task 3: `ChatsLayout`, `ConversationList`, routes (web)

**Files:**
- Create: `apps/web/src/layouts/ChatsLayout/ConversationList.tsx`
- Create: `apps/web/src/layouts/ChatsLayout/index.tsx`
- Test: `apps/web/src/layouts/ChatsLayout/index.test.tsx`
- Modify: `apps/web/src/router.tsx` (add two routes beside `chat/:roomId`)

**Interfaces:**
- Consumes: `roomRoute` (Task 1), `RoomPane` (Task 2), `useGateway` (`@/providers/GatewayProvider/context`, fields `rooms: Room[]`, `agents: AgentRow[]`, `agentsFetched: boolean`), `useOptionalController` (`@/providers/ControllerProvider/context`), `useAgentVisualStatus(controller, agent, activityState)` from `@vesta/core/react` returning `{ label, orbState }`, `Orb({ state, size, glow, suppressMotion })` from `@/components/Orb`, `useIsMobile` (`@/hooks/use-mobile`), `useLayout` (`@/stores/use-layout`, `navbarHeight`), `useDialogs` (`@/stores/use-dialogs`, `setOpen("newRoom", true)`), `NewRoomDialog` (`@/components/NewRoomDialog`), `Navbar`, `StatusPill`, `Button`, `cn` (`@/lib/utils`).
- Produces: `ChatsLayout`, `ChatsIndex`, `ChatsRoom` exports for the router.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/layouts/ChatsLayout/index.test.tsx
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Room } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { fakeAgentRow } from "@/test/fake-controller";
import { ChatsIndex, ChatsLayout, ChatsRoom } from ".";

vi.mock("@/components/Navbar", () => ({ Navbar: () => null }));
vi.mock("@/components/StatusPill", () => ({ StatusPill: () => null }));
vi.mock("@/components/NewRoomDialog", () => ({ NewRoomDialog: () => null }));
vi.mock("@/components/Orb", () => ({ Orb: () => null }));
vi.mock("@/components/RoomPane", () => ({
  RoomPane: ({ roomId }: { roomId: string }) => <p>pane {roomId}</p>,
}));

const mobile = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mobile.value }));

const rooms: Room[] = [
  { id: "dm:luna", name: null, agents: ["luna"], createdAt: 1, lastMessageAt: 1_755_600_000 },
  { id: "grp-trip", name: "lisbon trip", agents: ["luna", "atlas"], createdAt: 1, lastMessageAt: 1_755_500_000 },
  { id: "peer-1", name: null, agents: ["atlas", "iris"], createdAt: 1, lastMessageAt: null },
];

function renderAt(path: string) {
  const value: GatewayContextValue = {
    ...disconnectedValue,
    agentsFetched: true,
    agents: [fakeAgentRow("luna"), fakeAgentRow("atlas"), fakeAgentRow("iris")],
    rooms,
  };
  return render(
    <GatewayContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="chats" element={<ChatsLayout />}>
            <Route index element={<ChatsIndex />} />
            <Route path=":roomId" element={<ChatsRoom />} />
          </Route>
          <Route path="chat/:roomId" element={<p>full page</p>} />
          <Route path="agent/:name/chat" element={<p>agent page</p>} />
        </Routes>
      </MemoryRouter>
    </GatewayContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  mobile.value = false;
  useDialogs.getState().setOpen("newRoom", false);
});

describe("ChatsLayout", () => {
  it("lists every room in order with its label and members", () => {
    renderAt("/chats");
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("aria-label"))).toEqual([
      "open luna chat",
      "open lisbon trip chat",
      "open atlas & iris chat",
    ]);
    expect(screen.getByText("luna, atlas")).toBeTruthy();
    expect(screen.getByText("atlas, iris")).toBeTruthy();
  });

  it("links a row to its selection inside the inbox at wide width", () => {
    renderAt("/chats");
    expect(
      screen.getByRole("link", { name: "open lisbon trip chat" }).getAttribute("href"),
    ).toBe("/chats/grp-trip");
    expect(screen.getByText("pick a conversation")).toBeTruthy();
  });

  it("opens the selected room beside the list", () => {
    renderAt("/chats/grp-trip");
    expect(screen.getByText("pane grp-trip")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "open lisbon trip chat" }).getAttribute("aria-current"),
    ).toBe("page");
  });

  it("opens the new group dialog from the header", () => {
    renderAt("/chats");
    fireEvent.click(screen.getByRole("button", { name: "new group" }));
    expect(useDialogs.getState().open.newRoom).toBe(true);
  });

  it("links a row to the full page at narrow width", () => {
    mobile.value = true;
    renderAt("/chats");
    expect(
      screen.getByRole("link", { name: "open luna chat" }).getAttribute("href"),
    ).toBe("/agent/luna/chat");
    expect(
      screen.getByRole("link", { name: "open lisbon trip chat" }).getAttribute("href"),
    ).toBe("/chat/grp-trip");
  });

  it("redirects a selected room to its full page at narrow width", () => {
    mobile.value = true;
    renderAt("/chats/grp-trip");
    expect(screen.getByText("full page")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm -w @vesta/web run test -- src/layouts/ChatsLayout/index.test.tsx`
Expected: FAIL, cannot resolve `.` (no `index.tsx`).

- [ ] **Step 3: Write `ConversationList.tsx`**

```tsx
// apps/web/src/layouts/ChatsLayout/ConversationList.tsx
import { NavLink } from "react-router-dom";
import { Plus } from "lucide-react";
import { relativeTime, roomKind, roomLabel, type Room } from "@vesta/core";
import { useAgentVisualStatus } from "@vesta/core/react";
import { Orb } from "@/components/Orb";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { roomRoute } from "./room-route";

const DIRECT_ORB_SIZE = 44;
const MEMBER_ORB_SIZE = 30;
const CLUSTER_MAX = 3;

// An agent's orb and status word as the roster reports them; a name the roster lacks renders off.
function useMemberStatus(name: string) {
  const { agents } = useGateway();
  const agent = agents.find((row) => row.name === name) ?? null;
  return useAgentVisualStatus(
    useOptionalController(),
    agent,
    agent?.activityState ?? "idle",
  );
}

function MemberOrb({ name, size }: { name: string; size: number }) {
  const { orbState } = useMemberStatus(name);
  return <Orb state={orbState} size={size} glow={0.4} suppressMotion />;
}

function MemberStatus({ name }: { name: string }) {
  const { label } = useMemberStatus(name);
  return <>{label}</>;
}

function ChatRow({ room, wide }: { room: Room; wide: boolean }) {
  const kind = roomKind(room);
  const first = room.agents[0];
  const direct = kind === "direct" && first !== undefined;

  return (
    <li>
      <NavLink
        to={roomRoute(room, wide)}
        end
        aria-label={`open ${roomLabel(room)} chat`}
        className={({ isActive }) =>
          cn(
            "flex w-full min-w-0 items-center gap-3 rounded-xl py-2 pr-3 pl-2 text-left transition-colors hover:bg-muted",
            isActive && wide && "bg-muted",
          )
        }
      >
        {direct ? (
          <MemberOrb name={first} size={DIRECT_ORB_SIZE} />
        ) : (
          <span className="flex shrink-0 -space-x-2">
            {room.agents.slice(0, CLUSTER_MAX).map((name) => (
              <MemberOrb key={name} name={name} size={MEMBER_ORB_SIZE} />
            ))}
          </span>
        )}
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-sm leading-none font-medium">
            {roomLabel(room)}
          </span>
          <span className="truncate text-xs leading-none text-muted-foreground">
            {direct ? <MemberStatus name={first} /> : room.agents.join(", ")}
          </span>
        </span>
        {room.lastMessageAt !== null && (
          <span className="shrink-0 text-xs text-muted-foreground">
            {relativeTime(room.lastMessageAt)}
          </span>
        )}
      </NavLink>
    </li>
  );
}

// Every conversation on the node, busiest first, with the way to start a group in the header so a
// long list never scrolls it away.
export function ConversationList({ wide }: { wide: boolean }) {
  const { rooms } = useGateway();
  const openDialog = useDialogs((s) => s.setOpen);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-between px-3">
        <h2 className="text-xs text-muted-foreground">chats</h2>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="new group"
          onClick={() => {
            openDialog("newRoom", true);
          }}
        >
          <Plus />
        </Button>
      </div>
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2">
        {rooms.map((room) => (
          <ChatRow key={room.id} room={room} wide={wide} />
        ))}
      </ul>
    </div>
  );
}
```

If `Button` has no `icon-sm` size, use `size="icon"` (check `components/ui/button.tsx` for the size variants; pick the smallest square one).

- [ ] **Step 4: Write `index.tsx`**

```tsx
// apps/web/src/layouts/ChatsLayout/index.tsx
import { Navigate, Outlet, useNavigate, useParams } from "react-router-dom";
import { Home } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { NewRoomDialog } from "@/components/NewRoomDialog";
import { RoomPane } from "@/components/RoomPane";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useLayout } from "@/stores/use-layout";
import { ConversationList } from "./ConversationList";
import { roomRoute } from "./room-route";

const LIST_WIDTH_CLASS = "w-80";

// The inbox: every conversation on the left, the selected one on the right, the selection in the
// URL. Narrow, the list stands alone and a row opens the full-page chat; the outlet stays mounted
// so a selected room can redirect there.
export function ChatsLayout() {
  const navigate = useNavigate();
  const wide = !useIsMobile();
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <>
      <Navbar
        leading={
          <Button
            variant="outline"
            size="icon-lg"
            aria-label="home"
            onClick={() => {
              void navigate("/");
            }}
          >
            <Home />
          </Button>
        }
        center={<span className="truncate text-sm font-medium">chats</span>}
        trailing={<StatusPill showHostname={false} />}
      />
      <div className="flex min-h-0 w-full flex-1">
        <aside
          className={cn(
            "flex min-h-0 shrink-0 flex-col pb-4",
            wide ? LIST_WIDTH_CLASS : "w-full",
          )}
          style={{ paddingTop: navbarHeight }}
        >
          <ConversationList wide={wide} />
        </aside>
        <div
          className={cn(
            "relative flex min-h-0 flex-1 flex-col",
            !wide && "hidden",
          )}
        >
          <Outlet />
        </div>
      </div>
      <NewRoomDialog />
    </>
  );
}

export function ChatsIndex() {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  return (
    <div
      className="flex flex-1 items-center justify-center text-sm text-muted-foreground"
      style={{ paddingTop: navbarHeight }}
    >
      pick a conversation
    </div>
  );
}

// The selected room. Narrow, the inbox has no pane, so the selection becomes the full-page route
// for that room; a loaded tree that lacks the id sends the inbox back to nothing selected.
export function ChatsRoom() {
  const { roomId } = useParams<{ roomId: string }>();
  const wide = !useIsMobile();
  const { rooms, agentsFetched } = useGateway();
  if (roomId === undefined) return <Navigate to="/chats" replace />;
  if (wide) return <RoomPane roomId={roomId} />;
  const room = rooms.find((candidate) => candidate.id === roomId);
  if (room === undefined) {
    return agentsFetched ? <Navigate to="/chats" replace /> : null;
  }
  return <Navigate to={roomRoute(room, false)} replace />;
}
```

- [ ] **Step 5: Register the routes**

In `apps/web/src/router.tsx`, add the import and, directly after the `chat/:roomId` entry, the new family:

```tsx
import { ChatsIndex, ChatsLayout, ChatsRoom } from "@/layouts/ChatsLayout";
```

```tsx
            {
              path: "chats",
              element: <ChatsLayout />,
              errorElement: <RouteErrorBoundary />,
              children: [
                { index: true, element: <ChatsIndex /> },
                { path: ":roomId", element: <ChatsRoom /> },
              ],
            },
```

- [ ] **Step 6: Run the tests until they pass**

Run: `npm -w @vesta/web run test -- src/layouts/ChatsLayout`
Expected: 9 passed (3 from Task 1, 6 here). If the "new group" button is not found, check the `Button` size variant you chose renders a `button` element with the `aria-label`.

- [ ] **Step 7: Lint, type-check, and check dead exports**

Run from the worktree root: `./check.sh app-web`
Expected: green. If knip flags `ChatsIndex`/`ChatsRoom`, confirm `router.tsx` imports both.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/layouts/ChatsLayout apps/web/src/router.tsx
git commit -m "feat(web): the chats inbox with the selected room beside the list"
```

---

### Task 4: The way in, and Home without its list (web)

**Files:**
- Modify: `apps/web/src/components/Navbar/HomeNavbar/index.tsx` (the `Leading` component)
- Modify: `apps/web/src/components/Home/index.tsx` (line 14 import, line 108 mount)
- Delete: `apps/web/src/components/Home/ChatsList/index.tsx`

- [ ] **Step 1: Add the chats button beside "+"**

In `HomeNavbar/index.tsx`, add `MessageSquare` to the lucide import and change the Home branch of `Leading` to return both buttons:

```tsx
import { Home, MessageSquare, Plus } from "lucide-react";
```

```tsx
  if (isHome && (!reachable || agentsFetched)) {
    return (
      <>
        <Button
          variant="outline"
          size="icon-lg"
          aria-label="new agent"
          onClick={() => {
            if (!reachable) {
              toast.error("can't reach the gateway right now");
              return;
            }
            void navigate("/new");
          }}
        >
          <Plus />
        </Button>
        <Button
          variant="outline"
          size="icon-lg"
          aria-label="chats"
          onClick={() => {
            void navigate("/chats");
          }}
        >
          <MessageSquare />
        </Button>
      </>
    );
  }
```

- [ ] **Step 2: Remove the list from Home**

In `components/Home/index.tsx` delete `import { ChatsList } from "./ChatsList";` and the `<ChatsList />` line, then delete the folder:

```bash
git rm -r apps/web/src/components/Home/ChatsList
```

- [ ] **Step 3: Check**

Run: `./check.sh app-web`
Expected: green (knip no longer sees `ChatsList`; nothing else imported it).

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/Navbar/HomeNavbar/index.tsx apps/web/src/components/Home/index.tsx
git commit -m "feat(web): reach the chats inbox from Home and drop Home's list"
```

---

### Task 5: Web visual scenarios

**Files:**
- Create: `apps/web/visual/drives/chats.ts`
- Modify: `apps/web/visual/drives/home.ts` (remove `CHATS_AGENTS`, `CHATS_ROOMS`, `chatsState`, the `home-chats-list` and `new-room-dialog` entries, and the now-unused `directRooms` import if nothing else in the file uses it)
- Modify: `apps/web/visual/drives/chat.ts` (export `GROUP_ROOM`, `GROUP_AGENTS`, `GROUP_HISTORY`)
- Modify: `apps/web/visual/drives/index.ts` (register `"chats.ts": CHATS`)
- Modify: `apps/web/visual/scenarios.json`

- [ ] **Step 1: Export the group fixture from `chat.ts`**

Change the three `const` declarations to `export const GROUP_ROOM`, `export const GROUP_AGENTS`, `export const GROUP_HISTORY` (same values).

- [ ] **Step 2: Write `chats.ts`**

Move `CHATS_AGENTS`, `CHATS_ROOMS`, and `chatsState` out of `home.ts` verbatim, then:

```ts
// apps/web/visual/drives/chats.ts
import type { Page } from "@playwright/test";
import { AGENT } from "../harness/http-fixtures";
import { chatRoutes } from "../harness/chat-fixtures";
import { FIXED_TIME, type Scenario, type ScenarioState } from "../harness/scenario-state";
import { agentNode, directRooms } from "../harness/sync-fixtures";
import { GROUP_HISTORY, GROUP_ROOM } from "./chat";

const CHATS_ROUTE = "/chats";
const noDrive = (): Promise<void> => Promise.resolve();

// The inbox fixture: the agents' own chats plus a group and a pair, each with the time of its last
// message. The group is the one the chat drives carry history for, so selecting it renders bubbles.
const CHATS_AGENTS = Object.fromEntries(
  [AGENT, "atlas", "iris"].map((name) => [name, agentNode()] as const),
);
const CHATS_ROOMS = [
  ...directRooms(CHATS_AGENTS).map((room, index) => ({
    ...room,
    lastMessageAt: FIXED_TIME.getTime() / 1000 - (index + 1) * 900,
  })),
  {
    id: GROUP_ROOM,
    name: "lisbon trip",
    agents: [AGENT, "atlas"],
    createdAt: 1_755_400_000,
    lastMessageAt: FIXED_TIME.getTime() / 1000 - 4 * 3600,
  },
  {
    id: "peer-research",
    name: null,
    agents: ["atlas", "iris"],
    createdAt: 1_755_300_000,
    lastMessageAt: FIXED_TIME.getTime() / 1000 - 3 * 86400,
  },
];

function chatsState(route = CHATS_ROUTE): ScenarioState {
  return {
    route,
    sync: { agents: CHATS_AGENTS, rooms: CHATS_ROOMS },
  };
}

async function openNewGroup(page: Page): Promise<void> {
  await page.getByRole("button", { name: "new group" }).click();
  await page.getByLabel("group name").fill("weekend plans");
  await page.getByRole("checkbox").first().click();
}

export const CHATS: Record<string, Scenario> = {
  "chats-empty": { state: chatsState(), drive: noDrive },
  "chats-selected": {
    state: {
      ...chatsState(`${CHATS_ROUTE}/${GROUP_ROOM}`),
      routes: chatRoutes(GROUP_ROOM, { events: GROUP_HISTORY }),
      chatSocket: { events: [] },
    },
    drive: noDrive,
  },
  "chats-narrow": { state: chatsState(), drive: noDrive },
  "new-room-dialog": { state: chatsState(), drive: openNewGroup },
};
```

Check the exact export names of `AGENT`, `chatRoutes`, `agentNode`, `directRooms` against `harness/http-fixtures.ts`, `harness/chat-fixtures.ts`, `harness/sync-fixtures.ts` (the names above come from the current `home.ts` and `chat.ts` imports).

- [ ] **Step 3: Register the area and the cards**

In `drives/index.ts` add `import { CHATS } from "./chats";` and `"chats.ts": CHATS,` to `AREAS`.

In `scenarios.json`: delete the `home-chats-list` card; move the `new-room-dialog` card next to the new ones with `"group": "Chat"`; add:

```json
    {
      "id": "chats-empty",
      "title": "Chats, nothing selected",
      "description": "The inbox: every conversation busiest first, the pane waiting for a pick.",
      "group": "Chat",
      "platforms": ["web", "desktop"]
    },
    {
      "id": "chats-selected",
      "title": "Chats, a room open",
      "description": "The inbox with the lisbon trip group selected and its transcript beside the list.",
      "group": "Chat",
      "platforms": ["web", "desktop"]
    },
    {
      "id": "chats-narrow",
      "title": "Chats, narrow",
      "description": "The conversation list alone on a narrow viewport.",
      "group": "Chat",
      "platforms": ["web-narrow"]
    },
```

- [ ] **Step 4: Registry test, then capture**

Run: `npm -w @vesta/web run test -- visual/registry.test.ts`
Expected: pass (ids match drives).

Run from `apps/web`: `VISUAL_SUITE=states npx playwright test --config visual/playwright.config.ts -g "chats-empty|chats-selected|chats-narrow|new-room-dialog"`
Expected: all pass. Open `apps/visual/.visual/shots/web/chats-selected.png` and `web-narrow/chats-narrow.png` and confirm: rows with orbs, the group's members on its second line, the agent's status word on a direct row, the selected row tinted, the transcript beside the list, and on narrow the list alone.

- [ ] **Step 5: Commit**

```bash
git add apps/web/visual
git commit -m "test(visual): capture the chats inbox and retire the Home chats list"
```

---

### Task 6: `roomTarget` (mobile)

**Files:**
- Create: `apps/mobile/src/chats/chats-model.ts`
- Test: `apps/mobile/src/chats/chats-model.test.ts`

**Interfaces:**
- Produces: `roomTarget(room: Room): RoomTarget` where `RoomTarget = { pathname: "/agent/[name]"; params: { name: string } } | { pathname: "/chat/[roomId]"; params: { roomId: string } }`, the exact shape `router.push` takes.

- [ ] **Step 1: Write the failing test**

```ts
// apps/mobile/src/chats/chats-model.test.ts
import { describe, expect, it } from "vitest";
import type { Room } from "@vesta/core";
import { roomTarget } from "./chats-model";

const direct: Room = { id: "dm:aria", name: null, agents: ["aria"], createdAt: 1, lastMessageAt: null };
const peer: Room = { ...direct, id: "peer-1", agents: ["aria", "nova"] };
const group: Room = { ...direct, id: "grp-launch", name: "Launch week", agents: ["aria", "nova"] };

describe("roomTarget", () => {
  it("sends a direct room to its agent's screen", () => {
    expect(roomTarget(direct)).toEqual({ pathname: "/agent/[name]", params: { name: "aria" } });
  });

  it("sends a peer or group room to its own screen", () => {
    expect(roomTarget(peer)).toEqual({ pathname: "/chat/[roomId]", params: { roomId: "peer-1" } });
    expect(roomTarget(group)).toEqual({ pathname: "/chat/[roomId]", params: { roomId: "grp-launch" } });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run from `apps/`: `npm -w @vesta/mobile run test -- src/chats/chats-model.test.ts`
Expected: FAIL, cannot resolve `./chats-model`.

- [ ] **Step 3: Write the implementation**

```ts
// apps/mobile/src/chats/chats-model.ts
import { roomKind, type Room } from "@vesta/core";

export type RoomTarget =
  | { pathname: "/agent/[name]"; params: { name: string } }
  | { pathname: "/chat/[roomId]"; params: { roomId: string } };

// A direct room is that agent's own screen; every other room has its own.
export function roomTarget(room: Room): RoomTarget {
  const first = room.agents[0];
  if (roomKind(room) === "direct" && first !== undefined) {
    return { pathname: "/agent/[name]", params: { name: first } };
  }
  return { pathname: "/chat/[roomId]", params: { roomId: room.id } };
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm -w @vesta/mobile run test -- src/chats/chats-model.test.ts`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mobile/src/chats/chats-model.ts apps/mobile/src/chats/chats-model.test.ts
git commit -m "feat(mobile): the screen a conversation row opens"
```

---

### Task 7: The chats screen (mobile)

**Files:**
- Create: `apps/mobile/src/chats/chats-list.tsx` (from `src/home/chats-list.tsx`)
- Create: `apps/mobile/src/chats/agents-row.tsx`
- Create: `apps/mobile/app/chats.tsx`
- Modify: `apps/mobile/app/_layout.tsx` (register the screen; line 88 `routeNeedsAgents`)
- Modify: `apps/mobile/app/index.tsx` (remove the `ChatsList` import at line 27 and its `<View>` wrapper at lines 270–272; add the header button)
- Delete: `apps/mobile/src/home/chats-list.tsx`

**Interfaces:**
- Consumes: `roomTarget` (Task 6), `useRoster()` (`agents: AgentRow[]`, `rooms: Room[]`), `AgentOrb` (`@/components/AgentOrb`, props `name?, status, activityState?, operation?, booting?, rateLimited?, size?`), `agentVisualStatus` from `@vesta/core`, `useAgentRequest` from `@vesta/core/react`, `ControllerContext` (`@/controller/context`), `Text` (`@/components/ui/Typography`), `Screen` (`@/components/layout/Screen`), `usePreferences().colors`, `radii` (`@/theme/layout`).

- [ ] **Step 1: Move the list and rework its rows**

```bash
git mv apps/mobile/src/home/chats-list.tsx apps/mobile/src/chats/chats-list.tsx
```

Replace the file's contents with:

```tsx
// apps/mobile/src/chats/chats-list.tsx
import { use } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import {
  agentVisualStatus,
  relativeTime,
  roomKind,
  roomLabel,
  type AgentRow,
  type Room,
} from "@vesta/core";
import { useAgentRequest } from "@vesta/core/react";
import { AgentOrb } from "@/components/AgentOrb";
import { Text } from "@/components/ui/Typography";
import { ControllerContext } from "@/controller/context";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { radii } from "@/theme/layout";
import { roomTarget } from "./chats-model";

const DIRECT_ORB_SIZE = 40;
const MEMBER_ORB_SIZE = 26;
const CLUSTER_MAX = 3;
const CLUSTER_OVERLAP = -8;

function useAgentRow(name: string): AgentRow | null {
  const { agents } = useRoster();
  return agents.find((row) => row.name === name) ?? null;
}

function MemberOrb({ name, size }: { name: string; size: number }) {
  const agent = useAgentRow(name);
  if (agent === null) return <View style={{ width: size, height: size }} />;
  return (
    <AgentOrb
      name={name}
      status={agent.status}
      activityState={agent.activityState}
      operation={agent.operation}
      booting={agent.booting}
      rateLimited={agent.rateLimited ?? null}
      size={size}
      animated={false}
    />
  );
}

// The status word the carousel's badge shows, as plain text.
function MemberStatus({ name }: { name: string }) {
  const agent = useAgentRow(name);
  const { request } = useAgentRequest(use(ControllerContext), name);
  const { colors } = usePreferences();
  const label =
    agent === null
      ? ""
      : agentVisualStatus(
          {
            status: agent.status,
            operation: agent.operation,
            booting: agent.booting,
            rateLimited: agent.rateLimited,
          },
          request,
          agent.activityState,
        ).label;
  return (
    <Text numberOfLines={1} style={[styles.rowDetail, { color: colors.tertiaryText }]}>
      {label}
    </Text>
  );
}

function ChatRow({ room }: { room: Room }) {
  const router = useRouter();
  const { colors } = usePreferences();
  const kind = roomKind(room);
  const label = roomLabel(room);
  const first = room.agents[0];
  const direct = kind === "direct" && first !== undefined;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${label} chat`}
      onPress={() => {
        router.push(roomTarget(room));
      }}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: colors.card, opacity: pressed ? 0.6 : 1 },
      ]}
    >
      {direct ? (
        <MemberOrb name={first} size={DIRECT_ORB_SIZE} />
      ) : (
        <View style={styles.cluster}>
          {room.agents.slice(0, CLUSTER_MAX).map((name, index) => (
            <View key={name} style={index > 0 ? styles.clusterMember : null}>
              <MemberOrb name={name} size={MEMBER_ORB_SIZE} />
            </View>
          ))}
        </View>
      )}
      <View style={styles.rowText}>
        <Text numberOfLines={1} style={[styles.rowLabel, { color: colors.text }]}>
          {label}
        </Text>
        {direct ? (
          <MemberStatus name={first} />
        ) : (
          <Text numberOfLines={1} style={[styles.rowDetail, { color: colors.tertiaryText }]}>
            {room.agents.join(", ")}
          </Text>
        )}
      </View>
      {room.lastMessageAt !== null ? (
        <Text style={[styles.rowTime, { color: colors.tertiaryText }]}>
          {relativeTime(room.lastMessageAt)}
        </Text>
      ) : null}
    </Pressable>
  );
}

// Every conversation on the node, busiest first, filling the chats screen under the agent row.
export function ChatsList() {
  const { rooms } = useRoster();
  return (
    <ScrollView contentContainerStyle={styles.rows} showsVerticalScrollIndicator={false}>
      {rooms.map((room) => (
        <ChatRow key={room.id} room={room} />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  rows: { gap: 6, paddingHorizontal: 16, paddingBottom: 24 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: radii.control,
    borderCurve: "continuous",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  cluster: { flexDirection: "row", alignItems: "center" },
  clusterMember: { marginLeft: CLUSTER_OVERLAP },
  rowText: { flex: 1, minWidth: 0, gap: 2 },
  rowLabel: { fontSize: 15, fontWeight: "600" },
  rowDetail: { fontSize: 12 },
  // Never squeezed by a long room name: the label truncates instead.
  rowTime: { fontSize: 12, flexShrink: 0 },
});
```

Check `AgentOrb`'s `activityState` default and whether `booting` accepts `undefined` (it is optional in `AgentOrbProps`); `agentVisualStatus`'s `AgentVisualSource` takes `booting?` and `rateLimited?`, so passing `agent.rateLimited` (possibly `undefined`) is fine.

- [ ] **Step 2: Write `agents-row.tsx`**

```tsx
// apps/mobile/src/chats/agents-row.tsx
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { AgentOrb } from "@/components/AgentOrb";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";

const ORB_SIZE = 64;

// Every agent as its orb, the fast way to one agent's own page above the conversation list.
export function AgentsRow() {
  const router = useRouter();
  const { agents } = useRoster();
  const { colors } = usePreferences();

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {agents.map((agent) => (
        <Pressable
          key={agent.name}
          accessibilityRole="button"
          accessibilityLabel={`Open ${agent.name}`}
          onPress={() => {
            router.push({ pathname: "/agent/[name]", params: { name: agent.name } });
          }}
          style={({ pressed }) => [styles.item, { opacity: pressed ? 0.6 : 1 }]}
        >
          <AgentOrb
            name={agent.name}
            status={agent.status}
            activityState={agent.activityState}
            operation={agent.operation}
            booting={agent.booting}
            rateLimited={agent.rateLimited ?? null}
            size={ORB_SIZE}
          />
          <Text
            family="serif"
            numberOfLines={1}
            style={[styles.name, { color: colors.text }]}
          >
            {agent.name}
          </Text>
        </Pressable>
      ))}
      <View style={styles.tail} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 18, paddingHorizontal: 20, paddingVertical: 8 },
  item: { alignItems: "center", gap: 6, width: ORB_SIZE + 16 },
  name: { fontSize: 13, fontWeight: "500" },
  tail: { width: 4 },
});
```

- [ ] **Step 3: Write the screen**

```tsx
// apps/mobile/app/chats.tsx
import { Pressable, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import { Ionicons } from "@expo/vector-icons";
import { AgentsRow } from "@/chats/agents-row";
import { ChatsList } from "@/chats/chats-list";
import { Screen } from "@/components/layout/Screen";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

// The inbox: every agent's orb over every conversation, with the way to start a group in the
// header so a long list never scrolls it away.
export default function ChatsScreen() {
  const router = useRouter();
  const { colors } = usePreferences();
  const openNewRoom = () => router.push("/new-room");

  return (
    <Screen scroll={false} contentStyle={styles.screen}>
      <Stack.Screen
        options={{
          title: "Chats",
          headerTitleAlign: "center",
          headerRight: IS_IOS
            ? undefined
            : () => (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="New group"
                  hitSlop={8}
                  onPress={openNewRoom}
                  style={[styles.headerButton, { backgroundColor: colors.elevated }]}
                >
                  <Ionicons name="add" size={22} color={colors.text} />
                </Pressable>
              ),
        }}
      />
      {IS_IOS ? (
        <Stack.Toolbar placement="right">
          <Stack.Toolbar.Button
            accessibilityLabel="New group"
            icon="plus"
            tintColor={colors.text}
            onPress={openNewRoom}
          />
        </Stack.Toolbar>
      ) : null}
      <View style={styles.body}>
        <AgentsRow />
        <ChatsList />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { padding: 0 },
  body: { flex: 1, gap: 8 },
  headerButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
});
```

The body must clear the transparent header. Look at how `app/chat/[roomId].tsx` or `app/debug.tsx` offsets content under the header (a top inset from `navHeaderHeight` in `@/theme/layout` plus `useSafeAreaInsets().top`, or the Android opaque-header options); apply the same to `styles.body` or to the `Stack.Screen` options so the orb row is not hidden under the title.

- [ ] **Step 4: Register the screen and gate it on agents**

In `app/_layout.tsx`, inside `<Stack.Protected guard={status === "connected"}>` next to `chat/[roomId]`:

```tsx
              <Stack.Screen
                name="chats"
                options={{
                  title: "Chats",
                  headerTitleAlign: "center",
                  ...(IS_ANDROID
                    ? {
                        headerTransparent: false,
                        headerStyle: { backgroundColor: colors.background },
                      }
                    : {}),
                }}
              />
```

At line 88 make the chats route wait for the roster like Home does:

```ts
  const routeNeedsAgents =
    isHomeRoute || activeRoute === "agent" || activeRoute === "chats";
```

(Read the surrounding lines first; `activeRoute` may be derived differently, match its existing form.)

- [ ] **Step 5: Home: drop the list, add the button**

In `app/index.tsx`:
- delete `import { ChatsList } from "@/home/chats-list";` (line 27) and the wrapper at lines 270–272 (`<View style={{ paddingBottom: ... }}><ChatsList /></View>`); if `insets` is then unused in `HomeScreen`, remove that `useSafeAreaInsets()` call there (keep the one in `HomeSkeleton` if it still uses it);
- in `HomeHeader`, add `const openChats = () => router.push("/chats");`, and:
  - iOS: add a second button to the left toolbar:
    ```tsx
            <Stack.Toolbar.Button
              accessibilityLabel="Chats"
              icon="message"
              tintColor={colors.text}
              onPress={openChats}
            />
    ```
    directly after the "Create agent" button inside the same `<Stack.Toolbar placement="left">`;
  - Android: make `headerLeft` return a row of two `HomeHeaderButton`s:
    ```tsx
              : () => (
                  <View style={styles.headerButtons}>
                    <HomeHeaderButton
                      accessibilityLabel="Create agent"
                      icon="add"
                      iconSize={22}
                      onPress={openCreateAgent}
                    />
                    <HomeHeaderButton
                      accessibilityLabel="Chats"
                      icon="chatbubbles-outline"
                      iconSize={20}
                      onPress={openChats}
                    />
                  </View>
                ),
    ```
    and add `headerButtons: { flexDirection: "row", gap: 8 }` to `styles`. Keep the `showCreate` gating as it is for the create button only (render the chats button regardless).

If `Stack.Toolbar.Button`'s `icon` rejects `"message"`, use `"bubble.left.and.bubble.right"` (both are SF Symbol names).

- [ ] **Step 6: Delete the old file's directory if empty, then check**

```bash
rmdir apps/mobile/src/home 2>/dev/null || true
```

Run from the worktree root: `./check.sh app-mobile`
Expected: green (lint, tsc, vitest, clean prebuild). If `expo lint` reports `import/no-unresolved` for a package that is installed, delete `apps/mobile/.expo/cache/eslint` and re-run.

- [ ] **Step 7: Commit**

```bash
git add apps/mobile
git commit -m "feat(mobile): the chats screen with every agent over every conversation"
```

---

### Task 8: Mobile visual scenarios

**Files:**
- Modify: `apps/mobile/visual/scenarios.json`
- Modify: `apps/mobile/maestro/visual/chat-states.yml` (the last two blocks)

- [ ] **Step 1: Cards**

Replace the `home-chats-section` card with:

```json
    {
      "id": "chats-screen",
      "title": "Chats",
      "description": "Every agent's orb over every conversation, busiest first.",
      "group": "Chat"
    },
```

and change the `new-room` card's `"group"` to `"Chat"`.

- [ ] **Step 2: Flow**

Replace the `home-chats-section` block (from its `- openLink:` through its `runScript`) with:

```yaml
- stopApp
- openLink:
    link: "vesta-dev://chats?visualPrivacy=unlocked&visualSession=connected&visualRoster=agents&visualRooms=group"
- runFlow: wait-for-launch.yml
- extendedWaitUntil:
    visible: "Open Launch week chat"
    timeout: 30000
- waitForAnimationToEnd:
    timeout: 3000
- takeScreenshot: chats-screen
- runScript:
    file: capture-screenshot.js
    env:
      SCREENSHOT: chats-screen.png
```

Keep the `new-room` block that follows; its `tapOn: text: "New group"` now matches the header button's accessibility label.

- [ ] **Step 3: Capture on iOS**

Run from `apps/`: `npm run visual:capture -- ios` (or the narrower `VISUAL_SUITE=states` form the runner documents in `mobile/visual/README.md`), then open `apps/visual/.visual/shots/ios/chats-screen.png` and `new-room.png`. Confirm the orb row, the rows with orbs and status words, and that "+" opened the new-room sheet.

- [ ] **Step 4: Commit**

```bash
git add apps/mobile/visual/scenarios.json apps/mobile/maestro/visual/chat-states.yml
git commit -m "test(visual): capture the mobile chats screen"
```

---

### Task 9: Full checks and the PR

- [ ] **Step 1: Run every affected slice**

From the worktree root: `./check.sh app-core && ./check.sh app-web && ./check.sh app-mobile`
Expected: all green.

- [ ] **Step 2: Push and open the PR against `feat/chat-rooms`**

```bash
git push -u origin feat/chats-inbox
gh pr create --base feat/chat-rooms --title "feat(apps): the chats inbox" --body-file - <<'BODY'
## What

A `/chats` route on web (every conversation beside the open one, selection in the URL; the list alone below 768px) and a `chats` screen on mobile (every agent's orb over the conversation list), both reached from a button on Home. Home stops listing conversations. Nothing changes on the wire.

Spec: docs/superpowers/specs/2026-09-09-chats-inbox-design.md

## Follow-ups

- last message preview and sender on each row (additive `lastMessage` on the `/sync` room branch)
- unread mark (per-room seen watermark)
- search in the list

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
```

- [ ] **Step 3: Verify mergeability once CI reports**

`gh pr checks <number>`; resolve anything red before calling it done.
