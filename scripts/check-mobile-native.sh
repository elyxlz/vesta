#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE="$ROOT/apps/mobile"
PLATFORM="${1:-}"

if [ "$PLATFORM" != "ios" ] && [ "$PLATFORM" != "android" ]; then
  echo "usage: $0 <ios|android>" >&2
  exit 2
fi

mkdir -p "$MOBILE/.expo"
BACKUP="$(mktemp -d "$MOBILE/.expo/native-check.XXXXXX")"
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

cd "$MOBILE"

if [ "$PLATFORM" = "ios" ]; then
  # The simulator build validates generated Xcode configuration and every
  # custom Swift module without requiring signing credentials or APNs access.
  CI=1 VESTA_LOCAL_IOS_NO_PUSH=1 npx expo prebuild --clean --platform ios
  HOST_ARCH="$(uname -m)"
  xcodebuild \
    -quiet \
    -workspace ios/Vesta.xcworkspace \
    -scheme Vesta \
    -configuration Debug \
    -sdk iphonesimulator \
    -destination "generic/platform=iOS Simulator" \
    ARCHS="$HOST_ARCH" \
    ONLY_ACTIVE_ARCH=YES \
    CODE_SIGNING_ALLOWED=NO \
    build
else
  CI=1 npx expo prebuild --clean --platform android
  (
    cd android
    # One emulator ABI is enough to compile the generated project and native
    # modules here. Production EAS builds still create the complete Android
    # artifact; avoiding four local ABIs keeps the PR gate practical.
    ./gradlew :app:assembleDebug \
      -PreactNativeArchitectures=x86_64 \
      --no-daemon
  )
fi

echo "mobile $PLATFORM native compile verified"
