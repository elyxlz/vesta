# App-chat attachments implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Scope note:** this is a scoping-mode plan, written before any code. Contracts, types, signatures, states, and test behaviors are locked here; implementation bodies are written at execution time, test-first. Each phase is one PR. Re-read the spec before each phase.

**Goal:** users send any file to their agent through app chat and receive typed attachment bubbles back, on web and desktop, over a chunked upload contract that mobile reuses later.

**Architecture:** the app-chat skill stores blobs on the agent's disk and extends its service with a chunked upload + streamed download contract; `@vesta/core` gains the shared upload engine, draft reducer, and wire types; the web app builds the composer UX (popover, drag-drop, paste, chips) and typed bubbles; desktop adds only a `will-download` handler. vestad is untouched.

**Tech stack:** aiohttp + sqlite (skill), TypeScript + vitest (`@vesta/core`), React + Tailwind + motion + vendored shadcn primitives (web), Electron main process (desktop).

**Spec:** `docs/superpowers/specs/2026-08-30-app-chat-attachments-design.md`

## Global constraints

- `ATTACHMENT_CHUNK_BYTES = 4 * 1024 * 1024`; `MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024`; `MAX_ATTACHMENTS_PER_MESSAGE = 10`. Same values as named consts in `@vesta/core` (`attachment-model.ts`) and Python (`attachments.py`); the wire contract in the spec is the seam.
- All attachment routes ride the existing private app-chat service; no new service, no vestad change, no `/sync` change, no `min_supported` bump, no fixture regen.
- The intake at-most-once invariant in `service.py::message_handler` must survive: no fallible step may be added after the notification write.
- Skill work follows `agent/` prompt rules (invoke vesta-prompt-guide before editing `SKILL.md`); no dashes as prose separators; no inline lint escapes; each PR runs its `./check.sh` subcommands before push; never push to master; do not merge without approval.
- Chat-plane compat: `attachments` is optional on `user`/`chat` events; old clients must keep parsing (no changes to `parse.ts` or the ignore-unknown tests).

---

## Phase 1 (PR 1): app-chat attachment store + endpoints + `send --attach`

Standalone and fully testable with pytest; clients come later. Suite: `agent/skills/app-chat/cli/tests/`, run via `uv run --project agent/skills/app-chat/cli pytest agent/skills/app-chat/cli/tests/` (picked up by `./check.sh app-chat`).

### Task 1.1: attachment store module

**Files:**
- Create: `agent/skills/app-chat/cli/src/app_chat_cli/attachments.py`
- Test: `agent/skills/app-chat/cli/tests/test_attachments.py`

**Interfaces (produces):**
```python
ATTACHMENT_CHUNK_BYTES = 4 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10
STALE_SESSION_MAX_AGE_SECS = 24 * 3600

class AttachmentMeta(tp.TypedDict, total=False):
    id: str; name: str; mime: str; size: int
    width: int; height: int; duration_secs: float

def create_session(root: Path, name: str, mime: str, size: int, extra: AttachmentMeta) -> str  # returns id; raises SizeError
def append_chunk(root: Path, attachment_id: str, index: int, data: bytes) -> int  # returns staged bytes; raises WrongChunk(expected)/UnknownAttachment
def finalize(root: Path, attachment_id: str) -> AttachmentMeta  # renames .part, writes meta.json final; raises SizeMismatch
def read_meta(root: Path, attachment_id: str) -> AttachmentMeta | None  # None until finalized
def blob_path(root: Path, attachment_id: str) -> Path
def ingest_file(root: Path, source: Path, mime: str | None) -> AttachmentMeta  # copy-in for agent sends; mime guessed via mimetypes when None
def sweep(root: Path, now: float, referenced: cabc.Callable[[str], bool]) -> list[str]  # removes stale .part sessions and unreferenced finalized dirs older than the max age
def sanitize_filename(name: str) -> str  # strips path separators/control chars, caps length, never empty
```

Disk layout per spec: `<root>/<id>/meta.json` + `<root>/<id>/<sanitized-name>` (staging suffix `.part`). Chunk index is enforced sequential; re-PUT of the last accepted index is an idempotent no-op (returns current staged size).

- [ ] Write failing tests: session create rejects size over cap; sequential chunks accumulate; wrong index raises with `expected`; duplicate last chunk is a no-op; finalize rejects size mismatch and renames the blob; `read_meta` is `None` pre-finalize; `ingest_file` copies and guesses mime; `sanitize_filename` strips `../` and slashes; `sweep` removes a stale `.part` and an old unreferenced dir but keeps a referenced one
- [ ] Implement `attachments.py` minimally to pass
- [ ] Run the suite; commit `feat(app-chat): attachment blob store`

### Task 1.2: HTTP routes

**Files:**
- Modify: `agent/skills/app-chat/cli/src/app_chat_cli/service.py`
- Test: `agent/skills/app-chat/cli/tests/test_service.py` (extend)

**Interfaces (produces):** the four routes exactly as the spec's wire contract: `POST /attachments`, `PUT /attachments/{id}/chunks/{index}`, `POST /attachments/{id}/complete`, `GET /attachments/{id}` (via `web.FileResponse` with `Content-Disposition` from `sanitize_filename`, `?download=1` toggling `attachment`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, max-age=31536000, immutable`). `web.Application(client_max_size=ATTACHMENT_CHUNK_BYTES + 1024 * 1024)`. `ServiceState` gains `attachments_root: Path` (default `data_dir / "attachments"`); daemon start runs `sweep` with a referenced-check that scans `events.data` for the candidate id.

- [ ] Write failing aiohttp test-client tests: full happy path (create → 2 chunks → complete → GET bytes round-trip with correct headers); 413 on oversize declare; 409 on out-of-order chunk carries `expected`; 409 on complete with missing bytes; 404 on unknown id; Range request returns 206; `?download=1` flips disposition
- [ ] Implement routes; run; commit `feat(app-chat): chunked attachment upload and download routes`

### Task 1.3: message intake with attachments

**Files:**
- Modify: `service.py::message_handler`, `store.py` (`StoredEvent` gains `attachments`)
- Test: `test_service.py` (extend)

Validation order inside the handler, preserving at-most-once: parse body → require `text` or `attachments` → resolve every id via `read_meta` (400 `unknown attachment: <id>` on any miss, nothing persisted) → build the event with embedded `AttachmentMeta` list → `_write_notification` (now also receives the metadata and renders the spec's `attachments` scalar line, `_human_size` helper) → append → emit → remember intent.

- [ ] Write failing tests: attachment message persists metadata into the stored event and the ws echo; attachment-only message (no text) accepted; unknown id 400s and writes no notification and persists nothing; notification JSON carries the formatted `attachments` line with absolute paths; intent_id dedup still returns `deduped` without touching the store
- [ ] Implement; run; commit `feat(app-chat): attachments on message intake`

### Task 1.4: `app-chat send --attach`

**Files:**
- Modify: `cli.py` (arg), `commands.py` (`cmd_send`), `daemon.py` (`_handle_socket_conn` `send` command gains `attach: list[str]`; ingest via `ingest_file`; `chat` event carries the metadata; bubble lint applies to text only and empty text with attachments passes)
- Test: `tests/test_daemon.py` (extend)

- [ ] Write failing tests: `send` with one attach path ingests the file, appends a `chat` event with `attachments`, and the reply carries the event id; missing source path errors on stderr with non-zero exit; empty message + attach passes lint; user-notification preview falls back to the attachment name when text is empty
- [ ] Implement; run; commit `feat(app-chat): send --attach`

### Task 1.5: SKILL.md + checks

- Modify: `agent/skills/app-chat/SKILL.md` (receiving: the notification's path line; sending: `--attach`; written after invoking vesta-prompt-guide, stating current mechanism only, no changelog)
- [ ] Run `./check.sh app-chat` and `./check.sh guards`; open PR 1 (`feat(app-chat): user attachments over chunked upload`)

---

## Phase 2 (PR 2): @vesta/core attachment modules

Suite: `./check.sh app-core`. Contract fixed by Phase 1; this PR is client logic only, no UI.

### Task 2.1: model + paths

**Files:**
- Create: `apps/core/src/attachments/attachment-model.ts`, `attachment-model.test.ts`

**Interfaces (produces):**
```ts
export interface ChatAttachment { id: string; name: string; mime: string; size: number; width?: number; height?: number; duration_secs?: number }
export type AttachmentKind = "image" | "video" | "audio" | "file"
export function attachmentKind(mime: string): AttachmentKind
export function formatBytes(size: number): string          // "2.1 MB", "340 kB"
export function appChatAttachmentPath(agent: string, id: string, download?: boolean): string
export const ATTACHMENT_CHUNK_BYTES: number
export const MAX_ATTACHMENT_BYTES: number
export const MAX_ATTACHMENTS_PER_MESSAGE: number
```

- [ ] Failing tests for kind mapping (image/*, video/*, audio/*, everything else → file), byte formatting boundaries, path encoding (`encodeURIComponent` on agent) → implement → commit

### Task 2.2: chunked upload engine

**Files:**
- Create: `apps/core/src/attachments/upload.ts`, `upload.test.ts`

**Interfaces (produces):**
```ts
export interface UploadMeta { name: string; mime: string; size: number; width?: number; height?: number; duration_secs?: number }
export interface UploadCallbacks { onProgress: (sentBytes: number, totalBytes: number) => void }
export type UploadErrorReason = "too_large" | "unsupported_agent" | "failed"
export interface UploadHandle { result: Promise<ChatAttachment>; abort: () => void }  // result rejects with UploadError{reason}
export function uploadAttachment(http: HttpClient, agent: string, blob: Blob, meta: UploadMeta, callbacks: UploadCallbacks): UploadHandle
```

Behavior locked by tests: sequential `Blob.slice` chunk PUTs; progress after each accepted chunk; a 409 resyncs to the server's `expected` index; per-chunk retry capped at 3 with backoff for retryable failures (network, 502/503/504); a 404 on session create rejects `unsupported_agent`; declared size over the cap rejects `too_large` without any request; abort stops between chunks and rejects. Fake `HttpClient` records requests.

- [ ] Failing tests for each behavior above → implement → commit

### Task 2.3: draft reducer

**Files:**
- Create: `apps/core/src/attachments/attachment-draft.ts`, `attachment-draft.test.ts`

**Interfaces (produces):**
```ts
export interface DraftAttachment { localId: string; name: string; mime: string; size: number; status: "uploading" | "uploaded" | "error"; progress: number; attachment?: ChatAttachment; error?: UploadErrorReason }
export function addDraft(drafts, file: {name; mime; size}, localId: string): DraftAttachment[] | null  // null when at MAX_ATTACHMENTS_PER_MESSAGE
export function setDraftProgress(drafts, localId, sent, total): DraftAttachment[]
export function finalizeDraft(drafts, localId, attachment: ChatAttachment): DraftAttachment[]
export function failDraft(drafts, localId, error: UploadErrorReason): DraftAttachment[]
export function removeDraft(drafts, localId): DraftAttachment[]
export function draftsReady(drafts): boolean   // non-empty and all uploaded
export function uploadedIds(drafts): string[]
export function uploadedAttachments(drafts): ChatAttachment[]
```

- [ ] Table-driven failing tests → implement → commit

### Task 2.4: wire the existing seams

**Files:**
- Modify: `apps/core/src/protocol/events.ts` (`user`/`chat` gain `attachments?: ChatAttachment[]`), `apps/core/src/intents/send-message.ts` (`SendMessageBody { text?: string; attachments?: string[]; input_method?: InputMethod }`), `apps/core/src/chat/chat-stream-model.ts` (`beginSend(state, text, inputMethod, intentId, attachments?)` carries them onto the optimistic bubble)
- Test: extend `send-message.test.ts` (body serialization with attachments, no-text body), `chat-stream-model.test.ts` (optimistic bubble carries attachments; echo adoption replaces the pending row wholesale so server metadata wins)

- [ ] Failing tests → implement → run `./check.sh app-core` → commit; open PR 2 (`feat(core): chat attachment model, chunked upload engine, draft reducer`)

---

## Phase 3 (PR 3): web composer (attach, drop, paste, chips, send)

Suite: `./check.sh app-web`; visual states verified through the visual-qa gallery (add scenarios) and a live run before claiming done (per the verify-UI-visually rule).

### Task 3.1: draft hook

**Files:**
- Create: `apps/web/src/components/Chat/use-attachment-drafts.ts`, `use-attachment-drafts.test.ts`

**Interfaces (produces):**
```ts
export interface AttachmentDrafts {
  drafts: DraftAttachment[]
  addFiles: (files: File[]) => void        // size/count guards -> toast; starts uploads; measures image dims via createImageBitmap best-effort
  retry: (localId: string) => void
  remove: (localId: string) => void        // aborts in-flight upload, revokes preview
  clear: () => void                        // post-send
  previewUrl: (localId: string) => string | null   // object-URL map, image/video only
  ready: boolean                           // draftsReady
  uploaded: ChatAttachment[]
}
export function useAttachmentDrafts(agentName: string): AttachmentDrafts
```

`unsupported_agent` failure raises the "This agent needs an update to receive files" toast and removes the draft. Object URLs revoked on remove/clear/unmount.

- [ ] Failing hook tests (fake upload engine via injected module boundary or msw-style fake http) for add/progress/finalize/fail/remove/ready → implement → commit

### Task 3.2: attach menu + paste

**Files:**
- Create: `apps/web/src/components/Chat/ChatComposer/AttachMenu.tsx`
- Modify: `ChatComposer/index.tsx` (wrap the existing Plus in `PopoverTrigger`; disabled when `notAuthenticated`/disconnected), `Chat/index.tsx` (textarea `onPaste` routes `clipboardData.files` to `addFiles`; placeholder switches to "Add a caption" when drafts exist and input is empty)

Popover content: two items (lucide `Image` and `Paperclip` icons), each triggering a hidden `<input type="file" multiple>` (`accept="image/*,video/*"` and unrestricted). `chrome-outline`-consistent styling via the vendored `PopoverContent` defaults.

- [ ] Implement; unit-test the file-input change → `addFiles` wiring and the paste path; commit

### Task 3.3: drop zone

**Files:**
- Create: `apps/web/src/components/Chat/DropZone/index.tsx` (+ pure counter model `drop-zone-model.ts` with tests)
- Modify: `Chat/index.tsx` (mount over the Chat root; only when this instance is the visible one)

States per spec: idle / valid drag-over overlay / non-file drag ignored (`dataTransfer.types` gate) / drop → `addFiles`. Counter pattern in a pure reducer so enter/leave/drop sequencing is table-tested without DOM.

- [ ] Failing reducer tests (enter/enter/leave keeps overlay, final leave hides, drop resets) → implement component → commit

### Task 3.4: chips row

**Files:**
- Create: `apps/web/src/components/Chat/AttachmentChips/index.tsx`
- Modify: `ChatComposer/index.tsx` (render the row as a `basis-full` child of the existing flex-wrap pill so the `layout` spring animates growth)

Chip states per spec (uploading ring with determinate progress, uploaded, error + retry, remove). Thumbnails from `previewUrl`, kind icon tiles otherwise (lucide `FileText`/`Film`/`Music`/`File`). Verify the composer height measurement (`hasDraftRef` rule) still behaves with the taller pill.

- [ ] Implement; add a visual-qa scenario for the chip states; commit

### Task 3.5: send wiring

**Files:**
- Modify: `Chat/index.tsx` (`handleSend` gates on `input.trim() || ready`, passes `uploaded` through, clears drafts on accept), `providers/AgentSocketProvider/use-agent-socket.ts` (`send(text, inputMethod?, attachments?: ChatAttachment[])` → `sendMessage(http, name, { text, input_method, attachments: ids })` + `beginSend(..., attachments)`; `retry` re-carries them), `apps/web/src/lib/types.ts` (mirror field)
- Test: extend `use-agent-socket` tests for the extended send/retry; keyboard Enter no-op while gate closed

- [ ] Failing tests → implement → run `./check.sh app-web` → visual verify → open PR 3 (`feat(web): attachment composer with drag-drop, paste, and upload chips`)

---

## Phase 4 (PR 4): bubbles, lightbox, downloads, desktop save

### Task 4.1: authed media src + download lib

**Files:**
- Create: `apps/web/src/hooks/use-authed-src.ts` (async `authedUrl(appChatAttachmentPath(...))` → `string | null`, rebuilt per mount), `apps/web/src/lib/download.ts` (`downloadAttachment(agent, attachment): Promise<void>` via header-authed `apiFetch` → Blob → object-URL anchor → revoke; throws on !ok)
- Test: `download.test.ts` with a fake fetch; hook test for token stamping

- [ ] Failing tests → implement → commit

### Task 4.2: attachment bubble content

**Files:**
- Create: `apps/web/src/components/Chat/ChatBubble/AttachmentContent/index.tsx` (routes on `attachmentKind`: image with `aspect-ratio` pre-size + skeleton + broken-fallback + lightbox `Dialog`; video `controls preload="metadata"`; audio compact; file tile with download states)
- Modify: `ChatBubble/index.tsx` (render attachment blocks stacked above the markdown caption inside `BubbleContent`; optimistic rows read `previewUrl` from the Chat-level map before the echo)
- Test: render tests for each kind and for caption-less messages; visual-qa scenarios for all four bubble kinds in both user and agent variants, loading and error states

- [ ] Failing tests → implement → visual verify (scroll stability with a loading image: pre-size must hold) → commit

### Task 4.3: desktop will-download

**Files:**
- Modify: `apps/desktop/src/window.ts` (`session.on("will-download")`: default to the OS Downloads dir with a native save dialog)
- Test: `apps/desktop` unit test around the handler wiring; manual verify via the `apps/desktop:verify` skill

- [ ] Implement → `./check.sh app-desktop` → commit → run `./check.sh web` whole chain → open PR 4 (`feat(web,desktop): attachment bubbles, lightbox, and downloads`)

---

## Phase 5 (later, separate plans)

- **Mobile**: pickers (expo-image-picker/document-picker) + share-sheet save, reusing `attachment-draft.ts` and `upload.ts` unchanged; holds for drafts in `src/holds/`.
- **Agent behavior**: teach Vesta when to send files back (prompt/skill text refinement beyond the Phase 1 SKILL.md mechanics).
- **Deferred items** from the spec: bubble-embedded upload progress, thumbnails, FTS over attachment names, camera capture, streaming desktop save.

## Verification map

| Behavior | Suite |
|---|---|
| store/session/chunk/finalize/GC | `test_attachments.py` |
| routes incl. Range + dispositions | `test_service.py` |
| intake invariant + notification line | `test_service.py` |
| `send --attach` | `test_daemon.py` |
| upload engine resume/retry/abort | `upload.test.ts` |
| draft reducer | `attachment-draft.test.ts` |
| send body + optimistic echo | `send-message.test.ts`, `chat-stream-model.test.ts` |
| drop counter, drafts hook, download | web vitest |
| bubble kinds + chip states | render tests + visual-qa gallery |
| end-to-end (later, optional) | extend `vestad/tests/server/sync.rs` app-chat coverage with an upload → message → history round-trip |
