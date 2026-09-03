# App-chat attachments

**Date:** 2026-08-30
**Status:** Design draft, pending review. No code written.

## Goal

The user sends any file (image, video, audio, document, anything) to their agent through app chat, WhatsApp-style. The agent receives a real file on its own disk plus a notification, so it can read the file with its normal tools. The agent can send attachments back, and the client renders typed bubbles the user can view and download. Web and desktop ship first. The wire contract and the @vesta/core modules are shared, so mobile reuses everything except the view layer.

## Ground truth (what exists today)

Every claim below was verified in the current tree.

- **The chat plane is owned end to end by the app-chat skill** (`agent/skills/app-chat/cli/src/app_chat_cli/`): aiohttp service with `POST /message`, `GET /history`, `GET /ws`, `GET /health`, reached through vestad's per-agent proxy. Events are JSON blobs in sqlite (`~/.app-chat/app-chat.db`, `events(id, ts, data)`); `store.page()` surfaces only `type in ("user","chat")`.
- **The chat plane is additive-tolerant.** `chat-socket.ts` does a bare `JSON.parse` with no field validation, and history is unvalidated `http.json`. An optional field added to `user`/`chat` events is invisible to shipped clients. No `/sync` frame changes, no `sync-protocol.json` regen, no `min_supported` bump.
- **Intake is at-most-once** (`service.py::message_handler`): the notification file write is deliberately the only fallible step before persist + emit, and `intent_id` dedup makes a retry re-run intake exactly once. Any attachment design must not add a fallible step inside that handler.
- **vestad proxy limits**: request bodies are fully buffered at `PROXY_MAX_BODY_BYTES = 10 MiB` (`vestad/src/state.rs:17`, `vestad/src/agent_proxy.rs:446`); response bodies are streamed with no cap (`agent_proxy.rs:507`); `Range`/`Content-Range`/`Accept-Ranges` pass through; there is no request deadline on the proxy path. The cloudflared tunnel adds a per-request edge cap (~100 MB on free plans). aiohttp's default `client_max_size` is 1 MiB in `create_app`.
- **The composer already has the entry point**: a `Plus` button with `aria-label="add attachment"` and no handler (`apps/web/src/components/Chat/ChatComposer/index.tsx:264-278`).
- **`authedUrl()` is the sanctioned token-in-URL carrier** for media elements (`apps/web/src/lib/authed-url.ts`), because `<img>`/`<video>`/`<audio>` send no headers.
- **Nothing exists for files on the client**: no drag-drop for files, no download flow, no `FormData`/`Blob` usage, no file surface on the native bridge. An anchor `download` attribute is ignored cross-origin, so downloads must go through an authed fetch to a Blob.
- **Electron's renderer supports `<input type="file">`**, so file picking needs no native-bridge change. Desktop has no `will-download` handler, so a triggered download currently has no configured save behavior.
- **Two `Chat` instances can be mounted at once** (panel + fullscreen overlay in `DesktopPanelView.tsx`), so drop targets and draft state must be per-instance or deliberately shared.
- **The core HTTP client replays the same `init` after a 401 refresh** (`transport/http.ts:58-72`), so upload bodies must be re-readable. `Blob.slice()` bodies are.
- **`app-chat send`** moves at most 64 KB over the unix socket and lints text at 220 chars, so agent-sent attachments must be path references, never inline bytes.

## Decisions (locked)

Each fork below is resolved. Alternatives are recorded once, with the reason.

1. **The app-chat skill owns attachments.** Blobs live on the agent's disk under the skill's data dir. One owner for the whole chat plane, and the agent gets a plain file path it can `Read`. Rejected: a vestad-side blob store (splits chat ownership, and the agent would need a network hop to read its own attachment).
2. **Uploads are chunked and offset-addressed** (tus-style). The client PUTs sequential byte ranges at an explicit `offset`; the server appends only when the offset equals the staged size and otherwise answers with the staged size so the client resyncs. This clears vestad's 10 MiB buffered-body cap and the Cloudflare edge cap with margin, requires **zero vestad changes**, gives per-chunk progress and per-chunk retry, allows variable chunk sizes (the resilience section below adapts them to link quality), and scales to `MAX_ATTACHMENT_BYTES = 512 MiB`. Rejected: index-addressed chunks (a fixed index implies a fixed size, which forbids adaptive sizing), multipart (nothing in the stack parses it), streaming proxy bodies (a vestad rewrite that disables its bind-grace retry), WS binary upload (a second stateful channel for no gain).
3. **Attachments ride the existing `user`/`chat` events** as an optional `attachments` metadata array; `text` becomes the optional caption. History paging, socket echo, intent dedup, optimistic reconciliation, grouping, and trimming all keep working untouched. An attachment-only message has `text: ""`. Rejected: a new event type (the store's `_CONVERSATION_TYPES` filter would drop it from history).
4. **Upload precedes send.** The composer uploads on add; `POST /message` carries only finalized attachment ids. Validation of those ids happens before the notification write, and a validation failure is a 400 that persists nothing, so the at-most-once invariant is preserved. A send retry re-posts the same `intent_id` and the same ids; dedup covers it.
5. **Send is gated on upload completion (v1).** Chips show upload progress; the send button enables when every draft is finalized. By the time a caption is typed, small files are done. The WhatsApp pattern (send immediately, progress inside the bubble) is a deliberate later enhancement, because it adds partially-sent message states to the stream model.
6. **Viewing and downloading reuse the streamed proxy.** `GET .../attachments/{id}` serves the blob via aiohttp `web.FileResponse`, which gives correct `Content-Type`, `Content-Length`, and native `Range` support (video seeking) for free. Media elements load it through `authedUrl()`. Explicit downloads use the header-authed `apiFetch` to a Blob + object-URL anchor, which works identically in browser and Electron and never puts a token in a visible URL.
7. **`kind` is derived, not wired.** `attachmentKind(mime)` in `@vesta/core` maps a MIME type to `"image" | "video" | "audio" | "file"`. One owner; the wire carries only `mime`.
8. **The agent sends attachments by path**: `app-chat send --attach <path>` (repeatable). The daemon copies the file into the attachment store, mints the metadata, and appends a `chat` event. Bubble lint applies to the text only; `--attach` with empty text is valid.
9. **The notification carries file paths as scalars.** Extra notification fields render as XML attributes on the `<channel>` element (`agent/core/notification.py`), so the attachment list is one formatted string: name, mime, human size, and absolute container path per file. The agent reads the path directly; no new tool, no new skill verb for receiving.
10. **No MIME allowlist.** "Absolutely anything" is the requirement, the service is private behind vestad's gate, and the agent's container is the blast radius. The serve handler sets `X-Content-Type-Options: nosniff` and a sanitized `Content-Disposition` filename.
11. **Compatibility is additive both ways.** Old client + new agent: the unknown `attachments` field is ignored; the bubble shows the caption. New client + old agent: `POST .../attachments` 404s; the composer surfaces "this agent needs an update to receive files" and adds no chip. No `min_supported` bump.

## Wire contract

All routes live on the app-chat service (private, proxied at `/agents/{name}/app-chat/...`). All bodies are JSON except the chunk PUT (raw bytes).

```
POST /attachments
  { "name": string, "mime": string, "size": int,
    "width"?: int, "height"?: int, "duration_secs"?: number }
  -> 200 { "id": string }            # uuid4, server-minted
  -> 400 invalid body | 413 size > MAX_ATTACHMENT_BYTES

PUT /attachments/{id}/data?offset={n}        # raw bytes, <= MAX_CHUNK_BYTES
  -> 200 { "ok": true, "received": int }     # total bytes staged so far
  -> 404 unknown id
  -> 409 { "error": "offset mismatch", "received": int }
  # append happens only when offset == staged size; on 409 the client resyncs to
  # "received". A retried PUT whose original landed but whose response was lost
  # gets a 409 with received == offset + len, which the client reads as success.

GET /attachments/{id}/status
  -> 200 { "received": int, "size": int, "finalized": bool }
  -> 404 unknown id
  # the resume probe: after a connection gap the client asks where to continue
  # instead of guessing with a blind PUT

POST /attachments/{id}/complete
  {}
  -> 200 { "attachment": ChatAttachment }    # staged size must equal declared size
  -> 409 size mismatch | 404 unknown id
  # idempotent: complete on an already-finalized id returns 200 with the same
  # metadata, so a lost complete response is retried safely

GET /attachments/{id}                        # streams the blob
  -> 200 bytes; Accept-Ranges/Range supported (web.FileResponse)
     Content-Disposition per RFC 6266/5987 (ascii fallback + filename*), inline only for
     image/*, video/*, audio/*, application/pdf; every other declared mime serves as
     application/octet-stream attachment (client-declared text/html inline on the gateway
     origin would execute beside the app's tokens), plus Content-Security-Policy: sandbox
     and Cache-Control: private, max-age=3600 (an hour, so a removed blob's 410 can surface)
  ?download=1 -> Content-Disposition: attachment
  -> 404 unknown id
  -> 410 { "error": "attachment removed" }   # meta exists but the blob was cleaned up
                                             # (app-chat attachments rm); clients render
                                             # "no longer available", terminal, no retry

POST /message                                # extended
  { "text"?: string, "attachments"?: [string], "input_method"?, "intent_id"? }
  # at least one of text / attachments; every id must be finalized
  -> 400 { "error": "unknown attachment: <id>" } when not
```

The shared metadata shape, embedded verbatim in events:

```ts
export interface ChatAttachment {
  id: string
  name: string            // original filename, sanitized server-side
  mime: string
  size: number            // bytes
  width?: number          // images/videos, client-measured best effort
  height?: number
  duration_secs?: number  // audio/video, best effort
}
```

`StoredEvent` (Python, `store.py`) gains `attachments: list[...]`; the TS `VestaEvent` union's `user` and `chat` members gain `attachments?: ChatAttachment[]`. Constants: `MAX_CHUNK_BYTES = 8 MiB` (the server-enforced per-request cap, safely under vestad's 10 MiB), `MAX_ATTACHMENT_BYTES = 512 MiB`, `MAX_ATTACHMENTS_PER_MESSAGE = 10`; client-side sizing consts live in the resilience section.

### Disk layout (agent side)

```
~/.app-chat/attachments/<id>/.meta.json     # ChatAttachment JSON (name, mime, size, dims), atomic write
~/.app-chat/attachments/<id>/<sanitized-name>   # the blob (staging: .part + .session.json, renamed on complete)
```

The blob keeps a human filename so the path in the notification reads naturally for the agent. Control files are dot-prefixed and sanitization strips leading dots, so a user file named like a store record can never clobber one. `.meta.json` is what the serve handler reads; the id directory is the unit of GC. Stale sessions and finalized-but-never-referenced dirs older than 24 h are swept by a periodic daemon task (first pass shortly after start, never on the readiness path), with referenced ids taken from one structured scan of the events' `$.attachments` arrays; a referenced attachment lives as long as its event.

### Notification (agent intake)

`message_handler` extends the existing payload with one scalar field when attachments are present:

```
"attachments": "photo.jpg (image/jpeg, 2.1 MB) at /root/.app-chat/attachments/<id>/photo.jpg; report.pdf (application/pdf, 340 kB) at ..."
```

`message` stays the caption. An attachment-only message keeps the notification's `message` empty and the attribute renderer drops empty fields, so the `<channel>` body is the attachment line itself in that case (`format_for_display` picks the first of `message`/`text`/`content`; when all are empty the attributes still render). The agent needs no new mechanism: it reads the path with its normal tools and replies with `app-chat send --attach` when it wants to return a file.

## Resilience on poor and spotty connections

The upload path is the part of the app most exposed to link quality, so resilience is designed in, not retrofitted. Principles: the server holds the truth about staged bytes, every request is idempotent or resyncable, retries are unbounded while intent exists, and the client never burns retries against a link it knows is down.

### Adaptive chunk sizing

One fixed chunk size cannot serve both a fast LAN and a train wifi. The engine adapts, GCS-resumable-style:

- `INITIAL_CHUNK_BYTES = 1 MiB`, `MIN_CHUNK_BYTES = 256 KiB`, `MAX_CHUNK_UPLOAD_BYTES = 8 MiB` (client mirror of the server's `MAX_CHUNK_BYTES`).
- After a chunk completes in under `CHUNK_FAST_SECS = 2 s`, the next chunk doubles (capped at max). After a timeout or a network failure, the next attempt halves (floored at min).
- The loss window on a drop is at most one chunk, and on a degraded link it shrinks toward 256 KiB. On a good link the file moves at near-streaming efficiency.

### Stall detection and retry policy

- Every chunk PUT carries `AbortSignal.timeout(CHUNK_TIMEOUT_MS = 120_000)`; the core HTTP client passes `init` through, so no client change is needed. A stalled request aborts, halves the chunk, and retries. 256 KiB in 120 s holds down to roughly 2G speeds.
- Failures are classified once, in the engine: **terminal** (413, 404 on create meaning old agent, complete size mismatch) rejects the draft to its error state; **retryable** (network error, abort, 408/429/5xx) never rejects. Retryable failures back off exponentially from `RETRY_BASE_MS = 1 s` to `RETRY_MAX_MS = 30 s` and retry for as long as the draft exists. The user's X on the chip is the only cap.
- A 409 is not a failure: it is the resync signal. The client adopts the server's `received` and continues from there. This also confirms delivery when a PUT landed but its response was lost.

### Offline awareness (pause, do not fail)

- The engine takes an injected `Connectivity` dep (`isOnline(): boolean` plus an `onChange` subscription). While offline it skips retry timers entirely and parks; the first online edge resumes immediately with a `GET .../status` probe, then continues from `received`. The web adapter wraps `navigator.onLine` and the `online`/`offline` window events.
- Parked or backing-off drafts surface as a distinct chip state, **waiting** ("waiting for network"), separate from active uploading and from terminal error. Auto-resume needs no tap; tap-to-retry is reserved for terminal errors.
- Browser `onLine` overreports connectivity, so the online edge is an optimization only; the backoff loop remains the correctness mechanism.

### Resume semantics

- **Within the SPA session** (tab alive, network dropped for any duration): full resume from the server's staged offset via the status probe. Nothing re-uploads except the in-flight chunk.
- **Across a page reload**: not resumable on web, by design. The browser cannot re-read a picked `File` after reload without re-picking. Drafts die with the tab; the staged session on disk is swept by the daemon's 24 h GC. The offset protocol and status probe are exactly what mobile will use later for background/cross-launch resume, where file URIs persist.
- **Send intent**: already resilient by the existing contract (durable 200, `intent_id` dedup, tap-to-retry with the same id). On the socket's reconnect edge, a message stuck in `send_state: "retry"` whose bytes are all finalized is re-posted automatically once; dedup makes the double-send impossible.

### Receiving side on a bad link

- Image blocks that fail to load show the broken-fallback tile and auto-retry once on each reconnect edge (the `connected` flag the chat provider already exposes); the manual retry stays.
- Video and audio ride the browser's native Range recovery against the `FileResponse` endpoint; no client logic.
- Explicit downloads that fail mid-transfer surface the failed tile state with tap-to-retry; the blob refetches from zero. Range-based download resume is recorded as deferred.

## UI state map (web/desktop)

### 1. Attach entry points (three, all feeding the same draft list)

| Entry | Trigger | Behavior |
|---|---|---|
| Plus button | click on the existing `Plus` in `ChatComposer` | opens a Popover (`components/ui/popover`, `chrome-outline` surface) with two items: **Photos & videos** (`accept="image/*,video/*"`) and **File** (accept anything). Each item clicks a hidden `<input type="file" multiple>`. |
| Drag and drop | files dragged over a `Chat` instance | per-instance drop zone (see states below) |
| Paste | `paste` event on the textarea with `clipboardData.files` | files become drafts; text paste unaffected |

Popover states: closed; open (scrim held, existing behavior); option focused/hovered. On a disconnected agent the Plus button is disabled with the same toast the send path uses. When `POST /attachments` 404s (old agent), show the toast "This agent needs an update to receive files" and add no chip.

### 2. Drag-and-drop states (per Chat instance, dragenter/dragleave counter pattern)

| State | Visual |
|---|---|
| idle | nothing |
| drag-over, valid | full-chat absolute overlay: dimmed backdrop, inner dashed `chrome-outline` rounded panel, upload icon, "Drop to send to {agent}" |
| drag-over, non-file drag | no overlay (check `dataTransfer.types` includes `"Files"`) |
| drop | overlay dismisses; each file becomes a draft chip; oversize/overcount files rejected with one toast naming them |

The counter pattern (increment on `dragenter`, decrement on `dragleave`, reset on `drop`) is required because child elements fire spurious leave events. Only the visible instance overlays: the fullscreen `Chat` when the `/chat` route is active, the panel otherwise.

### 3. Draft chips row (inside the composer pill, above the textarea)

A new full-width flex row inside the existing `flex-wrap` pill (the pill's `motion.div layout` + `LAYOUT_TRANSITION` spring animates the expansion for free; the composer height measurement path already handles growth). Each chip:

| Chip state | Visual |
|---|---|
| uploading | 56 px thumbnail (images/videos, local object URL) or kind icon tile; middle-truncated name + human size; circular progress ring overlay (determinate, per-chunk granularity); X to cancel |
| waiting | ring pauses, muted wifi-off glyph, "waiting for network"; auto-resumes, no tap needed; X to cancel |
| uploaded | ring completes and fades; subtle check |
| error (terminal) | red ring + short reason ("too large", "agent needs update"); tap to retry, X to remove |
| removing | chip exits via layout animation |

Rules: max `MAX_ATTACHMENTS_PER_MESSAGE = 10` chips (further adds toast); files over `MAX_ATTACHMENT_BYTES` are rejected at pick time with a toast naming the file and its size, never uploaded; image dims measured client-side via `createImageBitmap` before session create; video dims/duration best-effort via a metadata probe, skipped on failure. When chips exist and the input is empty, the textarea placeholder becomes "Add a caption". Enter sends only when the send gate is open.

**Size is always visible.** Every chip shows its file's human size next to the name from the moment it appears (so the user knows what they are about to send before any byte moves), and with two or more chips a muted footer line under the row totals them: "3 files · 48 MB". `formatBytes` in `@vesta/core` is the one formatter behind chips, footer, bubbles, and the viewer, so the same file never reads as two different sizes.

### 4. Send states

| State | Behavior |
|---|---|
| gate closed | any chip uploading or errored: send button disabled (dimmed), Enter no-ops |
| gate open | text non-empty OR ≥1 uploaded chip: send enabled |
| sending | optimistic user bubble appears immediately (existing `beginSend` flow) with attachments rendered from local previews; chips clear; input clears |
| echo | `foldLiveEvent` matches by `intent_id` (unchanged); bubble adopts server ids; media flips from local object URL to `authedUrl` source (imperceptible; object URLs revoked) |
| retry / failed | the existing "not sent · tap to retry" affordance, unchanged; retry re-posts the same intent and ids |

Local previews live in a per-Chat `Map<attachmentId, objectUrl>` at the view layer, never in the core model, so the shared stream model stays pure wire data.

### 5. Message bubbles (user and agent render identically, sided by the existing variants)

One `AttachmentContent` block per attachment, stacked vertically inside the bubble, caption last as the normal markdown body. Bubble keeps its existing radius/tail/timestamp system; media blocks get edge-to-edge rounded corners inside the bubble padding.

| Kind | Render | States |
|---|---|---|
| image | `<img>` via `authedUrl`, pre-sized with CSS `aspect-ratio` from `width`/`height` (prevents scroll jitter; the chat ResizeObserver otherwise fires on load), max ~320×400 | skeleton shimmer while loading; loaded; broken-image fallback tile with retry; removed (410) shows the "no longer available" tile |
| video | `<video controls preload="metadata">` via `authedUrl`, pre-sized; Range gives seeking | poster-less first frame; native controls |
| audio | compact `<audio controls>` | native |
| file (everything else) | horizontal tile: kind icon, name (middle-truncated), size, download icon | idle; fetching (determinate ring: the proxy strips `Content-Length`, so progress reads the response stream against the metadata `size`); saved; failed (toast + retry) |
| removed (any kind) | muted tile: name, size, "no longer available" | terminal: a 410 from the serve route; no retry, no auto-reload |

Size appears on every rendered form: the file tile inline, the viewer caption (name + dimensions + size), video/audio via a small size badge in the corner until playback starts, and the download toast on completion. The metadata `size` is wire truth, so every display works even while bytes are still loading or after they are removed.

Clicking an image, or a video's corner expand button, opens the in-chat viewer below. Audio plays inline; file tiles download on click. `useAuthedSrc(path)` (small web hook wrapping the async `authedUrl`) feeds every media element and rebuilds per mount, so the token is always fresh.

### 5b. In-chat attachment viewer

A media viewer that goes "full screen" **within the Chat container**, never over the whole window: an absolute inset overlay on the Chat card with a local scrim (`bg-background/80`), so the rest of the app (roster, navbar, the other pane) stays visible and interactive-looking behind it. Each mounted `Chat` instance owns its own viewer state; opening one in the panel does not touch the fullscreen chat.

| Aspect | Design |
|---|---|
| containment | absolute overlay inside the Chat card (the card is already `relative overflow-hidden`); deliberately **not** a body portal. Implementation note: Radix `Dialog` primitives composed without the `Portal` give the focus trap, Esc handling, and `role="dialog"`/`aria-modal` for free while staying inside the container |
| framing | media centered, capped at ~88% of the container's width and height, `object-contain`, rounded corners, shadow; never edge-to-edge, the scrim always shows around it |
| image | native `<img>` rendering; **wheel zooms anchored at the cursor** (a trackpad pinch arrives as ctrl+wheel, so pinch works natively); double-click toggles fit ↔ 2×; drag pans while zoomed; zoom clamped fit–4×; state resets on close. Pure clamp/anchor math lives in a tested model (`viewer-zoom.ts`), pointer events only, no zoom library |
| video | fresh `<video controls autoplay>` with the browser's native controls (play, seek via the Range-capable endpoint, volume, PiP where the browser offers it); the inline bubble's expand button hands over `currentTime` best-effort so playback continues where it was |
| audio / file | no viewer: audio's native inline player is already the whole experience, and a file opens nothing (click downloads) |
| chrome | X top-right, download action, caption bottom (name, size, dimensions for images); click on the scrim or Esc closes; focus returns to the opening bubble |
| motion | scale-and-fade in from ~0.96 with `stepTransition`; honored by the app-wide `MotionConfig reducedMotion="user"` |

Deferred (recorded): arrow-key gallery navigation across all media in the conversation, and a swipe-down-to-dismiss gesture (mobile-first concern).

### 6. Downloads

`downloadAttachment` (web lib): header-authed `apiFetch` of `?download=1` → Blob → `URL.createObjectURL` → temporary anchor click → revoke. Browser: normal download UX. Desktop: a new `session.on("will-download")` handler in `apps/desktop/src/window.ts` routes the item to the OS save dialog (defaulting to Downloads). This is the only desktop-side change; picking and dropping work in the renderer as-is, and the native bridge (`window.vestaNative`) does not change at all.

### 7. History and reconnect

Nothing new. Attachment metadata rides the events that history paging and the socket echo already move; a reconnect refetches the tail by id and the bubbles re-render from metadata. Media elements re-fetch bytes on demand (browser cache applies; the serve handler sends no `Cache-Control`, letting heuristic caching work since blobs are immutable per id; an explicit `Cache-Control: private, max-age=31536000, immutable` is a cheap add and is included).

## Module map

### @vesta/core (`apps/core/src/`)

| File | Contents |
|---|---|
| `attachments/attachment-model.ts` (new) | `ChatAttachment`, `AttachmentKind`, `attachmentKind(mime)`, `formatBytes(size)`, the sizing/retry consts (`MAX_CHUNK_UPLOAD_BYTES`, `INITIAL_CHUNK_BYTES`, `MIN_CHUNK_BYTES`, `CHUNK_TIMEOUT_MS`, `CHUNK_FAST_SECS`, `RETRY_BASE_MS`, `RETRY_MAX_MS`, `MAX_ATTACHMENT_BYTES`, `MAX_ATTACHMENTS_PER_MESSAGE`), `appChatAttachmentPath(agent, id, download?)` |
| `attachments/upload.ts` (new) | `uploadAttachment(http, agent, file: UploadSource, meta, deps, callbacks): UploadHandle` — the offset-addressed state machine: create → sequential offset PUTs (`Blob.slice`, re-readable on 401 replay, `AbortSignal.timeout` per chunk) → complete. Adaptive chunk sizing (double on fast, halve on failure), unbounded classified retries with backoff, 409 resync to the server's `received`, status-probe resume on reconnect, offline parking via the injected `Connectivity` dep, `onProgress(sentBytes, totalBytes)`, `onStateChange("uploading" \| "waiting")`, `abort()`. Pure logic over the injected `HttpClient`; fully unit-testable with fakes and injected timers |
| `attachments/attachment-draft.ts` (new) | pure draft reducer shared with mobile later: `DraftAttachment` (`status: "uploading" | "waiting" | "uploaded" | "error"`, `progress`, `attachment?`, `error?`), `addDraft`, `setDraftProgress`, `setDraftWaiting`, `finalizeDraft`, `failDraft`, `removeDraft`, `draftsReady(drafts)`, `uploadedIds(drafts)` |
| `protocol/events.ts` (modify) | `user` and `chat` members gain `attachments?: ChatAttachment[]` |
| `intents/send-message.ts` (modify) | `SendMessageBody` becomes `{ text?: string; attachments?: string[]; input_method?: InputMethod }`; behavior otherwise unchanged |
| `chat/chat-stream-model.ts` (modify) | `beginSend` gains an optional `attachments: ChatAttachment[]` param carried onto the optimistic bubble; echo reconciliation unchanged (matches on `intent_id`) |

The duplicate `ChatMessage` in `apps/web/src/lib/types.ts` picks up the same optional field.

### apps/web

| File | Contents |
|---|---|
| `components/Chat/ChatComposer/AttachMenu.tsx` (new) | popover + hidden file inputs, wired to the existing Plus button |
| `components/Chat/AttachmentChips/index.tsx` (new) | the draft chips row |
| `components/Chat/DropZone/index.tsx` (new) | per-instance overlay + counter-pattern handlers on the Chat root |
| `components/Chat/ChatBubble/AttachmentContent/index.tsx` (new) | the four typed blocks |
| `components/Chat/AttachmentViewer/index.tsx` (new) | the in-chat viewer overlay (portal-less Dialog composition, image zoom/pan, video handoff) + `viewer-zoom.ts`, the pure zoom/pan clamp model with tests |
| `components/Chat/use-attachment-drafts.ts` (new) | per-Chat hook: draft reducer + upload engine + local-preview object-URL map + old-agent 404 handling |
| `hooks/use-authed-src.ts` (new) | async `authedUrl` → `src` string for media elements |
| `lib/download.ts` (new) | `downloadAttachment(agent, attachment)` blob-anchor flow |
| `Chat/index.tsx`, `ChatComposer/index.tsx` (modify) | lift drafts next to `input`; send gating; paste handler; pass attachments into `send` |
| `providers/AgentSocketProvider/use-agent-socket.ts` (modify) | `send(text, inputMethod, attachments?)` threads ids + metadata through `sendMessage`/`beginSend`; `retry` carries them too; on the reconnect edge, re-posts a `send_state: "retry"` message once (dedup makes it safe) |
| `lib/native/…` | unchanged; the web `Connectivity` adapter (`navigator.onLine` + window events) lives beside the upload wiring in `use-attachment-drafts.ts` |

### apps/desktop

| File | Contents |
|---|---|
| `src/window.ts` (modify) | `session.on("will-download")` → OS save dialog, default Downloads dir |

No preload/native-bridge change, so `preload-parity.test.ts` is untouched.

### agent side (app-chat skill)

| File | Contents |
|---|---|
| `cli/src/app_chat_cli/attachments.py` (new) | store: session create, offset-checked append, staged-size read, idempotent finalize, GC sweep, meta read, path/filename sanitization |
| `cli/src/app_chat_cli/service.py` (modify) | the five attachment routes (create, data PUT, status, complete, serve); `client_max_size` raised to `MAX_CHUNK_BYTES` + slack; `/message` gains id validation + metadata embedding + notification attachment line |
| `cli/src/app_chat_cli/daemon.py` (modify) | unix-socket `send` accepts `attach` paths; ingest-by-copy into the store |
| `cli/src/app_chat_cli/commands.py` + `cli.py` (modify) | `app-chat send --attach <path>` (repeatable); `app-chat attachments list|rm` (direct disk readers, largest-first sizing, blob-only removal) |
| `SKILL.md` (modify) | the Attachments section and description update below |

## Agent side

**Zero `agent/core/` changes.** This is a designed property, verified against the current tree:

- `notification.py` renders every non-content notification field as an XML attribute on the `<channel>` element, so the new `attachments` scalar renders with no renderer change: `<app-chat type="message" attachments="photo.jpg (image/jpeg, 2.1 MB) at /root/.app-chat/attachments/<id>/photo.jpg">look at this</app-chat>`.
- `notification_interrupt_policy.py` is untouched: an attachment message is a `source=app-chat type=message` notification like any other, so it interrupts by default and user rules apply to it unchanged.
- `events.py`, `tools.py`, `loops.py`, prompts: untouched. The skill owns the whole feature.

### How the agent consumes an attachment

The notification hands the agent an absolute path inside its own container. From there everything is existing capability, and the SKILL.md states it so the agent does not go hunting for a special tool:

- Images and PDFs: the `Read` tool presents them visually (pages for PDFs).
- Text, code, spreadsheets, archives: `Read` and ordinary shell tools.
- Audio and video: shell tools (`ffprobe`/`ffmpeg` ship in the box); transcription rides whatever the agent's voice tooling offers.
- The blob is durable: GC never touches a referenced attachment, and `app-chat history` returns the metadata, so the agent can revisit a file the user sent weeks ago. Every surface the agent reads carries the byte size: the notification line (human size), `meta.json` (`size` in bytes), history events, and the CLI below.
- Disk management goes through the CLI, never `rm` on the directory: a raw delete leaves the app with an unexplained broken bubble, while `app-chat attachments rm` removes the blob and keeps `meta.json`, which is exactly what makes the serve route answer 410 and the app render a clean "no longer available" tile.

### Attachment CLI (agent-facing disk management)

Two subcommands under `app-chat attachments`, both direct disk readers (store db + attachments dir; sqlite WAL allows the concurrent read, and a POSIX unlink under an in-flight `FileResponse` is safe), so they work whether or not the daemon is up:

```
app-chat attachments list [--sort size|date] [--limit N] [--min-size BYTES]
  -> single-line JSON on stdout:
     { "attachments": [ { "id", "name", "mime", "size", "ts", "direction": "received"|"sent",
                          "removed": bool } ... ],
       "count": int, "total_bytes": int }
  # sorted largest-first by default; ts and direction joined from the event that references it

app-chat attachments rm <id> [<id> ...]
  -> { "removed": ["<id>", ...], "freed_bytes": int }
  # deletes the blob, keeps meta.json; idempotent (an already-removed id is a no-op);
  # unknown id fails on stderr with non-zero exit
```

The pair covers "how much space, what is biggest, clean it up" with two verbs and no daemon coupling. Output follows the skill output contract: single-line JSON envelope, errors on stderr, non-zero exit on failure.

### How the agent sends one

`app-chat send --attach <path>` (repeatable), with or without `--message`. The daemon copies the file into the store (`ingest_file`), so the agent may attach a temp file and delete its copy immediately after. Size above `MAX_ATTACHMENT_BYTES` fails loudly on stderr. The bubble lint applies to the message text only; `--attach` with no text is valid. Pacing on the client handles an attachment-only bubble (minimum typing delay).

### SKILL.md additions (draft copy, final wording at implementation under vesta-prompt-guide review)

Description gains the sending trigger, staying discovery-only: `The user's chat screen in the Vesta app (web, desktop, mobile). Reply to source=app-chat notifications via app-chat send; send files with --attach. Requires daemon.`

New body section, after How it works:

> ## Attachments
>
> Files the user sends from the app arrive on the message notification: the `attachments` attribute lists each file's name, type, size, and an absolute path. Open the path directly: `Read` shows images and PDFs, shell tools handle everything else. The files persist under `~/.app-chat/attachments/` (each in an id directory with a `meta.json` carrying name, type, and exact byte size) and `app-chat history` returns their metadata, so you can come back to one later.
>
> Send a file with `--attach` (repeat it for several), with or without a message:
>
> ```bash
> app-chat send --attach ~/out/budget-2026.pdf --message 'here it is!'
> app-chat send --attach chart.png
> ```
>
> The daemon copies the file into its own store, so a temp file can be removed right after sending. The app renders by type: images and videos inline, audio as a player, anything else as a download tile. Limit 512 MB per file. The short-bubble lint applies to the message text only. When the user asks for a real document, a chart, or anything they will keep, attach the file instead of pasting its contents as text.
>
> Manage the disk they use with the CLI, never by deleting files under `~/.app-chat/attachments/` yourself (a raw delete leaves the user a broken bubble; `rm` here leaves a clean "no longer available" tile):
>
> ```bash
> app-chat attachments list              # largest first, with count and total_bytes
> app-chat attachments list --sort date --limit 20
> app-chat attachments rm <id> [<id>...] # frees the bytes, keeps the chat history intact
> ```

The existing longform note gains that same last preference (attach real artifacts rather than sending walls of text), phrased once, in one place.

### Fleet convergence

No prompt migration: the change is additive and old history needs no conversion. The skill code reaches every box through upstream sync; the CLI is a `uv tool install --editable` install and the dependency set is unchanged (aiohttp only), so new code applies at the next daemon start with no reinstall. A merged sync restarts the agent, the restart kills the daemon with the container, and the agent's restart routine starts it again on the new code, so the feature turns on fleet-wide at the first post-update boot. Until a given agent updates, a new client's `POST /attachments` 404s and the composer shows the "agent needs an update" state; old clients against a new agent ignore the unknown field and show captions only.

`agent/tests/test_service_exposure.py` keeps pinning app-chat as private, and `test_daemon_contract.py` is untouched (the daemon verbs do not change).

## Invariants preserved

- Intake stays at-most-once: attachment-id validation is a pure read before the notification write; nothing fallible was added after it.
- The chat plane stays off `/sync`; no fixture regen, no `min_supported` bump; the "ignores unknown" tests are untouched.
- vestad is untouched in v1 (the desktop `will-download` handler is app-side).
- One owner per decision: chunk size, size caps, and kind-derivation live once in `@vesta/core` (client) and once as Python consts in `attachments.py` (server); the wire contract in this spec is the seam between them, locked by tests on both sides.
- The composer's voice path (`registerChatCallbacks`) is unaffected: voice sends text-only.

## Deliberately deferred (recorded so they are not re-litigated)

- **Bubble-embedded upload progress** (send-before-upload, WhatsApp exact): needs partial-message states in the stream model. The chunked engine and the bubble components are the foundation it will build on.
- **Server-side thumbnails / image resizing**: needs an image dependency in the skill CLI. v1 loads full images with `aspect-ratio` pre-sizing; a client-generated thumbnail uploaded alongside is the likely v2 shape.
- **Mobile**: expo-image-picker/document-picker feeding the same draft reducer and upload engine; RN download/share-sheet flow; scoped as its own plan.
- **Recall/FTS over attachment names**: the FTS triggers index `$.text` only; indexing `$.attachments[*].name` is a v3+ events-db-style additive migration in the skill store.
- **Camera capture** entry in the popover (mobile-first concern).
- **Streaming save on desktop** for multi-GB files (bridge `saveFile` capability); v1 buffers the Blob in renderer memory, acceptable to 512 MiB.
- **Range-resumable downloads**: the serve endpoint already honors Range; a chunked download engine mirroring the upload engine can resume a failed download instead of refetching. v1 refetches.
- **Cross-reload upload resume on web** via the File System Access API's persistable handles; the offset protocol and status probe already support it, only the file re-read is missing.
