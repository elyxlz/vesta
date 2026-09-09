# Client feature parity report

Audit date: 2026-08-29  
Last updated: 2026-08-29 after merged PRs
[#2269](https://github.com/elyxlz/vesta/pull/2269) (`50a7e8c46`),
[#2271](https://github.com/elyxlz/vesta/pull/2271) (`fad46587a`),
[#2272](https://github.com/elyxlz/vesta/pull/2272) (`17eee74c1`),
[#2276](https://github.com/elyxlz/vesta/pull/2276) (`458d3d6ce`),
[#2277](https://github.com/elyxlz/vesta/pull/2277) (`a1ae01493`),
[#2278](https://github.com/elyxlz/vesta/pull/2278) (`0b00cc118`), and
[#2279](https://github.com/elyxlz/vesta/pull/2279) (`d6f2e6425`)  
Audit base: original working tree at `a783a810d` (including existing
uncommitted changes), with gateway-management and credential-storage statuses
reconciled against the follow-up changes above

## Scope and method

This is a source audit of the web SPA, Electron desktop wrapper, Expo iOS and
Android builds, shared `@vesta/core`, vestad's client-facing routes, native
bridges, release configuration, and the visual scenario catalogs. It compares
user-visible capabilities, not identical UI treatment.

The follow-up sweeps reconciled every protected vestad route with the web and
mobile API wrappers and visible screens, compared consumption of the shared
core, audited native permission/configuration gates, and cross-checked the 137
registered web visual scenarios and 150 mobile screenshot scenarios. This
caught several capabilities that route/navigation inspection alone did not
reveal.

The web and desktop columns are close by construction: desktop embeds the exact
web bundle and adds native bridge capabilities. Likewise, iOS and Android share
the Expo route and feature code; platform files mainly provide native-equivalent
controls.

Status legend:

- **Full**: the workflow is implemented with equivalent functional reach.
- **Partial**: the workflow exists but has a meaningful limit, missing state,
  or unsafe/incomplete edge.
- **Missing**: there is no usable client path.
- **N/A**: deliberately owned by another delivery/runtime model.

This was not a live end-to-end device smoke test. A Full status means the path
is present in the audited code, not that external credentials and services were
validated during this audit.

## Executive result

Full parity has not been reached.

The shared transport foundation is strong: sync/version negotiation, roster and
operation state, durable chat delivery, reconnect healing, dashboard
authentication, agent lifecycle actions, host access, backups, provider auth,
gateway updates, release notes, and device context are implemented across all
four clients.

The largest missing mobile workflows are native agent creation, the durable
gateway notification feed, generic service visibility, complete
model/context selection, complete voice configuration, paged notification
history, and gateway diagnostics. Production mobile cloud sign-in is also
disabled.

The largest missing web/desktop workflows are message actions and replies,
complete filesystem browsing, per-agent page visibility preferences,
mobile-style notification controls, and App Lock. Browser
credentials remain in `localStorage`. Neither web nor desktop has remote
delivery after the browser tab or desktop process has closed, and neither
reverse-geocodes a reported position into the human-readable place mobile
supplies.

Android has one major iOS parity failure: remote push registration is disabled
by configuration. The rest of the iOS/Android differences found in the source
are native presentation or haptic differences rather than missing workflows.

## Changes landed since the audit

PR [#2269](https://github.com/elyxlz/vesta/pull/2269) closed the mobile
connected-switching and desktop credential-storage gaps:

- iOS and Android now expose the saved-gateway switcher from connected
  Settings, retain the disconnected recents path, identify the current gateway,
  and prevent reconnecting to or deleting that active entry.
- Desktop now persists active and recent gateway credentials through Electron
  `safeStorage`, migrates both legacy plaintext files and renderer
  `localStorage`, writes atomically with restrictive file permissions, and
  fails closed on unavailable, `basic_text`, or unknown Linux backends.
- Credential persistence failures no longer turn a successful authentication
  into a reported connection failure. The live session remains usable and the
  failed persistence attempt is logged.
- The implementation and review follow-up passed web, desktop, mobile, CodeQL,
  cross-platform packaging, and `merge-gate-ci` before merge.

Merged corrective PR [#2271](https://github.com/elyxlz/vesta/pull/2271) closed
the remaining web/desktop workflow gap that the first report update incorrectly
left in the backlog:

- The disconnected connection screen now shows a Recent gateways action when
  saved gateways exist, matching the mobile entry point.
- The existing native-aware picker is reused for reconnect and forget flows;
  selecting a saved gateway restores it through the authentication provider
  before entering the connected app.
- Browser and Electron component tests plus a web/desktop visual scenario cover
  the disconnected entry point and restore behavior.
- All CI, CodeQL, cross-platform desktop package builds, and `merge-gate-ci`
  passed before merge.

PR [#2272](https://github.com/elyxlz/vesta/pull/2272) closed the mobile agent
rename gap:

- iOS and Android now expose the agent name from native Agent settings and
  provide the rename form on the existing General screen.
- The form previews vestad's canonical lowercase/hyphenated name, applies the
  reserved-name rules before submission, blocks lifecycle conflicts, reports
  request errors inline, and follows the canonical identity returned by the
  authenticated PATCH after the restart-backed rename.
- Endpoint and normalization tests cover the wire shape and gateway naming
  rules; the deterministic mobile catalog now includes a focused rename state.
- Mobile, visual, clean native-prebuild, repository guard, and
  `merge-gate-ci` checks passed before merge; the full local iOS visual run
  captured all 150 registered scenarios.

PR [#2276](https://github.com/elyxlz/vesta/pull/2276) moved the keyed
per-agent hold store (per agent, per gateway) from mobile into `@vesta/core`
on `zustand/vanilla`, with a `useHeld` subscription hook in
`@vesta/core/react`; mobile keeps its four cells as one module-level object
and drops its provider. PR
[#2278](https://github.com/elyxlz/vesta/pull/2278), stacked on it, closed the
web/desktop draft gap:

- The composer draft is a `KeyedHoldStore<string>` above the agent route, so
  navigating to Home, switching agent from the navbar, or the desktop panel
  and fullscreen chat mounting at once all show one surviving draft.

PR [#2279](https://github.com/elyxlz/vesta/pull/2279) closed the natural
pacing split: every client now has one per-agent switch (default on) on the
agent's settings page and no global default. Web's App Settings chat card is
gone; mobile dropped `naturalChatPacingDefault`.

PR [#2277](https://github.com/elyxlz/vesta/pull/2277) corrected AGENTS.md to
describe the desktop updater as manual (backlog item 25 remains a product
decision on which behavior is wanted; the documentation no longer claims the
automatic one).

## Detailed parity matrix

### Connection, fleet, and lifecycle

| Capability                                          | Web     | Desktop | iOS                   | Android               | Gap to close                                                                      |
| --------------------------------------------------- | ------- | ------- | --------------------- | --------------------- | --------------------------------------------------------------------------------- |
| Sync, version gate, reconnect, state holds          | Full    | Full    | Full                  | Full                  | None found                                                                        |
| Fleet roster, agent/activity/build/operation states | Full    | Full    | Full                  | Full                  | None found                                                                        |
| Self-hosted connection through public HTTPS         | Full    | Full    | Full                  | Full                  | None found                                                                        |
| Direct LAN/private-host connection                  | Full    | Full    | Missing               | Missing               | Mobile explicitly rejects HTTP, localhost, `.local`, and private IPs              |
| Managed Vesta account sign-in                       | Full    | Full    | Missing in production | Missing in production | Production mobile config enables it only for development builds                   |
| QR connection scanning                              | Missing | Missing | Full                  | Full                  | Add a scanner or explicitly treat this as a mobile-only acquisition affordance    |
| Universal/deep connect links                        | Partial | Partial | Full                  | Full                  | Web accepts links, but mobile has the complete native universal-link flow         |
| Saved gateway management                            | Full    | Full    | Full                  | Full                  | None found                                                                        |
| Agent creation                                      | Full    | Full    | Missing               | Missing               | Mobile only opens `/app/new` in a browser and passes no native session credential |
| Agent rename                                        | Full    | Full    | Full                  | Full                  | None found                                                                        |
| Start, stop, restart, delete                        | Full    | Full    | Full                  | Full                  | None found                                                                        |
| Gateway update/restart/channel/auto-update          | Full    | Full    | Full                  | Full                  | None found                                                                        |

### Agent experience

| Capability                                                  | Web     | Desktop | iOS     | Android | Gap to close                                                                                                               |
| ----------------------------------------------------------- | ------- | ------- | ------- | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| Dashboard service, private key, theme/auth bridge           | Full    | Full    | Full    | Full    | None found                                                                                                                 |
| Chat send, echo confirmation, retry, paging, reconnect heal | Full    | Full    | Full    | Full    | None found                                                                                                                 |
| Message actions                                             | Missing | Missing | Full    | Full    | Web/desktop lack Reply, Copy, Edit & Resend, Read Aloud, and Share                                                         |
| Reply composer                                              | Missing | Missing | Full    | Full    | Add quoted-reply state and rendering to web/desktop                                                                        |
| Draft retention across agent-page unmount/switch            | Full    | Full    | Full    | Full    | None found                                                                                                                 |
| Attachments                                                 | Missing | Missing | Missing | Missing | No transport/UI exists; web shows an inert add-attachment button                                                           |
| Live speech-to-text and automatic text-to-speech            | Full    | Full    | Full    | Full    | None found in the primary voice loop                                                                                       |
| Voice settings                                              | Full    | Full    | Partial | Partial | Mobile lacks usage, nested settings, voice previews/custom-choice handling, and desktop-style activation controls          |
| Natural chat pacing                                         | Full    | Full    | Full    | Full    | None found; one per-agent switch per client, no global default                                                             |
| Agent page visibility controls                              | Missing | Missing | Full    | Full    | Mobile can show/hide Chat, Dashboard, Notifications, and Logs                                                              |
| Generic registered-service visibility                       | Full    | Full    | Partial | Partial | Mobile shows a service count and knows the dashboard/voice services, but has no generic service list/public-private detail |
| Agent live logs                                             | Full    | Full    | Full    | Full    | None found                                                                                                                 |

### Provider and agent configuration

| Capability                                  | Web     | Desktop | iOS     | Android | Gap to close                                                                                                             |
| ------------------------------------------- | ------- | ------- | ------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| Provider auth, sign-out, account, usage     | Full    | Full    | Full    | Full    | None found                                                                                                               |
| Model selection                             | Full    | Full    | Partial | Partial | Mobile silently truncates the catalog to the first 12 models and has no search/expand path                               |
| Context-window selection                    | Full    | Full    | Partial | Partial | Mobile does not filter plan-restricted presets or use plan-specific defaults                                             |
| Interrupt/snooze/trash rule management      | Full    | Full    | Partial | Partial | Mobile can reorder/change/delete, but cycles into destructive Trash without web's confirmation                           |
| Per-agent notification history              | Full    | Full    | Partial | Partial | Mobile loads only the newest page, has no older-page action, and renders fetch failure as an empty list                  |
| Durable gateway-wide user-notification feed | Full    | Full    | Missing | Missing | Mobile listens to live deltas/push only; it has no `/notifications` archive, unseen indicator, or synced seen watermark  |
| Memory and constitution editing             | Full    | Full    | Full    | Full    | None found                                                                                                               |
| Skills Markdown browsing/editing            | Full    | Full    | Full    | Full    | None found                                                                                                               |
| Dream archive                               | Full    | Full    | Partial | Partial | Mobile's curated list caps at 30; all files remain reachable through Advanced view                                       |
| Complete agent filesystem browser           | Missing | Missing | Full    | Full    | Mobile Advanced view exposes every returned file; web/desktop restrict selection to curated paths                        |
| Host folder grants and write mode           | Full    | Full    | Full    | Full    | None found                                                                                                               |
| Backup create/list/restore/delete           | Full    | Full    | Full    | Full    | None found                                                                                                               |
| Per-agent automatic-backup policy           | Partial | Partial | Partial | Partial | Every client can write an enabled override, but none can clear it back to global inheritance or edit per-agent retention |

### App, gateway, privacy, and notifications

| Capability                                          | Web     | Desktop | iOS                 | Android | Gap to close                                                                                                 |
| --------------------------------------------------- | ------- | ------- | ------------------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| Light/dark/system appearance                        | Full    | Full    | Full                | Full    | None found                                                                                                   |
| Device registry and foreground presence             | Full    | Full    | Full                | Full    | None found                                                                                                   |
| Timezone and foreground coordinates                 | Full    | Full    | Full                | Full    | None found                                                                                                   |
| Human-readable location place                       | Missing | Missing | Full                | Full    | Mobile reverse-geocodes city/region/country; web/desktop always send `place: null`                           |
| Closed-app background location polling              | N/A     | N/A     | Full                | Full    | Native-only capability; no parity action required unless desktop background context is desired               |
| App Lock and protected app-switcher content         | Missing | Missing | Full                | Full    | Add desktop/web privacy policy if this is a cross-client requirement                                         |
| Device notification controls                        | Missing | Missing | Full                | Partial | Web/desktop auto-request once and expose no switches; Android controls exist but remote push cannot register |
| Local notifications while running but unfocused     | Full    | Full    | Full                | Full    | All clients present live `/sync` deltas locally and suppress them while another client is focused            |
| Remote delivery after the app/tab/process is closed | Missing | Missing | Full in code/config | Missing | Web/desktop have no background receiver; Android cannot pass its FCM configuration gate                      |
| Notification-tap navigation                         | Full    | Full    | Partial             | Partial | Remote mobile pushes can open an agent, but locally scheduled `/sync` notifications carry no navigation data |
| Gateway logs                                        | Full    | Full    | Missing             | Missing | Add a mobile gateway log viewer or link into a diagnostics bundle                                            |
| LAN/tunnel setup visibility                         | Full    | Full    | Missing             | Missing | Mobile fetches `/gateway/info` but does not render these fields                                              |
| Shareable app/device diagnostics                    | Partial | Partial | Full                | Full    | Web has gateway logs and error-copy UI, but no mobile-equivalent app/gateway/device summary                  |
| Release notes and auto-open after update            | Full    | Full    | Full                | Full    | None found                                                                                                   |
| Managed account/billing link                        | Full    | Full    | Full                | Full    | None found when the gateway reports managed                                                                  |

### Security and release behavior

| Capability                    | Web                        | Desktop         | iOS                 | Android          | Gap to close                                                                                                                                                                 |
| ----------------------------- | -------------------------- | --------------- | ------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Credential-at-rest protection | Partial                    | Full            | Full                | Full             | Browser still uses `localStorage`; desktop encrypts active and recent credentials with OS-backed `safeStorage` and rejects insecure Linux fallbacks; mobile uses SecureStore |
| Client-behind recovery        | N/A for gateway-served web | Full            | Partial             | Partial          | Desktop has an update/download/relaunch action; mobile only shows text and names stores that do not match current delivery                                                   |
| Desktop app self-update       | N/A                        | Full but manual | N/A                 | N/A              | Code and UI are manual despite architecture documentation describing automatic background download/apply-next-launch                                                         |
| Mobile release delivery       | N/A                        | N/A             | TestFlight internal | GitHub arm64 APK | App-behind copy says App Store/Google Play and offers no direct action                                                                                                       |

## Implementation backlog, sorted by estimated effort

The order below is shortest/easiest first. Estimates are engineering days for
one experienced contributor and include implementation plus focused unit and
component tests. They exclude product decisions, external credentials,
store/notarization review, broad device-lab QA, and release soak time. Items
overlap, so the ranges should not be summed into a project total.

Difficulty describes uncertainty and architectural reach, not merely elapsed
time:

- **Low**: contained client wiring around an existing API/model.
- **Medium**: several states/screens, shared logic, persistence, or streaming.
- **High**: native/security work, new cross-client behavior, or backend changes.
- **Very high**: a new delivery/transport subsystem with security implications.

| Order | Work item                                                                  | Apps                           |             Estimate | Difficulty  | Main scope or dependency                                                                             |
| ----: | -------------------------------------------------------------------------- | ------------------------------ | -------------------: | ----------- | ---------------------------------------------------------------------------------------------------- |
|     1 | Add routing data to live-sync local notifications                          | iOS, Android                   |            0.5–1 day | Low         | Include agent/gateway data when scheduling and cover tap routing                                     |
|     2 | Confirm before cycling a notification rule into Trash                      | iOS, Android                   |            0.5–1 day | Low         | Reuse the existing destructive-confirm pattern                                                       |
|     3 | Remove or paginate the 30-item curated dream cap                           | iOS, Android                   |            0.5–1 day | Low         | Advanced view already makes every file reachable                                                     |
|     4 | Display LAN and tunnel status already returned by `/gateway/info`          | iOS, Android                   |            0.5–1 day | Low         | Presentation only; the query already fetches the fields                                              |
|     5 | Expose the independent app-switcher privacy toggle                         | iOS, Android                   |            0.5–1 day | Low         | Native implementation exists; restore persistence and Settings UI                                    |
|     6 | Add generic registered-service details                                     | iOS, Android                   |             1–2 days | Low         | Render names plus public/private state from the roster                                               |
|     8 | Make client-behind recovery actionable and correct its distribution copy   | iOS, Android                   |             1–2 days | Medium      | Needs an agreed TestFlight action and GitHub APK URL                                                 |
|     9 | Reset per-agent backup settings to global inheritance                      | All clients                    |             1–2 days | Medium      | Add the existing DELETE endpoint to both client helpers and UIs                                      |
|    10 | Paginate per-agent notification history and show fetch errors              | iOS, Android                   |             1–3 days | Medium      | Cursor/load-older state; web provides a reference implementation                                     |
|    11 | Configure and validate Android FCM push                                    | Android                        | 1–3 days engineering | Medium      | Calendar time depends on Firebase/EAS credentials and real-device validation                         |
|    12 | Replace the 12-model alert with a complete searchable picker               | iOS, Android                   |             2–3 days | Medium      | Search, loading/error states, and large-list behavior                                                |
|    13 | Share and apply plan-aware context-window rules                            | iOS, Android                   |             2–3 days | Medium      | Move web-only filtering/default logic into shared code                                               |
|    14 | Add explicit local-notification preferences                                | Web, Desktop                   |             2–3 days | Medium      | Permission retry, previews, reply kinds, and clear separation from server push routing               |
|    16 | Add optional page visibility                                               | Web, Desktop                   |             1–3 days | Medium      | First decide whether this remains a device-local preference                                          |
|    17 | Add an Advanced complete-filesystem view                                   | Web, Desktop                   |             2–4 days | Medium      | Reuse the existing tree/file APIs with safe navigation and editing states                            |
|    18 | Add a shareable diagnostics summary                                        | Web, Desktop                   |             2–4 days | Medium      | App/gateway/device summary plus safe copy/share redaction                                            |
|    19 | Enable production managed-account sign-in                                  | iOS, Android                   | 2–5 days engineering | Medium      | Externally blocked until cloud signup/review policy is ready                                         |
|    20 | Add global automatic-backup cadence and retention UI                       | All clients                    |             3–5 days | Medium      | Includes global enabled state and per-agent retention editing                                        |
|    21 | Add per-kind gateway push-routing UI                                       | All clients                    |             3–5 days | Medium      | Extend both settings wire types and keep it distinct from device-local preferences                   |
|    22 | Surface fleet-wide Start all and aggregate backups                         | All clients                    |             3–5 days | Medium      | Existing endpoints; needs fleet progress/error UX                                                    |
|    23 | Add mobile gateway log streaming                                           | iOS, Android                   |             3–5 days | Medium      | Port authenticated SSE lifecycle, reconnect, buffering, and export behavior                          |
|    24 | Add QR connection scanning                                                 | Web, Desktop                   |             3–5 days | Medium      | Camera permission, scanner UI, and secure connect-link parsing                                       |
|    25 | Align desktop self-update behavior with the automatic-update specification | Desktop                        |             3–5 days | Medium      | Product decision first: change code to background download or change the specification               |
|    26 | Broaden packaged binary architectures                                      | Desktop, Android               |             3–7 days | Medium–High | macOS x64, Windows arm64, and a universal/multi-architecture Android artifact plus release QA        |
|    27 | Add self-hosted Vesta Cloud pair/unpair UI                                 | All clients                    |             4–7 days | Medium–High | Device-code polling, expiry/resume, linked state, confirmation, and error recovery                   |
|    28 | Add native/deep connect-link handling                                      | Desktop, Web where installable |             4–7 days | High        | OS protocol registration, single-instance forwarding, browser/PWA scope                              |
|    29 | Reverse-geocode web/desktop locations into named places                    | Web, Desktop                   |             4–7 days | High        | Requires a privacy/network policy or three native OS implementations                                 |
|    30 | Add the durable gateway-wide notification feed                             | iOS, Android                   |             4–7 days | High        | Paging, live joins, unseen state, and the shared seen watermark                                      |
|    31 | Bring mobile voice settings to schema parity                               | iOS, Android                   |             4–8 days | High        | Usage, recursive config, previews, custom choices, and portable activation settings                  |
|    32 | Add Reply, Copy, Edit & Resend, Read Aloud, and Share                      | Web, Desktop                   |             5–8 days | High        | Reply state/rendering and per-message TTS are the long poles                                         |
|    33 | Add iPad and landscape support                                             | iOS, Android                   |            7–15 days | High        | Responsive navigation/composer/sheets plus a broader device QA matrix                                |
|    34 | Add App Lock and protected previews                                        | Web, Desktop                   |            7–15 days | High        | Desktop can use native auth; browser semantics require a separate security design                    |
|    35 | Redesign browser credential persistence                                    | Web                            |            7–15 days | High        | Avoiding `localStorage` likely requires an HTTP-only session/auth contract change                    |
|    36 | Build native mobile agent creation                                         | iOS, Android                   |            8–15 days | High        | Name, auth, model/context, personality, build progress, retries, and completion                      |
|    37 | Support trusted direct-LAN mobile connections                              | iOS, Android                   |           10–20 days | Very high   | Transport trust, certificate/onboarding policy, ATS/network-security config, and threat review       |
|    38 | Deliver notifications after web/desktop is fully closed                    | Web, Desktop                   |           15–30 days | Very high   | Service worker/Web Push and desktop background receiver need new registration/backend delivery paths |
|    39 | Implement chat attachments end to end                                      | All clients                    |           15–30 days | Very high   | Upload/storage protocol, limits, auth, persistence, rendering, retry, cleanup, and model ingestion   |

The quickest useful batch is items 1–13: mostly existing endpoints or models,
roughly one to three days each, with Android FCM the only externally dependent
item. Items 27 onward should receive a short design decision before
implementation because their security or cross-platform choices can change the
estimate materially.

## Platform-specific differences that should not block parity

- Electron owns window chrome, PKCE loopback, OS geolocation, external-link
  handling, and desktop package updates.
- Mobile owns QR capture, biometric/device authentication, app-switcher/screen
  protection, background location, native push, sharing sheets, native message
  menus, keyboard behavior, and haptics.
- iOS uses a native context-menu preview and additional voice/transcript
  haptics; Android uses its native menu fallback and different sheet/header
  chrome. The available actions are the same.
- A browser bundle served by its gateway cannot become independently
  `app_behind`, so it does not need a client binary updater.
- Current packaging is narrower than the product labels imply: desktop's macOS
  packages are arm64-only and its Windows package is x64-only, iOS explicitly
  disables tablet support, and the directly distributed Android APK is
  arm64-only. These are delivery constraints, not workflow differences in the
  installed apps.

The target should be workflow parity, security parity, and equivalent recovery
paths, not identical native presentation.

## Evidence for the material gaps

- Mobile creation is an explicit browser handoff:
  `apps/mobile/app/new-agent.tsx:28`; web owns the real create/provision
  pipeline in `apps/web/src/components/NewAgent/index.tsx:96`.
- Generic service details exist only in the web surfaces:
  `apps/web/src/components/AgentServices/index.tsx:8`.
- Mobile truncates models and offers every context preset directly:
  `apps/mobile/src/agent/settings/ProviderSection.tsx:188-207`; web's plan
  filter lives in `apps/web/src/components/ProviderPicker/context-plan.ts:35-59`.
- Mobile per-agent notification history performs one uncursored query:
  `apps/mobile/src/agent/NotificationsPage.tsx:140-143`; web carries a cursor
  and Load older at
  `apps/web/src/components/AgentSettings/NotificationsCard/index.tsx:35-166`.
- The durable notification feed is mounted by web through
  `useNotificationFeed` in
  `apps/web/src/providers/NotificationsPillProvider/index.tsx:46`; mobile only
  subscribes to live deltas in
  `apps/mobile/src/notifications/UserNotifications.tsx:22`.
- Web voice settings fetch usage and recursively render nested configuration:
  `apps/web/src/components/AgentSettings/VoiceSection/index.tsx:26-80` and
  `:299-357`; mobile maps only the top-level settings array in
  `apps/mobile/src/agent/settings/VoiceSection.tsx:135-143`.
- Mobile exposes the complete tree through Advanced view:
  `apps/mobile/src/agent/settings/FilesSection.tsx:77-97`; web gates paths with
  `isSimpleAllowed` in
  `apps/web/src/components/AgentSettings/FilesTab/paths.ts:6-11`.
- The mobile parser rejects direct local connections in
  `apps/mobile/src/api/connection-link.ts:52-65`; web accepts local links in
  `apps/web/src/lib/connection.test.ts:24-40`.
- Production mobile cloud login is disabled by
  `apps/mobile/app.config.ts:153-159`.
- Android push requires a `googleServicesFile` at runtime in
  `apps/mobile/src/notifications/PushCoordinator.tsx:70-75`, but the Android
  app config does not set one.
- Live-sync mobile notifications schedule only title/body in
  `apps/mobile/src/notifications/UserNotifications.tsx:22-29`, while tap
  routing requires `data.agent` in
  `apps/mobile/src/notifications/notification-routing.ts:8-20`.
- Mobile reverse-geocodes each fix in
  `apps/mobile/src/device-context/device-context.ts:105-124`; web/desktop
  explicitly emit `place: null` in `apps/web/src/lib/device-context.ts:168-183`.
- Mobile's app-behind copy hard-codes App Store/Google Play in
  `apps/mobile/src/controller/AppBehindScreen.tsx:11-25`; current delivery is
  documented as TestFlight/GitHub APK in `README.md:61-62`.
- Desktop update behavior is explicitly manual in
  `apps/desktop/src/updater.ts:14-31`.
- Mobile message actions are defined in
  `apps/mobile/src/agent/chat/chat-event.tsx:49-82`; web bubbles only render
  content/retry in `apps/web/src/components/Chat/ChatBubble/index.tsx`.
- The web attachment control has no handler:
  `apps/web/src/components/Chat/ChatComposer/index.tsx:269-277`.
- Gateway backup and push settings already exist server-side in
  `vestad/src/serve.rs:2121-2135` and `:2205-2300`, but both client types and
  screens omit push routing; their settings types include `auto_backup`, but
  their mutation helpers deliberately accept only update channel/automatic
  gateway updates.
- The per-agent backup DELETE that restores global inheritance is implemented
  at `vestad/src/serve.rs:2406-2414`; both client helpers expose only GET and an
  enabled-only PUT.
- App-facing Vesta Cloud pairing routes are registered at
  `vestad/src/serve.rs:2851-2856`, with no matching call in either client.
- The disconnected web/desktop entry point reads the native-aware recents store
  in `apps/web/src/components/Connect/index.tsx`; the shared reconnect/forget UI
  is in `apps/web/src/components/SwitchGatewayDialog/index.tsx`, and restoring a
  disconnected session is owned by
  `apps/web/src/providers/AuthProvider/index.tsx`.
- Desktop active and recent connection records are encrypted through Electron
  `safeStorage` in `apps/desktop/src/store.ts`; browser storage remains the
  `localStorage` implementation in `apps/web/src/lib/native/browser.ts`.
- Package architecture constraints are declared in
  `apps/desktop/electron-builder.yml:14-32`,
  `apps/mobile/app.config.ts:48-61`, and `apps/mobile/eas.json:33-39`.

## Corrections made by the follow-up sweeps

The initial audit overstated several areas. This report corrects them:

- Per-agent notification history is not Full on mobile; it is newest-page only.
- Voice is not fully configured on mobile; the primary voice loop is Full, but
  settings and usage are Partial.
- Files are not simply Full everywhere; mobile has the broader filesystem
  browser, while web has the richer uncapped dream browser.
- Direct LAN connection is an additional mobile gap.
- Client-behind recovery copy is wrong for both current mobile delivery paths,
  not only Android.
- Global backup policy and per-kind push policy are backend capabilities with
  no complete client UI.
- Browser and desktop notifications are not remote delivery: they require the
  client process to remain connected.
- Web/desktop report coordinates but not mobile's city/region/country place.
- Local mobile notifications do not carry the data their tap router requires.
- Per-agent automatic backup is Partial everywhere because override inheritance
  and retention cannot be managed.
- Vesta Cloud pairing/unpairing is not surfaced by any client.
- Saved gateway management is now Full after adding the connected mobile
  switcher, encrypted desktop persistence, and the initially missed
  disconnected web/desktop entry point.
- Draft retention and natural pacing are now Full on every client
  ([#2278](https://github.com/elyxlz/vesta/pull/2278),
  [#2279](https://github.com/elyxlz/vesta/pull/2279)); the backlog numbering
  above keeps its original order with the closed items removed.
