# Chats inbox

A conversation list with the open conversation beside it, on its own route, reached from Home. It takes the structure of a messaging app's inbox: every room is a row with its avatar, name, a second line, and the time of its last message; on a wide screen the selected room opens next to the list, and on a narrow screen a row opens the full-page chat. It keeps Vesta's skin: the orbs as avatars, the app's tokens, and the one `Chat` transcript every surface already renders.

This builds on `feat/chat-rooms`, which introduced rooms (direct, peer, group) on the node and the `/sync` room list.

## Goals

- One place that lists every conversation, busiest first.
- On wide web and desktop, a split view: pick a row, the chat opens in place, the URL carries the selection.
- On narrow web and on the phone, a list that opens the existing chat screens.
- Home keeps its carousel and stops listing conversations.

## Non-goals (follow-ups, each its own PR)

- A last-message preview and its sender on each row. The room on `/sync` carries only `id`, `name`, `agents`, `createdAt`, `lastMessageAt`; a preview is an additive `lastMessage` field on vestad's room branch plus the core parser and fixtures.
- An unread mark. It needs a per-room seen watermark the client advances and vestad persists, the way `user_notifications_seen_at` works for the notification feed.
- Search in the list. With only names to match, a box is chrome.
- Any change to the chat transcript's look. The right pane is today's `Chat`, unchanged.

## Web

### Routes

Two routes join the guarded tree in `apps/web/src/router.tsx`, siblings of `chat/:roomId`:

```
chats            ChatsLayout, index child: EmptyPane
chats/:roomId    ChatsLayout, child: RoomPane
```

### `layouts/ChatsLayout`

Renders a `Navbar` (leading: the Home button; center: "chats"; trailing: `StatusPill`) over a two-column body: `ConversationList` at a fixed width on the left, an `Outlet` filling the right.

Below 768px (`useIsMobile`) the layout is one column: `/chats` shows `ConversationList` full width, and `/chats/:roomId` redirects to the full-page target for that room (see `roomRoute`).

### `components/RoomPane`

The body of today's `layouts/RoomLayout` lifted into one component taking `roomId`: `RoomProvider` around `RoomSocketProvider` around `Chat fullscreen`. `RoomLayout` keeps its navbar and renders `RoomPane` under it, so the full-page room route behaves as before and the provider stack lives once. `RoomProvider` already redirects to Home when a loaded tree lacks the id, so a stale `/chats/:roomId` cannot strand the page.

A direct room opens in the pane like any room: `RoomProvider` resolves `dm:<agent>` from the tree. The agent page's chat pane is a separate mount under its own route; chat tails and drafts are core holds keyed per room and connection, so both mounts show the same conversation and the same unsent draft.

### `ChatsLayout/ConversationList`

Private to the layout folder. A header row with the "+" button (opens the existing `newRoom` dialog) and a list of every room from `useGateway().rooms`, already ordered by `selectRooms`. Each row is a `NavLink` to `/chats/:roomId` at wide width, so the selected row is styled from the URL; at narrow width the row navigates with `roomRoute`.

A row:

```
(orb)  luna                    15m ago
       ready

(orbs) lisbon trip              4h ago
       luna, atlas
```

- Avatar: the agent's own `AgentOrb` for a direct room; a small cluster of the members' orbs for a peer or group room. Status stays readable in the list the way it is on the cards.
- Name: `roomLabel(room)`, the app's medium weight.
- Second line, muted: the members for a peer or group room; the agent's status word for a direct room, the one the carousel computes. No row shows a blank line.
- Time, muted, right-aligned: `relativeTime(room.lastMessageAt)`; nothing when the room has no message yet.

### `roomRoute(room, wide)`

One function beside the layout owns both targets:

- wide: `/chats/${room.id}`
- narrow: `/agent/${agent}/chat` for a direct room, `/chat/${room.id}` otherwise

### The way in

`HomeNavbar` gains a button next to "+" and the bell: a `MessageSquare` icon, `aria-label="chats"`, navigating to `/chats`. The `ChatsLayout` navbar's Home button is the way back.

### Removals

`components/Home/ChatsList` and its mount in `components/Home`. Home returns to its pre-rooms shape apart from the navbar button.

## Mobile

### Screen

`app/chats.tsx`, registered in `app/_layout.tsx`, reached from a header button on Home matching the web one. Header: back to Home, title "Chats", "+" pushing the existing `new-room` screen.

```
(orb)   (orb)   (orb)   (orb)      every agent, horizontal scroll
luna    atlas   iris    nova

(orb) luna                  15m
      ready
(orb) lisbon trip            4h
      luna, atlas
```

- The orb row lists every agent; tapping one pushes that agent's page. With no usage signal on the wire yet, a "most used" pick would be a guess; busiest-first order for this row arrives with the preview work.
- The list is the branch's `src/home/chats-list.tsx` moved to `src/chats/chats-list.tsx`, same rows and same targets: a direct row pushes the agent screen, any other row pushes `/chat/[roomId]`. Its second line and avatar follow the web row above.

### Removals

The `ChatsList` mount and the "New group" reach-from-Home code in `app/index.tsx`. Home keeps its carousel.

## Wire

Nothing changes. The page reads the room list `/sync` already carries.

## Tests

- Vitest, web: `roomRoute` for each room kind at wide and narrow; the narrow redirect of `/chats/:roomId`; the list's order and labels through the core helpers.
- Vitest, mobile: the moved list's targets per room kind.
- Visual, web: `chats-empty` (wide, nothing selected), `chats-selected` (wide, the "lisbon trip" room open), `chats-narrow` (the list alone, narrow project), light and dark, reusing the branch's `chatsState()` fixture. `home-chats-list` is removed; `new-room-dialog` opens from the inbox.
- Visual, mobile: `chats-screen`. `home-chats-section` is removed; `new-room` opens from the chats screen.
- `check.sh app-core`, `app-web`, `app-mobile`.
