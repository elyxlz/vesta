#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE="$ROOT/apps/mobile"
mkdir -p "$MOBILE/.expo"
BACKUP="$(mktemp -d "$MOBILE/.expo/prebuild-check.XXXXXX")"
HAD_IOS=0
HAD_ANDROID=0
CLEANED=0

cleanup() {
  if [ "$CLEANED" = "1" ]; then
    return
  fi
  CLEANED=1
  trap - EXIT INT TERM
  rm -rf "$MOBILE/ios" "$MOBILE/android"
  if [ "$HAD_IOS" = "1" ] && [ -d "$BACKUP/ios" ]; then
    mv "$BACKUP/ios" "$MOBILE/ios"
  fi
  if [ "$HAD_ANDROID" = "1" ] && [ -d "$BACKUP/android" ]; then
    mv "$BACKUP/android" "$MOBILE/android"
  fi
  rm -rf "$BACKUP"
}
trap cleanup EXIT INT TERM

if [ -d "$MOBILE/ios" ]; then
  HAD_IOS=1
  mv "$MOBILE/ios" "$BACKUP/ios"
fi
if [ -d "$MOBILE/android" ]; then
  HAD_ANDROID=1
  mv "$MOBILE/android" "$BACKUP/android"
fi

(
  cd "$MOBILE"
  CI=1 npx expo prebuild --clean --no-install --platform all
)

STORYBOARD="$MOBILE/ios/Vesta/SplashScreen.storyboard"
INFO_PLIST="$MOBILE/ios/Vesta/Info.plist"
EXPO_PLIST="$MOBILE/ios/Vesta/Supporting/Expo.plist"
ENTITLEMENTS_PLIST="$MOBILE/ios/Vesta/Vesta.entitlements"
ANDROID_MANIFEST="$MOBILE/android/app/src/main/AndroidManifest.xml"
ANDROID_SPLASH="$MOBILE/android/app/src/main/res/drawable/splashscreen_logo.xml"

for generated in "$STORYBOARD" "$INFO_PLIST" "$EXPO_PLIST" "$ENTITLEMENTS_PLIST" "$ANDROID_MANIFEST" "$ANDROID_SPLASH"; do
  if [ ! -f "$generated" ]; then
    echo "error: Expo prebuild did not generate ${generated#"$ROOT/"}" >&2
    exit 1
  fi
done

if grep -Eq 'imageView|SplashScreenLogo' "$STORYBOARD"; then
  echo "error: generated iOS launch storyboard is not blank" >&2
  exit 1
fi

if ! grep -q '@android:color/transparent' "$ANDROID_SPLASH"; then
  echo "error: generated Android launch drawable is not blank" >&2
  exit 1
fi

python3 - "$INFO_PLIST" "$EXPO_PLIST" "$ENTITLEMENTS_PLIST" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as handle:
    info = plistlib.load(handle)
background_modes = info.get("UIBackgroundModes", [])
if "remote-notification" in background_modes:
    raise SystemExit("error: generated Info.plist enables unused remote-notification background mode")

with open(sys.argv[2], "rb") as handle:
    expo = plistlib.load(handle)
if not str(expo.get("EXUpdatesURL", "")).startswith("https://u.expo.dev/"):
    raise SystemExit("error: generated Expo.plist is missing the EAS Update URL")
if not expo.get("EXUpdatesRuntimeVersion"):
    raise SystemExit("error: generated Expo.plist is missing the runtime version")

with open(sys.argv[3], "rb") as handle:
    entitlements = plistlib.load(handle)
if entitlements.get("aps-environment") != "development":
    raise SystemExit("error: generated iOS app is missing the APNs development entitlement")
PY

echo "mobile clean prebuild verified"
