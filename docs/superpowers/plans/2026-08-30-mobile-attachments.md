# Mobile app-chat attachments implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Scope note:** written before any code. The protocol half already ships in `@vesta/core` (proven by the web epic, PR #2295); this plan is mobile view-layer plus native glue plus config. Re-read the spec before each phase.

**Goal:** the phone reaches web/desktop attachment parity, including camera capture, reusing the shipped `@vesta/core` upload engine, draft reducer, and wire types.

**Architecture:** add the missing Expo native modules and permissions; a NetInfo-backed `Connectivity` and a `fetch(uri).blob()` byte source feed the shared `uploadAttachment` engine; a mobile `useAttachmentDrafts` hook and an `attachments` hold cell mirror web; the composer gains an attach action sheet (library / camera / document) and draft chips; bubbles render typed blocks with `expo-image`/`expo-video`/`expo-audio`; a fullscreen `Modal` viewer with pinch-zoom; downloads save via `expo-file-system` + `expo-sharing`.

**Tech stack:** Expo SDK 57 (managed prebuild, New Architecture), React Native 0.86, TypeScript + vitest, `react-native-gesture-handler` + `react-native-reanimated`, Maestro visual QA.

**Spec:** `docs/superpowers/specs/2026-08-30-mobile-attachments-design.md`

## Global constraints

- **No `apps/core/` changes and no `apps/web/`/`vestad/`/`agent/` changes.** The wire contract, upload engine (`apps/core/src/attachments/`), draft reducer, and chat-stream seams already carry attachments. If a core change seems needed, stop and reconsider: web proves it is not.
- Caps and consts come from `@vesta/core` (`MAX_ATTACHMENT_BYTES`, `MAX_ATTACHMENTS_PER_MESSAGE`, `MAX_CHUNK_UPLOAD_BYTES`, etc.); never re-hardcode them.
- Reuse `appChatAttachmentPath`, `attachmentKind`, `formatBytes`, `uploadAttachment`, the `attachment-draft.ts` reducer, and `retryableSends` from `@vesta/core`; do not reimplement.
- New native modules autolink under managed prebuild; every native-surface change must keep `scripts/check-mobile-prebuild.sh` and the `mobile-ios`/`mobile-android` compiles green. Add config-plugin entries and Info.plist/permission strings in `apps/mobile/app.config.ts`.
- Run `./check.sh app-mobile` before every push; `./check.sh mobile-ios` / `mobile-android` where a phase touches native config. Never push to master; work on the epic branch; do not merge without approval.
- No dashes as prose separators in copy; no inline lint escapes; strict TS (no `any`).

## Branch and commit structure

One epic branch `feat/mobile-attachments` cut from master, one reviewed big commit per phase (develop with the inner TDD steps, squash, read the full diff against the spec, run a code-review pass, fold confirmed fixes in, then push), one final epic PR that merges only on explicit approval. Rebase onto master between phases.

---

## Phase 1 (commit 1): native dependencies, permissions, clean prebuild green

The native-surface change, isolated so the prebuild + compile gates review it alone. Suite: `./check.sh app-mobile`, then `./check.sh mobile-ios` and `./check.sh mobile-android`.

### Task 1.1: add dependencies

**Files:**
- Modify: `apps/mobile/package.json`

Add via `npx expo install` (pins SDK-57-compatible versions): `expo-image`, `expo-image-picker`, `expo-document-picker`, `expo-file-system`, `expo-video`, `expo-sharing`, `@react-native-community/netinfo`. Run `npm install` at the `apps` workspace root to update the shared lockfile.

- [ ] Install the packages; confirm `npx expo install --check` reports them compatible
- [ ] Commit `chore(mobile): add attachment native dependencies`

### Task 1.2: config plugins and permissions

**Files:**
- Modify: `apps/mobile/app.config.ts`

Add the `expo-image-picker` plugin with `photosPermission` ("Attach photos and videos to your chat.") and reuse the existing camera/mic strings; add `expo-video`'s plugin if it ships one. Add iOS `NSPhotoLibraryUsageDescription`. Add Android `READ_MEDIA_IMAGES`, `READ_MEDIA_VIDEO`.

- [ ] Edit config; keep the existing QR camera copy unchanged
- [ ] Run `./check.sh app-mobile` (lint + tsc + vitest + clean-prebuild verify)
- [ ] Run `./check.sh mobile-ios` and `./check.sh mobile-android` (autolinking exercised by the real compile)
- [ ] Squash the phase into one commit (`feat(mobile): attachment native modules and permissions`); review the diff + code-review pass; push

---

## Phase 2 (commit 2): upload plumbing and the drafts hook

Pure/hook logic, unit-tested with vitest against fakes. Suite: `./check.sh app-mobile`. No new UI yet.

### Task 2.1: connectivity adapter

**Files:**
- Create: `apps/mobile/src/attachments/connectivity.ts`, `connectivity.test.ts`

**Interfaces (produces):**
```ts
// A @vesta/core Connectivity backed by @react-native-community/netinfo.
export function netInfoConnectivity(): Connectivity  // { isOnline(): boolean; onChange(cb): () => void }
```
Track the latest `isConnected` from `NetInfo.addEventListener`; `isOnline` reads the cached value, `onChange` subscribes and returns the unsubscribe.

- [ ] Failing test with a fake NetInfo module (online edge fires the callback, unsubscribe stops it) → implement → commit

### Task 2.2: picker and Blob source

**Files:**
- Create: `apps/mobile/src/attachments/pick.ts`, `pick.test.ts`

**Interfaces (produces):**
```ts
export interface PickedAsset { uri: string; name: string; mime: string; size: number }
export async function pickFromLibrary(): Promise<PickedAsset[]>   // expo-image-picker launchImageLibraryAsync, multi-select
export async function captureFromCamera(): Promise<PickedAsset[]>  // expo-image-picker launchCameraAsync (photo or video)
export async function pickDocuments(): Promise<PickedAsset[]>      // expo-document-picker
export async function assetToBlob(asset: PickedAsset): Promise<Blob>  // fetch(uri).blob(), the sliceable body
export async function assetSize(asset: PickedAsset): Promise<number>  // asset.size, or expo-file-system getInfoAsync fallback for content:// underreports
```
Each picker gates its permission first (prompt-once, respect prior answer, open-Settings fallback modeled on `scan.tsx`), returns `[]` on cancel or denial, and normalizes the SDK's asset shape to `PickedAsset`.

- [ ] Failing tests with faked expo modules (a granted pick returns normalized assets; a cancel returns `[]`; `assetToBlob` calls `fetch(uri).blob()`; the size fallback triggers when `asset.size` is 0) → implement → commit

### Task 2.3: the drafts hook

**Files:**
- Create: `apps/mobile/src/attachments/use-attachment-drafts.ts`, `use-attachment-drafts.test.ts`
- Modify: `apps/mobile/src/holds/agent-holds.ts` (add the `attachments: KeyedHoldStore<DraftAttachment[]>` cell)

**Interfaces (produces):** mirror web's `AttachmentDrafts`:
```ts
export interface AttachmentDrafts {
  drafts: DraftAttachment[]
  addAssets: (assets: PickedAsset[]) => void   // size/count guard → toast; starts uploads; local preview uri map
  retry: (localId: string) => void
  remove: (localId: string) => void            // aborts the engine, frees the preview
  clear: () => void                            // post-send
  previewUri: (localId: string) => string | null
  ready: boolean
  uploaded: ChatAttachment[]
}
export function useAttachmentDrafts(agent: string, controller: Controller): AttachmentDrafts
```
Port `apps/web/src/stores/use-attachment-drafts.ts` wholesale, swapping: `File` → `PickedAsset` (Blob via `assetToBlob`), `navigator.onLine` adapter → `netInfoConnectivity()`, `httpClient` → `controller.http`, the object-URL preview → the asset's local `uri`. Keep the orphan-safe `mutateDraft`/`release`/eviction handling and the `unsupported_agent` (old-agent 404) toast verbatim. Preview uris are the picker's own local uris, so no revoke is needed (note that difference from web).

- [ ] Failing tests (fake upload engine at the module boundary + fake connectivity): add → progress → waiting → finalize → ready; terminal error → retry starts a fresh run; oversize rejected with a toast, no upload; `unsupported_agent` removes the draft with the update toast; remove aborts; an evicted cell aborts its engine
- [ ] Implement; run `./check.sh app-mobile`; squash the phase into one commit (`feat(mobile): attachment upload plumbing and draft hook`); review + code-review pass; push

---

## Phase 3 (commit 3): composer (attach sheet, chips, send)

Suite: `./check.sh app-mobile`; visual scenarios land in Phase 5.

### Task 3.1: attach action sheet

**Files:**
- Create: `apps/mobile/src/agent/chat/AttachMenu.tsx`

Three actions (Photo or Video Library, Take Photo or Video, File) via a bottom sheet / `@expo/ui` action sheet, each calling the matching `pick.ts` function and passing results to `addAssets`. Disabled while not authenticated.

- [ ] Implement; wire an `Ionicons` attach button into the composer row in `ChatPage.tsx`/`chat-composer.tsx`; commit

### Task 3.2: draft chips

**Files:**
- Create: `apps/mobile/src/agent/chat/AttachmentChips.tsx`

A horizontal scroll row above the input: thumbnail (`expo-image` from the preview uri for image/video, kind-icon tile otherwise), name + `formatBytes`, progress ring, waiting state, terminal error + retry, remove; a totals line for 2+. Mirror `apps/web/src/components/Chat/AttachmentChips`.

- [ ] Implement; verify the composer height/layout accommodates the chips row; commit

### Task 3.3: send gating and wiring

**Files:**
- Modify: `apps/mobile/src/chat/useAgentSocket.ts` (`send`/`retry` gain `attachments?: ChatAttachment[]`, web-parity; add the `retryableSends` reconnect replay), `apps/mobile/src/agent/ChatPage.tsx` (thread `attachments.uploaded`/`clear` through `sendCurrentInput`, extend `sendMode`/gating, block send while uploading/errored)
- Test: extend the `useAgentSocket` vitest for the attachments arg and the reconnect re-post

- [ ] Failing tests (send posts finalized ids + optimistic bubble carries metadata; reconnect re-posts a retry-state bubble once via `retryableSends`) → implement → run `./check.sh app-mobile` → squash the phase into one commit (`feat(mobile): attachment composer and send`); review + code-review pass; push

---

## Phase 4 (commit 4): bubbles, viewer, save

Suite: `./check.sh app-mobile`.

### Task 4.1: authed media uri + save flow

**Files:**
- Create: `apps/mobile/src/lib/authed-media-uri.ts` (a hook resolving `api.authedUrl(appChatAttachmentPath(agent, id))` to a uri string, rebuilt per mount and per retry epoch, the mobile `useAuthedSrc` twin), `apps/mobile/src/lib/save-attachment.ts` (stream `controller.http.request(appChatAttachmentPath(agent, id, true))` to an `expo-file-system` cache file with progress, then `expo-sharing.shareAsync`; a 410 throws a removed error the caller toasts)
- Test: `save-attachment.test.ts` (fake http + fake file-system + fake sharing: writes then shares; a 410 surfaces removed)

- [ ] Failing tests → implement → commit

### Task 4.2: attachment bubble blocks

**Files:**
- Create: `apps/mobile/src/agent/chat/AttachmentContent.tsx` (image via `expo-image` pre-sized + placeholder + broken/removed tiles + reconnect-edge retry; video poster tile → viewer; audio inline `expo-audio` player; file tile → save)
- Modify: `apps/mobile/src/agent/chat/chat-event.tsx` (render blocks above the markdown caption; attachment-only message renders blocks with no body)
- Test: render tests for each kind and the caption-less case

- [ ] Failing tests → implement → verify inverted-FlatList stability (pre-sized images must not jump the list on load) → commit

### Task 4.3: fullscreen viewer

**Files:**
- Create: `apps/mobile/src/agent/chat/AttachmentViewer.tsx` (RN `Modal`: pinch-zoom + pan image via `react-native-gesture-handler`/`reanimated`, double-tap fit↔2×, swipe-down dismiss, caption, share; video via `expo-video` `VideoView` with native controls and best-effort resume), plus a pure `viewer-gesture.ts` clamp model with tests mirroring web's `viewer-zoom.ts`
- Modify: `apps/mobile/src/agent/ChatPage.tsx` (viewer open/close state; bubbles call open)

- [ ] Failing `viewer-gesture.ts` tests (zoom clamp, pan clamp, double-tap toggle) → implement model → implement modal → verify on a device/simulator (per the ask-before-verifying rule, flag if unable) → squash the phase into one commit (`feat(mobile): attachment bubbles, viewer, and save`); review + code-review pass; push

---

## Phase 5 (commit 5): visual QA (Maestro)

Follow `apps/mobile/visual/README.md`: production screens rendered as-is, fixtures at the picker/upload boundary in `visual/harness/`, `setPermissions` for photo/camera in the flow.

**Files:**
- Modify: `apps/mobile/visual/metro.config.js` (map the picker + upload-engine boundary to harness fixtures: a deterministic picked asset and a scripted upload that completes / stalls / 404s)
- Modify: a chat/composer Maestro flow under `apps/mobile/maestro/visual/` + `apps/mobile/visual/scenarios.json`
- Serve fixture attachment bytes for the bubble/viewer scenarios (a small deterministic image, a short video, a wav) through the harness

Scenarios (ids unique, `group: "Chat"`): attach sheet open, draft chips (uploaded + uploading + totals), waiting-for-network chip, attachment bubbles (all four kinds), removed/broken tiles, the fullscreen viewer (fitted and zoomed).

- [ ] Add fixtures, flow steps (with `setPermissions`), and registry entries → `./check.sh app-visual` and the mobile registry test → `npm run visual:ios:capture` and `visual:android:capture` → inspect the gallery pixels (both themes, ios/android/android-galaxy) → squash the phase into one commit (`test(mobile): attachment visual scenarios`); review; push

---

## Closing task: the epic PR

- [ ] Rebase `feat/mobile-attachments` onto master (never soft-reset; diff-stat sanity-check after)
- [ ] Run `./check.sh app-mobile`, `./check.sh mobile-ios`, `./check.sh mobile-android`, `./check.sh app-visual`
- [ ] Open the epic PR: `feat/mobile-attachments` → master, title `feat: mobile app chat attachments`, body summarizing per surface (native deps, upload plumbing, composer, bubbles/viewer/save) with a link to the spec
- [ ] Verify `merge-gate-ci` is green and the PR is mergeable; then stop. **Merges only on explicit approval.**

## Verification map

| Behavior | Suite |
|---|---|
| clean prebuild + native compile with new modules | `check.sh app-mobile` (prebuild verify) + `mobile-ios`/`mobile-android` |
| connectivity adapter, pickers, Blob source | `connectivity.test.ts`, `pick.test.ts` |
| drafts hook (add/progress/waiting/finalize/error/orphan) | `use-attachment-drafts.test.ts` |
| send + retry with attachments, reconnect re-post | `useAgentSocket` vitest |
| save flow + 410 | `save-attachment.test.ts` |
| viewer gesture math | `viewer-gesture.test.ts` |
| bubble kinds, chips, viewer | render tests + Maestro scenarios |
