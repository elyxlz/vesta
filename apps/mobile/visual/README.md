# Mobile visual review

Per-PR screenshot capture for the iOS app (issue #1463). The `Mobile Visual Review` workflow (`.github/workflows/mobile-visual.yml`) builds the simulator app from the PR's code, boots a pinned simulator, runs the Maestro screen catalog in `flows/`, and uploads a `mobile-visual-screenshots` artifact containing every named screenshot plus `contact-sheet.png`, a one-glance grid of all pages. A trusted follow-up workflow (`mobile-visual-comment.yml`) keeps one sticky PR comment pointing at the latest run's artifact.

## Screen catalog

| Screenshot | Page | How it is reached |
| --- | --- | --- |
| `01-connect` | Disconnected landing screen | Clean-install launch |
| `02-connect-link` | Gateway link sheet | Tap "Self-hosting? Connect your gateway" |
| `03-recent-gateways` | Recent gateways sheet (empty state) | Deep link `vesta://recent-gateways` |

The current catalog covers the disconnected surfaces: they render deterministically on a clean install with no gateway, credentials, or user data. Connected surfaces (agent home, chat, settings, logs) need a fixture gateway feeding stable data and are tracked as follow-up work on issue #1463.

## Registering a new page

1. Add a flow file to `flows/` named `NN-page-name.yaml`. The numeric prefix orders the contact sheet; pick the next free number.
2. Start from a known state: `launchApp` with `clearState: true` wipes app data so every run begins identically.
3. Navigate deterministically: tap stable visible text or accessibility labels, or use `openLink` with the `vesta://` scheme for routes that have no tap path. Maestro selector strings are regular expressions, so escape or wildcard characters like `?`.
4. Settle before capturing: `extendedWaitUntil` on a stable text anchor unique to the page, then `waitForAnimationToEnd`.
5. Capture with `takeScreenshot: ${SCREENSHOT_DIR}/NN-page-name`. The workflow passes `SCREENSHOT_DIR`; the name must match the flow's prefix so the sheet stays ordered.

Determinism rules for every flow: no live gateways or credentials, no dependence on wall-clock time or network responses, anchors on copy that only changes when the page itself changes. The simulator is pinned by `boot-simulator.sh` (device type, newest installed runtime, `en_US` locale, light appearance, 9:41 status bar) and the workflow pins `TZ=UTC` and the Maestro version.

## Running locally

```bash
cd apps/mobile
CI=1 VESTA_LOCAL_IOS_NO_PUSH=1 npx expo prebuild --clean --platform ios
xcodebuild -workspace ios/Vesta.xcworkspace -scheme Vesta -configuration Release \
  -sdk iphonesimulator -destination "generic/platform=iOS Simulator" \
  -derivedDataPath build ARCHS="$(uname -m)" ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=NO build
GITHUB_ENV=/tmp/sim-env bash visual/boot-simulator.sh && source /tmp/sim-env
xcrun simctl install "$SIMULATOR_UDID" build/Build/Products/Release-iphonesimulator/Vesta.app
mkdir -p /tmp/visual-shots
maestro --device "$SIMULATOR_UDID" test -e SCREENSHOT_DIR=/tmp/visual-shots visual/flows
```
