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
2. **Uploads are chunked.** The client slices the file into `ATTACHMENT_CHUNK_BYTES = 4 MiB` parts and PUTs them sequentially. This clears vestad's 10 MiB buffered-body cap and the Cloudflare edge cap with margin, requires **zero vestad changes**, gives per-chunk progress and per-chunk retry, and scales to `MAX_ATTACHMENT_BYTES = 512 MiB`. Rejected: multipart (nothing in the stack parses it), streaming proxy bodies (a vestad rewrite that disables its bind-grace retry), WS binary upload (a second stateful channel for no gain).
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

PUT /attachments/{id}/chunks/{index}         # raw bytes, <= ATTACHMENT_CHUNK_BYTES
  -> 200 { "ok": true, "received": int }     # total bytes staged so far
  -> 404 unknown id | 409 { "error": "wrong chunk index", "expected": int }
  # chunks are sequential; re-PUTting the last-accepted index is an idempotent no-op

POST /attachments/{id}/complete
  {}
  -> 200 { "attachment": ChatAttachment }    # staged size must equal declared size
  -> 409 size mismatch | 404 unknown id

GET /attachments/{id}                        # streams the blob
  -> 200 bytes, Content-Type: <mime>, Content-Disposition: inline; filename="<sanitized>"
     Accept-Ranges/Range supported (web.FileResponse)
  ?download=1 -> Content-Disposition: attachment
  -> 404 unknown id

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

`StoredEvent` (Python, `store.py`) gains `attachments: list[...]`; the TS `VestaEvent` union's `user` and `chat` members gain `attachments?: ChatAttachment[]`. Constants: `ATTACHMENT_CHUNK_BYTES = 4 MiB`, `MAX_ATTACHMENT_BYTES = 512 MiB`, `MAX_ATTACHMENTS_PER_MESSAGE = 10`.

### Disk layout (agent side)

```
~/.app-chat/attachments/<id>/meta.json      # ChatAttachment JSON (name, mime, size, dims)
~/.app-chat/attachments/<id>/<sanitized-name>   # the blob (staging: .part, renamed on complete)
```

The blob keeps a human filename so the path in the notification reads naturally for the agent. `meta.json` is what the serve handler reads; the id directory is the unit of GC. Stale sessions (a `.part` older than 24 h) and finalized-but-never-referenced dirs older than 24 h are swept at daemon start; a referenced attachment lives as long as its event.

### Notification (agent intake)

`message_handler` extends the existing payload with one scalar field when attachments are present:

```
"attachments": "photo.jpg (image/jpeg, 2.1 MB) at /root/.app-chat/attachments/<id>/photo.jpg; report.pdf (application/pdf, 340 kB) at ..."
```

`message` stays the caption. An attachment-only message keeps the notification's `message` empty and the attribute renderer drops empty fields, so the `<channel>` body is the attachment line itself in that case (`format_for_display` picks the first of `message`/`text`/`content`; when all are empty the attributes still render). The agent needs no new mechanism: it reads the path with its normal tools and replies with `app-chat send --attach` when it wants to return a file.

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
| uploaded | ring completes and fades; subtle check |
| error | red ring + short reason ("too large", "upload failed"); tap to retry, X to remove |
| removing | chip exits via layout animation |

Rules: max `MAX_ATTACHMENTS_PER_MESSAGE = 10` chips (further adds toast); files over `MAX_ATTACHMENT_BYTES` are rejected at pick time with a toast, never uploaded; image dims measured client-side via `createImageBitmap` before session create; video dims/duration best-effort via a metadata probe, skipped on failure. When chips exist and the input is empty, the textarea placeholder becomes "Add a caption". Enter sends only when the send gate is open.

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
| image | `<img>` via `authedUrl`, pre-sized with CSS `aspect-ratio` from `width`/`height` (prevents scroll jitter; the chat ResizeObserver otherwise fires on load), max ~320×400 | skeleton shimmer while loading; loaded; broken-image fallback tile with retry |
| video | `<video controls preload="metadata">` via `authedUrl`, pre-sized; Range gives seeking | poster-less first frame; native controls |
| audio | compact `<audio controls>` | native |
| file (everything else) | horizontal tile: kind icon, name (middle-truncated), size, download icon | idle; fetching (spinner replaces icon, determinate when Content-Length survives); saved; failed (toast + retry) |

Image click opens a lightbox (existing `Dialog`): full image, filename, size, download action, Esc/backdrop closes. Video/audio play inline; file tiles download on click. `useAuthedSrc(path)` (small web hook wrapping the async `authedUrl`) feeds every media element and rebuilds per mount, so the token is always fresh.

### 6. Downloads

`downloadAttachment` (web lib): header-authed `apiFetch` of `?download=1` → Blob → `URL.createObjectURL` → temporary anchor click → revoke. Browser: normal download UX. Desktop: a new `session.on("will-download")` handler in `apps/desktop/src/window.ts` routes the item to the OS save dialog (defaulting to Downloads). This is the only desktop-side change; picking and dropping work in the renderer as-is, and the native bridge (`window.vestaNative`) does not change at all.

### 7. History and reconnect

Nothing new. Attachment metadata rides the events that history paging and the socket echo already move; a reconnect refetches the tail by id and the bubbles re-render from metadata. Media elements re-fetch bytes on demand (browser cache applies; the serve handler sends no `Cache-Control`, letting heuristic caching work since blobs are immutable per id; an explicit `Cache-Control: private, max-age=31536000, immutable` is a cheap add and is included).

## Module map

### @vesta/core (`apps/core/src/`)

| File | Contents |
|---|---|
| `attachments/attachment-model.ts` (new) | `ChatAttachment`, `AttachmentKind`, `attachmentKind(mime)`, `formatBytes(size)`, `ATTACHMENT_CHUNK_BYTES`, `MAX_ATTACHMENT_BYTES`, `MAX_ATTACHMENTS_PER_MESSAGE`, `appChatAttachmentPath(agent, id, download?)` |
| `attachments/upload.ts` (new) | `uploadAttachment(http, agent, file: UploadSource, meta, callbacks): UploadHandle` — the chunked state machine: create → sequential chunk PUTs (`Blob.slice`, re-readable on 401 replay) → complete. `onProgress(sentBytes, totalBytes)`, `abort()`, capped per-chunk retry with backoff, resumes from the server's `expected` index on a 409. Pure logic over the injected `HttpClient`; fully unit-testable with a fake |
| `attachments/attachment-draft.ts` (new) | pure draft reducer shared with mobile later: `DraftAttachment` (`status: "uploading" | "uploaded" | "error"`, `progress`, `attachment?`, `error?`), `addDraft`, `setDraftProgress`, `finalizeDraft`, `failDraft`, `removeDraft`, `draftsReady(drafts)`, `uploadedIds(drafts)` |
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
| `components/Chat/ChatBubble/AttachmentContent/index.tsx` (new) | the four typed blocks + lightbox |
| `components/Chat/use-attachment-drafts.ts` (new) | per-Chat hook: draft reducer + upload engine + local-preview object-URL map + old-agent 404 handling |
| `hooks/use-authed-src.ts` (new) | async `authedUrl` → `src` string for media elements |
| `lib/download.ts` (new) | `downloadAttachment(agent, attachment)` blob-anchor flow |
| `Chat/index.tsx`, `ChatComposer/index.tsx` (modify) | lift drafts next to `input`; send gating; paste handler; pass attachments into `send` |
| `providers/AgentSocketProvider/use-agent-socket.ts` (modify) | `send(text, inputMethod, attachments?)` threads ids + metadata through `sendMessage`/`beginSend`; `retry` carries them too |

### apps/desktop

| File | Contents |
|---|---|
| `src/window.ts` (modify) | `session.on("will-download")` → OS save dialog, default Downloads dir |

No preload/native-bridge change, so `preload-parity.test.ts` is untouched.

### agent side (app-chat skill; scoped now, built later)

| File | Contents |
|---|---|
| `cli/src/app_chat_cli/attachments.py` (new) | store: session create, sequential chunk staging, finalize, GC sweep, meta read, path/filename sanitization |
| `cli/src/app_chat_cli/service.py` (modify) | the four attachment routes; `client_max_size` raised to chunk size + slack; `/message` gains id validation + metadata embedding + notification attachment line |
| `cli/src/app_chat_cli/daemon.py` (modify) | unix-socket `send` accepts `attach` paths; ingest-by-copy into the store |
| `cli/src/app_chat_cli/commands.py` + `cli.py` (modify) | `app-chat send --attach <path>` (repeatable) |
| `SKILL.md` (modify) | document receiving (path in notification) and sending (`--attach`); written under the vesta-prompt-guide rules |

No prompt migration is needed: the change is additive, ships with upstream sync, and old history needs no conversion.

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
