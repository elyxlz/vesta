# Mobile app-chat attachments

**Date:** 2026-08-30
**Status:** Design draft, pending review. No code written.

## Goal

The phone reaches parity with web and desktop: the user attaches images, videos, documents, or a fresh camera capture in app chat, sends them to the agent, and views/saves the files the agent sends back. The whole protocol half (upload engine, draft reducer, wire types, download URL) already ships in `@vesta/core` and is battle-tested by the web app; mobile builds the native front half only.

## Ground truth (verified in the current tree)

- **Everything protocol-side already ships.** `apps/core/src/attachments/` holds `uploadAttachment` (offset-addressed chunked upload over an injected `HttpClient`, adaptive sizing, 409 resync, offline parking), the pure `attachment-draft.ts` reducer, and `attachment-model.ts` (`ChatAttachment`, `attachmentKind`, `formatBytes`, `appChatAttachmentPath`, the caps). `chat-stream-model.ts` already threads `attachments?: ChatAttachment[]` through `beginSend`, `foldLiveEvent`, `retryableSends`, and `SendMessageBody.attachments?: string[]`. **No core changes.**
- **The upload engine slices a `Blob`.** `upload.ts` does `blob.slice(offset, ...)`. React Native (Fabric, RN 0.86) ships a native-backed Blob: `await fetch(pickedUri).blob()` returns a sliceable Blob for `file://` and `content://` URIs on both platforms, and a Blob body PUTs its bytes. So the shared engine runs on RN unchanged once a picked URI is turned into a Blob.
- **The mobile HTTP client is already an `HttpClient`.** `controller.http` (built via core `createHttpClient` in `apps/mobile/src/api/client.ts`) forwards arbitrary `RequestInit`, so binary chunk PUTs already work through it. `api.authedUrl(path)` stamps `?token=` for media elements, exactly as web's `authedUrl` does.
- **`useAgentSocket` (`apps/mobile/src/chat/useAgentSocket.ts`) is behind web.** Its `send`/`retry` take no `attachments` arg and it has no `retryableSends` reconnect replay. Both are additive parity changes; the core signatures already accept them.
- **The composer is a single morphing mic↔send button** (`apps/mobile/src/agent/chat/chat-composer.tsx`, `ChatPage.tsx`). There is no attach button today. Icons are `@expo/vector-icons` `Ionicons`.
- **Bubbles render via `react-native-markdown-display`** in `chat-event.tsx`; rows come from `chat-list-model.ts` (`EventChatRow.event.attachments` is already available). No new row type.
- **The app displays no bitmap media today.** Only `react-native-svg` (orb, brand). `expo-image` is absent.
- **Native inventory:** Expo SDK 57, New Architecture, **managed prebuild (no committed `ios/`/`android/` dirs)**. Present: `expo-camera` (QR only), `expo-audio` (voice), `expo-web-browser`, `react-native-gesture-handler`, `react-native-reanimated`. **Absent, must add:** `expo-image`, `expo-image-picker`, `expo-document-picker`, `expo-file-system`, `expo-video`, `expo-sharing`, and a connectivity source.
- **Config lives in `apps/mobile/app.config.ts`** (dynamic TS, no static app.json). Adding a native module = add the dep, its config plugin, and iOS Info.plist usage strings / Android permissions; Expo autolinking wires the pod/gradle. The `scripts/check-mobile-prebuild.sh` clean-prebuild verify plus the `mobile-ios`/`mobile-android` native compiles gate it.
- **Permission UX template:** `apps/mobile/app/scan.tsx` (in-context camera permission with allow / open-Settings fallback, re-check on `AppState` active) and `apps/mobile/src/device-context/location-consent.ts` (prompt-once, respect prior answer).
- **Save/share today:** only `apps/mobile/src/sharing/share-message.ts` (text share via a native module + RN `Share`). No file download/save flow.

## Decisions (locked)

Each fork resolved once, with the reason.

1. **Reuse the shared engine and reducer verbatim.** Mobile's only new logic is a thin `useAttachmentDrafts` hook mirroring `apps/web/src/stores/use-attachment-drafts.ts`, swapping three edges: `File` → a picked asset turned into a Blob via `fetch(uri).blob()`, `navigator.onLine` → a NetInfo-backed `Connectivity`, and `httpClient` → `controller.http`. Rejected: a mobile-specific upload path (the engine is the hard part and it already exists).
2. **Camera capture folds into the picker, no custom camera screen.** `expo-image-picker`'s `launchCameraAsync` gives the native camera UI for photo and video capture; `launchImageLibraryAsync` gives the photo/video library; `expo-document-picker` gives arbitrary files. Three entry points, one draft pipeline. Rejected: an `expo-camera` capture screen (expo-camera stays scoped to QR scanning; rebuilding capture is needless native surface).
3. **`fetch(uri).blob()` is the byte source; `expo-file-system` supplies metadata and the download half.** The upload path needs only the Blob. `expo-file-system` is added for reliable size/mime when a `content://` asset underreports, and is required for the download-and-save half (write bytes to cache, hand to the share sheet). Rejected: base64 round-tripping through the JS bridge (multi-hundred-MB files would blow memory).
4. **Connectivity via `@react-native-community/netinfo`.** Event-based (`addEventListener`), Expo-autolink-compatible, no config plugin. Its `isConnected` plus the listener satisfy the engine's `Connectivity` interface (`isOnline`, `onChange`). Rejected: polling `expo-network` (the engine parks on the connectivity *edge*, which wants an event, not a poll).
5. **Media rendering: `expo-image` (images), `expo-video` (video), `expo-audio` (audio).** `expo-image` matches web's `<img>` role with a token-in-URL source from `api.authedUrl(appChatAttachmentPath(...))`. `expo-video` is the SDK 57 successor for inline video (expo-av is deprecated). `expo-audio`'s `useAudioPlayer` is already the app's audio path (voice TTS), reused for audio attachments. Rejected: a WebView per media (heavy, and the token-in-URL flow is simpler).
6. **The fullscreen viewer is a native RN modal, not a portal trick.** Web's viewer is contained inside the Chat card because the web app is one window; on mobile a full-screen `Modal` with a pinch-zoom image (`react-native-gesture-handler` + `react-native-reanimated`, both already present) is the native idiom. Video opens the same modal with `expo-video` controls. Rejected: reusing web's contained-overlay shape (there is no roster to keep visible on a phone).
7. **Download saves via the share sheet.** `expo-file-system` writes the streamed bytes to a cache file, then `expo-sharing.shareAsync` opens the OS share sheet (save to Files, Photos, AirDrop, etc.). This is one permission-free flow covering every save target. `expo-media-library` (direct "save to camera roll") is deferred: it adds a photo-add permission for a target the share sheet already reaches.
8. **The wire, the send path, and compatibility are identical to web.** Mobile posts the same `POST /message` with finalized ids, gets the same echo, and an old agent's `404` on `POST .../attachments` surfaces the same "this agent needs an update" state. No `min_supported` bump; the field is already additive-safe on the chat plane.
9. **Drafts are held per agent and gateway** in a new `agentHolds.attachments` cell (a fifth `createKeyedHoldStore<DraftAttachment[]>()` in `apps/mobile/src/holds/agent-holds.ts`), consumed reactively with `useHeld` (like web's store), so leaving the chat screen or backgrounding never cancels an upload. The LRU-eviction orphan safety the web store carries (abort the engine and free previews when a cell is evicted) ports verbatim.

## Permissions and config (app.config.ts)

- **iOS Info.plist usage strings to add:** `NSPhotoLibraryUsageDescription` ("Attach photos and videos to your chat."), and `NSMicrophoneUsageDescription` already exists (camera video capture with audio). `NSCameraUsageDescription` already exists (QR); its copy stays QR-focused since capture reuses the same permission. `NSPhotoLibraryAddUsageDescription` only if media-library save lands (deferred).
- **Android permissions to add:** `READ_MEDIA_IMAGES`, `READ_MEDIA_VIDEO` (API 33+ scoped media read for the picker). The document picker uses the Storage Access Framework and needs no permission. Save-via-share needs none.
- **Config plugins to add:** `expo-image-picker` (with its `photosPermission`/`cameraPermission` strings) and, if it ships one, `expo-video`. `expo-image`, `expo-document-picker`, `expo-file-system`, `expo-sharing`, and `netinfo` autolink without plugins.
- **Permission gate:** picking from the library or camera prompts on first use through `expo-image-picker`'s own `requestMediaLibraryPermissionsAsync`/`requestCameraPermissionsAsync`, wrapped in the prompt-once-respect-prior-answer shape from `location-consent.ts`, with an open-Settings fallback modeled on `scan.tsx` when permanently denied.

## UI state map (mobile)

### Composer (`ChatPage.tsx` + `chat-composer.tsx`)

- **Attach button** (`Ionicons` `add` / `attach`) added to the composer row, left of the input, disabled while not authenticated. Tapping opens an **action sheet** (iOS `@expo/ui` or a bottom sheet) with: Photo or Video Library, Take Photo or Video (camera), File. Each launches the matching `expo-*` picker; results become drafts.
- **Draft chips** render in a horizontal scroll row above the input (mirror of `AttachmentChips`): 56px thumbnail (image/video via `expo-image` from the local asset uri) or a kind-icon tile, name + `formatBytes`, an upload progress ring, waiting-for-network state, terminal error with retry, and a remove control. A totals line ("3 files · 48 MB") when more than one.
- **Send gating** matches web: the morphing button's `sendMode` extends to "a ready draft exists"; send is blocked (with a toast-equivalent) while any draft is uploading or errored. Voice sends carry ready drafts too (the mobile `send` gains the attachments arg, so a dictated caption never drops the chips).

### Bubbles (`chat-event.tsx`)

One attachment block per attachment, stacked above the markdown caption inside the bubble:

| Kind | Render | States |
|---|---|---|
| image | `expo-image` from `api.authedUrl`, pre-sized from `width`/`height` (prevents list jump on load, the inverted FlatList is sensitive to it), tap opens the viewer | placeholder while loading; loaded; broken-load retry; removed (410) tile |
| video | a poster/first-frame tile with a play badge; tap opens the viewer's `expo-video` player | same removed/broken handling |
| audio | a compact inline player (`expo-audio` `useAudioPlayer`), play/pause + duration | native |
| file | a tile: kind icon, name, size, a download/share affordance | idle; fetching (determinate against metadata size); shared; failed |

The 410 removed tile and the broken-load retry (retry on the socket's reconnect edge, which `useAgentSocket` already exposes as `connected`) match web. An attachment-only message (`text === ""`) renders the blocks with no markdown body.

### Viewer (fullscreen `Modal`)

- Image: pinch-zoom and pan (`react-native-gesture-handler` `PinchGestureHandler`/`PanGestureHandler` + `reanimated`), double-tap toggles fit ↔ 2×, swipe-down-to-dismiss (the mobile idiom the web spec deferred), a caption (name · dimensions · size), and a share action.
- Video: `expo-video` `VideoView` with native controls, autoplay, best-effort resume position handed from the bubble.

### Download / save

`saveAttachment(agent, attachment)`: `controller.http.request(appChatAttachmentPath(agent, id, download=true))` streamed to an `expo-file-system` cache file (progress against the metadata size), then `expo-sharing.shareAsync(fileUri)`. A 410 surfaces "no longer available". The share sheet is the save target for Files, Photos, and everything else.

## Module map

### apps/core

No changes. The engine, reducer, model, and chat-stream seams already carry attachments.

### apps/mobile

| File | Contents |
|---|---|
| `package.json` + `app.config.ts` (modify) | add `expo-image`, `expo-image-picker`, `expo-document-picker`, `expo-file-system`, `expo-video`, `expo-sharing`, `@react-native-community/netinfo`; plugins + iOS Info.plist strings + Android media permissions |
| `src/attachments/connectivity.ts` (new) | a NetInfo-backed `Connectivity` for the engine deps |
| `src/attachments/pick.ts` (new) | the three pickers (library / camera / document) → a normalized `PickedAsset { uri, name, mime, size }`, permission-gated; `assetToBlob(asset)` via `fetch(uri).blob()` with an `expo-file-system` size/mime fallback |
| `src/attachments/use-attachment-drafts.ts` (new) | the drafts hook mirroring web's store: the `attachments` hold cell, the upload engine wiring, preview uris, orphan-safe mutation, `MAX_ATTACHMENT_BYTES` guard, old-agent 404 handling |
| `src/holds/agent-holds.ts` (modify) | add the `attachments: KeyedHoldStore<DraftAttachment[]>` cell |
| `src/chat/useAgentSocket.ts` (modify) | `send`/`retry` gain the `attachments?: ChatAttachment[]` arg (web parity); add the `retryableSends` reconnect replay |
| `src/agent/chat/AttachmentChips.tsx` (new) | the draft chips row |
| `src/agent/chat/AttachMenu.tsx` (new) | the attach action sheet |
| `src/agent/chat/AttachmentContent.tsx` (new) | the four typed bubble blocks |
| `src/agent/chat/AttachmentViewer.tsx` (new) | the fullscreen modal viewer (pinch-zoom image, expo-video) |
| `src/agent/chat/chat-event.tsx` (modify) | render attachment blocks above the markdown caption |
| `src/agent/ChatPage.tsx` (modify) | drafts wiring, send gating, attach button, viewer state |
| `src/lib/save-attachment.ts` (new) | the download-to-cache + share-sheet flow |
| `src/lib/authed-media-uri.ts` (new) | a small `api.authedUrl(appChatAttachmentPath(...))` resolver hook for media components (the mobile `useAuthedSrc` twin) |

## Invariants preserved

- No core changes; the wire is identical to web, so agent and gateway are untouched.
- No `min_supported` bump (additive chat-plane field).
- The managed-prebuild model holds: new native modules autolink, gated by the clean-prebuild verify and the native compiles.
- One owner per decision: the upload engine, draft reducer, kind derivation, and byte formatting stay in `@vesta/core`; mobile only supplies the native edges (pickers, Blob source, connectivity, media components).

## Deliberately deferred (recorded)

- **`expo-media-library` direct save-to-camera-roll** (the share sheet reaches Photos already; adds a permission for marginal gain).
- **Send-before-upload / bubble-embedded progress** (the same product fork deferred on web; needs partial-message stream states).
- **Server-side thumbnails** (v1 loads full images via `expo-image`, which caches).
- **Range-resumable downloads** (the protocol supports it; v1 refetches).
- **Client-side attachment compression** (down-scaling a huge camera capture before upload) — a natural mobile follow-up once the pipeline is proven.
