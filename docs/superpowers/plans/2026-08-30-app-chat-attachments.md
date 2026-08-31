# App-chat attachments implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Scope note:** this is a scoping-mode plan, written before any code. Contracts, types, signatures, states, and test behaviors are locked here; implementation bodies are written at execution time, test-first. Each phase lands as one reviewed commit on the epic branch (see Branch and commit structure). Re-read the spec before each phase.

**Goal:** users send any file to their agent through app chat and receive typed attachment bubbles back, on web and desktop, over a chunked upload contract that mobile reuses later.

**Architecture:** the app-chat skill stores blobs on the agent's disk and extends its service with a chunked upload + streamed download contract; `@vesta/core` gains the shared upload engine, draft reducer, and wire types; the web app builds the composer UX (popover, drag-drop, paste, chips) and typed bubbles; desktop adds only a `will-download` handler. vestad is untouched.

**Tech stack:** aiohttp + sqlite (skill), TypeScript + vitest (`@vesta/core`), React + Tailwind + motion + vendored shadcn primitives (web), Electron main process (desktop).

**Spec:** `docs/superpowers/specs/2026-08-30-app-chat-attachments-design.md`

## Global constraints

- Server caps: `MAX_CHUNK_BYTES = 8 * 1024 * 1024`, `MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024`, `MAX_ATTACHMENTS_PER_MESSAGE = 10` (Python consts in `attachments.py`). Client sizing/retry consts (`attachment-model.ts`): `MAX_CHUNK_UPLOAD_BYTES = 8 MiB`, `INITIAL_CHUNK_BYTES = 1 MiB`, `MIN_CHUNK_BYTES = 256 KiB`, `CHUNK_TIMEOUT_MS = 120_000`, `CHUNK_FAST_SECS = 2`, `RETRY_BASE_MS = 1_000`, `RETRY_MAX_MS = 30_000`. The wire contract in the spec is the seam.
- Resilience invariants (spec, "Resilience on poor and spotty connections"): offset-addressed uploads with 409 resync, idempotent complete, status-probe resume, adaptive chunk sizing, unbounded classified retries, offline parking. Every one has a behavioral test.
- All attachment routes ride the existing private app-chat service; no new service, no vestad change, no `/sync` change, no `min_supported` bump, no fixture regen.
- The intake at-most-once invariant in `service.py::message_handler` must survive: no fallible step may be added after the notification write.
- Skill work follows `agent/` prompt rules (invoke vesta-prompt-guide before editing `SKILL.md`); no dashes as prose separators; no inline lint escapes; each phase runs its `./check.sh` subcommands before push; never push to master; do not merge without approval.
- Chat-plane compat: `attachments` is optional on `user`/`chat` events; old clients must keep parsing (no changes to `parse.ts` or the ignore-unknown tests).

## Branch and commit structure (one epic branch, one epic PR)

Nothing merges to master until the whole feature is reviewed as one, and there are no intermediate PRs. Structure (standing instruction from Emi, 2026-08-30):

- **One branch**: `feat/app-chat-attachments`, cut from master at Phase 1 start, worked in its own worktree.
- **One big commit per phase.** A phase's tasks are developed with the plan's inner TDD steps, then squashed into a single phase commit with a full Conventional Commits message (the phase's `feat(...)` subject plus a body listing what it contains).
- **Review before every push.** Before a phase commit is pushed: the phase's `./check.sh` slices pass, the full phase diff is read end to end against the spec, and a code-review pass runs on it, with confirmed findings fixed and folded into the commit. Only then push.
- **Master drift**: rebase the epic branch onto master between phases when master moves (never soft-reset; diff-stat sanity-check after).
- **Final deliverable**: one epic PR, `feat/app-chat-attachments` → master, opened after the Phase 4 commit is pushed. Four reviewed phase commits are its history; the body summarizes per surface and links the spec. It merges only on Emi's explicit approval.

---

## Phase 1 (commit 1): app-chat attachment store + endpoints + `send --attach`

Standalone and fully testable with pytest; clients come later. Suite: `agent/skills/app-chat/cli/tests/`, run via `uv run --project agent/skills/app-chat/cli pytest agent/skills/app-chat/cli/tests/` (picked up by `./check.sh app-chat`).

### Task 1.1: attachment store module

**Files:**
- Create: `agent/skills/app-chat/cli/src/app_chat_cli/attachments.py`
- Test: `agent/skills/app-chat/cli/tests/test_attachments.py`

**Interfaces (produces):**
```python
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10
STALE_SESSION_MAX_AGE_SECS = 24 * 3600

class AttachmentMeta(tp.TypedDict, total=False):
    id: str; name: str; mime: str; size: int
    width: int; height: int; duration_secs: float

def create_session(root: Path, name: str, mime: str, size: int, extra: AttachmentMeta) -> str  # returns id; raises SizeError
def append_at(root: Path, attachment_id: str, offset: int, data: bytes) -> int  # appends only when offset == staged size, returns staged bytes; raises OffsetMismatch(received)/UnknownAttachment
def staged_size(root: Path, attachment_id: str) -> int  # raises UnknownAttachment
def finalize(root: Path, attachment_id: str) -> AttachmentMeta  # renames .part, writes meta.json final; raises SizeMismatch; idempotent on an already-finalized id
def read_meta(root: Path, attachment_id: str) -> AttachmentMeta | None  # None until finalized
def blob_path(root: Path, attachment_id: str) -> Path
def ingest_file(root: Path, source: Path, mime: str | None) -> AttachmentMeta  # copy-in for agent sends; mime guessed via mimetypes when None
def sweep(root: Path, now: float, referenced: cabc.Callable[[str], bool]) -> list[str]  # removes stale .part sessions and unreferenced finalized dirs older than the max age
def remove_blob(root: Path, attachment_id: str) -> int  # deletes the blob, keeps meta.json, returns freed bytes; idempotent (already-removed returns 0); raises UnknownAttachment
def is_removed(root: Path, attachment_id: str) -> bool  # meta.json present, blob absent: the 410 condition
def sanitize_filename(name: str) -> str  # strips path separators/control chars, caps length, never empty
```

Disk layout per spec: `<root>/<id>/meta.json` + `<root>/<id>/<sanitized-name>` (staging suffix `.part`). Appends are offset-checked: a write at a stale offset raises with the true staged size, so a client that lost a response resyncs instead of corrupting the stage.

- [ ] Write failing tests: session create rejects size over cap; sequential offset appends accumulate; a stale offset raises with `received` and stages nothing; a replayed append whose bytes already landed raises with `received == offset + len` (the lost-response case); `staged_size` tracks; finalize rejects size mismatch, renames the blob, and is an idempotent no-op when already finalized; `read_meta` is `None` pre-finalize; `ingest_file` copies and guesses mime; `sanitize_filename` strips `../` and slashes; `sweep` removes a stale `.part` and an old unreferenced dir but keeps a referenced one and keeps a removed-blob dir (meta only); `remove_blob` frees and reports bytes, is idempotent, and flips `is_removed`
- [ ] Implement `attachments.py` minimally to pass
- [ ] Run the suite; commit `feat(app-chat): attachment blob store`

### Task 1.2: HTTP routes

**Files:**
- Modify: `agent/skills/app-chat/cli/src/app_chat_cli/service.py`
- Test: `agent/skills/app-chat/cli/tests/test_service.py` (extend)

**Interfaces (produces):** the five routes exactly as the spec's wire contract: `POST /attachments`, `PUT /attachments/{id}/data?offset={n}`, `GET /attachments/{id}/status`, `POST /attachments/{id}/complete`, `GET /attachments/{id}` (via `web.FileResponse` with `Content-Disposition` from `sanitize_filename`, `?download=1` toggling `attachment`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, max-age=31536000, immutable`). `web.Application(client_max_size=MAX_CHUNK_BYTES + 1024 * 1024)`. `ServiceState` gains `attachments_root: Path` (default `data_dir / "attachments"`); daemon start runs `sweep` with a referenced-check that scans `events.data` for the candidate id.

- [ ] Write failing aiohttp test-client tests: full happy path (create → 2 offset PUTs → complete → GET bytes round-trip with correct headers); 413 on oversize declare; 409 on a stale offset carries `received`; status reports `{received, size, finalized}` mid-stage and post-finalize; complete is idempotent (second call returns the same metadata); 409 on complete with missing bytes; 404 on unknown id; 410 on a removed blob (meta present, blob absent); Range request returns 206; `?download=1` flips disposition
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

### Task 1.5: `app-chat attachments` CLI (list, rm)

**Files:**
- Modify: `cli.py` (subparser), `commands.py` (`cmd_attachments_list`, `cmd_attachments_rm`)
- Test: `agent/skills/app-chat/cli/tests/test_attachments_cli.py`

**Interfaces (produces):** the spec's CLI contract. `list` reads the attachments dir plus the store db directly (largest-first default, `--sort size|date`, `--limit`, `--min-size`), joining each id to its referencing event for `ts` and `direction` (`user` event → `received`, `chat` → `sent`) and marking `removed` via `is_removed`; prints one line: `{"attachments": [...], "count": n, "total_bytes": n}`. `rm` calls `remove_blob` per id, prints `{"removed": [...], "freed_bytes": n}`, and fails on stderr with non-zero exit for an unknown id. No daemon socket involved; works with the daemon up or down.

- [ ] Write failing tests: list sorts largest-first with correct `total_bytes`; `--sort date`, `--limit`, and `--min-size` filter; `direction` and `ts` join correctly; a removed id lists with `removed: true` and its size excluded from `total_bytes`; rm frees the blob, keeps `meta.json`, reports `freed_bytes`, is idempotent, and exits non-zero on an unknown id with a single-line JSON error on stderr
- [ ] Implement; run; commit `feat(app-chat): attachments list and rm`

### Task 1.6: SKILL.md + checks

**Files:**
- Modify: `agent/skills/app-chat/SKILL.md`

The spec's "Agent side" section carries the draft copy: the description gains "send files with --attach" as a discovery trigger, and a new `## Attachments` body section covers receiving (the `attachments` notification attribute with absolute paths and sizes, `Read` for images/PDFs, shell tools otherwise), sending (`--attach` examples with and without `--message`, temp files safe to remove after, 512 MB cap, lint on text only), disk management (`app-chat attachments list|rm`, never raw-delete under `~/.app-chat/attachments/`), and the preference to attach real artifacts instead of pasting them as text. Rules: invoke vesta-prompt-guide before writing, state mechanism only (no changelog prose), concrete command examples over descriptions, no dash separators (the SKILL.md dash guard covers this file).

- [ ] Write the section following the draft; verify against the guide's checklist (description states when, not how; no old-design prose)
- [ ] Confirm zero `agent/core/` diffs in the PR (the spec's designed property: notification rendering and interrupt policy are generic)
- [ ] Run `./check.sh app-chat` and `./check.sh guards`; squash the phase into one commit (`feat(app-chat): user attachments over chunked upload`); review the full diff against the spec + code-review pass; push to `feat/app-chat-attachments`

---

## Phase 2 (commit 2): @vesta/core attachment modules

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
export const MAX_CHUNK_UPLOAD_BYTES: number  // 8 MiB, mirrors the server cap
export const INITIAL_CHUNK_BYTES: number     // 1 MiB
export const MIN_CHUNK_BYTES: number         // 256 KiB
export const CHUNK_TIMEOUT_MS: number        // 120_000
export const CHUNK_FAST_SECS: number         // 2
export const RETRY_BASE_MS: number           // 1_000
export const RETRY_MAX_MS: number            // 30_000
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
export interface Connectivity { isOnline: () => boolean; onChange: (cb: (online: boolean) => void) => () => void }
export interface UploadDeps { connectivity: Connectivity; setTimer: (fn: () => void, ms: number) => number; clearTimer: (handle: number) => void; now: () => number }
export interface UploadCallbacks { onProgress: (sentBytes: number, totalBytes: number) => void; onStateChange: (state: "uploading" | "waiting") => void }
export type UploadErrorReason = "too_large" | "unsupported_agent" | "failed"
export interface UploadHandle { result: Promise<ChatAttachment>; abort: () => void }  // result rejects with UploadError{reason}
export function uploadAttachment(http: HttpClient, agent: string, blob: Blob, meta: UploadMeta, deps: UploadDeps, callbacks: UploadCallbacks): UploadHandle
```

Behavior locked by tests (fake `HttpClient`, fake timers, fake connectivity):
- sequential `Blob.slice` offset PUTs with `AbortSignal.timeout(CHUNK_TIMEOUT_MS)`; progress after each accepted chunk
- adaptive sizing: chunk doubles after a sub-`CHUNK_FAST_SECS` success (capped at `MAX_CHUNK_UPLOAD_BYTES`), halves after a timeout or network failure (floored at `MIN_CHUNK_BYTES`)
- a 409 resyncs the offset to the server's `received` and is not counted as a failure; a 409 with `received == offset + len` reads as delivered
- failure classification: 413/create-404 (`unsupported_agent`)/size-mismatch reject terminally; network/abort/408/429/5xx retry forever with `RETRY_BASE_MS → RETRY_MAX_MS` backoff and emit `waiting`
- offline parking: while `connectivity.isOnline()` is false no timer burns; the online edge probes `GET .../status`, adopts `received`, resumes, and emits `uploading`
- declared size over the cap rejects `too_large` without any request; abort stops between chunks, cancels timers, and rejects; complete retries ride the same classification and its idempotence

- [ ] Failing tests for each behavior above → implement → commit

### Task 2.3: draft reducer

**Files:**
- Create: `apps/core/src/attachments/attachment-draft.ts`, `attachment-draft.test.ts`

**Interfaces (produces):**
```ts
export interface DraftAttachment { localId: string; name: string; mime: string; size: number; status: "uploading" | "waiting" | "uploaded" | "error"; progress: number; attachment?: ChatAttachment; error?: UploadErrorReason }
export function addDraft(drafts, file: {name; mime; size}, localId: string): DraftAttachment[] | null  // null when at MAX_ATTACHMENTS_PER_MESSAGE
export function setDraftProgress(drafts, localId, sent, total): DraftAttachment[]  // also flips waiting -> uploading
export function setDraftWaiting(drafts, localId): DraftAttachment[]
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

- [ ] Failing tests → implement → run `./check.sh app-core`; squash the phase into one commit (`feat(core): chat attachment model, chunked upload engine, draft reducer`); review the full diff + code-review pass; push

---

## Phase 3 (commit 3): web composer (attach, drop, paste, chips, send)

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

`unsupported_agent` failure raises the "This agent needs an update to receive files" toast and removes the draft. Object URLs revoked on remove/clear/unmount. The hook owns the web `Connectivity` adapter (`navigator.onLine` + `online`/`offline` window events) and feeds it to the engine; engine `onStateChange` drives the `waiting` draft status.

- [ ] Failing hook tests (fake upload engine via injected module boundary or msw-style fake http) for add/progress/waiting/finalize/fail/remove/ready → implement → commit

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

Chip states per spec (uploading ring with determinate progress, waiting with the wifi-off glyph and auto-resume, uploaded, terminal error + retry, remove). Every chip shows name + `formatBytes(size)` from the moment it appears; two or more chips add the muted totals footer ("3 files · 48 MB"). Thumbnails from `previewUrl`, kind icon tiles otherwise (lucide `FileText`/`Film`/`Music`/`File`, `WifiOff` for waiting). Verify the composer height measurement (`hasDraftRef` rule) still behaves with the taller pill.

- [ ] Implement; commit (gallery scenarios for these states land in Task 3.6)

### Task 3.5: send wiring

**Files:**
- Modify: `Chat/index.tsx` (`handleSend` gates on `input.trim() || ready`, passes `uploaded` through, clears drafts on accept), `providers/AgentSocketProvider/use-agent-socket.ts` (`send(text, inputMethod?, attachments?: ChatAttachment[])` → `sendMessage(http, name, { text, input_method, attachments: ids })` + `beginSend(..., attachments)`; `retry` re-carries them; on the socket's reconnect edge, a message in `send_state: "retry"` is re-posted automatically once, safe under intent dedup), `apps/web/src/lib/types.ts` (mirror field)
- Test: extend `use-agent-socket` tests for the extended send/retry, the one-shot reconnect re-post (and that it fires only once per reconnect), and keyboard Enter no-op while gate closed

- [ ] Failing tests → implement → run `./check.sh app-web` → visual verify → commit

### Task 3.6: visual QA harness, composer states

Follow the visual-qa skill (`apps/visual/.agents/skills/visual-qa/SKILL.md`): production routes rendered as-is, no capture logic in `web/src/`, fixtures model infrastructure only, `settle` asserts the captured state.

**Files:**
- Modify: `apps/web/visual/harness/http-fixtures.ts` (fixture routes for the app-chat attachment contract: `POST .../attachments` → fixed id; `PUT .../data` with a **stall variant** for one designated id, accepting the first chunk then never answering, which is the sanctioned deterministic delay for a real loading state; `POST .../complete`; a 413 route for the oversize case)
- Modify: `apps/web/visual/drives.ts` + `apps/web/visual/scenarios.json` (group `"Chat"`)

Scenarios (ids unique across both families):
- `chat-attach-menu`: open the composer Plus popover; settle on the two options.
- `chat-attachment-chips`: `setInputFiles` with three fixture files: one that completes (uploaded chip), one routed to the stalling id (uploading chip frozen at a known progress), one oversized (rejected via toast, so the shot also proves the guard); settle on the totals footer text.
- `chat-attachment-chips-offline`: add a file, then `context.setOffline(true)`; settle on the "waiting for network" chip.
- `chat-attachment-dropzone`: dispatch `dragenter` with a `DataTransfer` carrying the `Files` type; settle on the "Drop to send" overlay.

- [ ] Add fixtures, drives, and registry entries → `./check.sh app-visual` → `npm run web:visual:capture` → inspect the gallery pixels (both themes, `web`, `desktop`, `web-narrow`) → squash the phase into one commit (`feat(web): attachment composer with drag-drop, paste, and upload chips`); review the full diff + code-review pass; push

---

## Phase 4 (commit 4): bubbles, in-chat viewer, downloads, desktop save

### Task 4.1: authed media src + download lib

**Files:**
- Create: `apps/web/src/hooks/use-authed-src.ts` (async `authedUrl(appChatAttachmentPath(...))` → `string | null`, rebuilt per mount), `apps/web/src/lib/download.ts` (`downloadAttachment(agent, attachment): Promise<void>` via header-authed `apiFetch` → Blob → object-URL anchor → revoke; throws on !ok)
- Test: `download.test.ts` with a fake fetch; hook test for token stamping

- [ ] Failing tests → implement → commit

### Task 4.2: attachment bubble content

**Files:**
- Create: `apps/web/src/components/Chat/ChatBubble/AttachmentContent/index.tsx` (routes on `attachmentKind`: image with `aspect-ratio` pre-size + skeleton + broken-fallback with manual retry and one auto-retry per `connected` reconnect edge; video `controls preload="metadata"` with the corner expand button; audio compact; file tile with download states, progress read from the response stream against metadata `size`; the removed tile on a 410, terminal with no retry; `formatBytes(size)` on the file tile, the viewer caption, and the video/audio corner badge)
- Modify: `ChatBubble/index.tsx` (render attachment blocks stacked above the markdown caption inside `BubbleContent`; optimistic rows read `previewUrl` from the Chat-level map before the echo)
- Test: render tests for each kind and for caption-less messages (gallery scenarios land in Task 4.3)

- [ ] Failing tests → implement → visual verify (scroll stability with a loading image: pre-size must hold) → commit

### Task 4.2b: in-chat attachment viewer

**Files:**
- Create: `apps/web/src/components/Chat/AttachmentViewer/index.tsx`, `apps/web/src/components/Chat/AttachmentViewer/viewer-zoom.ts`, `viewer-zoom.test.ts`
- Modify: `Chat/index.tsx` (per-instance `viewer` state: `{attachment, source} | null`; the overlay mounts inside the Chat card root)

**Interfaces (produces):**
```ts
// viewer-zoom.ts: pure, fully table-tested
export interface ZoomState { scale: number; x: number; y: number }
export function zoomAt(state: ZoomState, cursor: {x; y}, factor: number, bounds: {fit: number; max: number}): ZoomState  // cursor-anchored, clamped
export function panBy(state: ZoomState, dx: number, dy: number, container: Size, content: Size): ZoomState  // clamped so content never detaches from view
export function toggleZoom(state: ZoomState, cursor: {x; y}, bounds): ZoomState  // fit <-> 2x (double-click)
```

Component behavior per the spec's viewer table: contained overlay on the Chat card (Radix Dialog primitives without `Portal` for focus trap + Esc + aria), local `bg-background/80` scrim, media capped at ~88% of container, wheel/ctrl+wheel zoom, drag pan, double-click toggle, video with native controls and best-effort `currentTime` handoff from the inline element, X + download + name/size/dimensions caption, scrim click and Esc close, focus return, `stepTransition` scale-fade honoring reduced motion.

- [ ] Failing `viewer-zoom.ts` tests (cursor-anchored zoom math, clamp bounds at fit and 4×, pan clamps at edges, double-click toggle) → implement model → implement component → visual verify in both panel and fullscreen Chat instances (containment: the overlay must never cover the roster or navbar) → commit (gallery scenarios land in Task 4.3)

### Task 4.3: visual QA harness, bubbles + viewer

Same rules as Task 3.6 (visual-qa skill; fixtures only, production rendering untouched).

**Files:**
- Modify: `apps/web/visual/harness/http-fixtures.ts` (app-chat `history` fixture gains attachment events on both `user` and `chat` rows; `GET .../attachments/{id}` routes serving deterministic fixture bytes: a small solid-color PNG with known dimensions, a tiny fixture mp4 whose first frame is a solid color, a short wav, a plain file; one id answering 410; one image id behind the sanctioned deterministic delay for the skeleton state)
- Modify: `apps/web/visual/drives.ts` + `apps/web/visual/scenarios.json` (group `"Chat"`)

Scenarios:
- `chat-attachment-bubbles`: history with all four kinds across user and agent sides, captions and sizes visible; settle on the file tile's size text.
- `chat-attachment-bubble-states`: loading skeleton (delayed image), broken fallback, removed tile (410) in one conversation; settle on "no longer available".
- `chat-attachment-viewer`: click the image bubble; settle on the viewer caption; the shot proves containment (roster and navbar visible around the scrim).
- `chat-attachment-viewer-zoomed`: wheel-zoom then pan via dispatched pointer events; settle on the zoom state (e.g. the caption plus a translated img transform).
- `chat-attachment-viewer-video`: expand the video bubble; settle on the viewer's video element being ready (`readyState`), first frame deterministic by fixture.

- [ ] Add fixtures, drives, and registry entries → `./check.sh app-visual` → `npm run web:visual:capture` → inspect gallery pixels in both themes and all three web-family platforms → commit

### Task 4.4: desktop will-download

**Files:**
- Modify: `apps/desktop/src/window.ts` (`session.on("will-download")`: default to the OS Downloads dir with a native save dialog)
- Test: `apps/desktop` unit test around the handler wiring; manual verify via the `apps/desktop:verify` skill

- [ ] Implement → `./check.sh app-desktop` → run `./check.sh web` whole chain → squash the phase into one commit (`feat(web,desktop): attachment bubbles, viewer, and downloads`); review the full diff + code-review pass; push

## Closing task: the epic PR

- [ ] Rebase the epic branch onto master one last time (never soft-reset; diff-stat sanity-check after)
- [ ] Run the full relevant check set on the branch: `./check.sh guards`, `./check.sh app-chat`, `./check.sh web`
- [ ] Open the epic PR: `feat/app-chat-attachments` → master, title `feat: app chat attachments`, body summarizing per surface (skill contract, core engine, composer UX, viewer, downloads, desktop) with a link to the spec; the four reviewed phase commits are the history
- [ ] Verify `merge-gate-ci` is green and the PR is mergeable; then stop. **The epic PR merges only on Emi's explicit approval.**

---

## Phase 5 (later, separate plans, outside this epic)

- **Mobile**: pickers (expo-image-picker/document-picker) + share-sheet save, reusing `attachment-draft.ts` and `upload.ts` unchanged; holds for drafts in `src/holds/`.
- **Agent behavior refinement**: the Phase 1 SKILL.md ships the full mechanics plus the attach-over-paste preference; revisit only if real transcripts show the agent underusing or misusing attachments (a vesta-feel style pass, evidence first).
- **Deferred items** from the spec: bubble-embedded upload progress, thumbnails, FTS over attachment names, camera capture, streaming desktop save.

## Verification map

| Behavior | Suite |
|---|---|
| store/session/offset append/finalize/GC | `test_attachments.py` |
| routes incl. status, Range, dispositions | `test_service.py` |
| intake invariant + notification line | `test_service.py` |
| `send --attach` | `test_daemon.py` |
| `attachments list`/`rm` + 410 serve state | `test_attachments_cli.py`, `test_service.py` |
| engine: adaptive sizing, 409 resync, offline parking, status-probe resume, timeout, abort | `upload.test.ts` |
| reconnect re-post of a retry-state send | `use-agent-socket` tests |
| draft reducer | `attachment-draft.test.ts` |
| send body + optimistic echo | `send-message.test.ts`, `chat-stream-model.test.ts` |
| drop counter, drafts hook, download | web vitest |
| bubble kinds + chip states | render tests + gallery scenarios (Tasks 3.6, 4.3) |
| viewer zoom/pan math + containment | `viewer-zoom.test.ts` + gallery scenarios (Task 4.3) |
| end-to-end (later, optional) | extend `vestad/tests/server/sync.rs` app-chat coverage with an upload → message → history round-trip |
