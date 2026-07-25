#!/usr/bin/env bash
# Create and boot a pinned iOS simulator for visual review captures, then
# freeze the mutable chrome (locale, appearance, status bar) so screenshots
# are comparable across runs. Exports SIMULATOR_UDID through GITHUB_ENV.
set -euo pipefail

DEVICE_NAME="vesta-visual-review"
DEVICE_TYPE_CANDIDATES=(
  "iPhone 16 Pro"
  "iPhone 17 Pro"
  "iPhone 16"
  "iPhone 15 Pro"
)

udid=""
for device_type in "${DEVICE_TYPE_CANDIDATES[@]}"; do
  # No runtime argument: simctl picks the newest runtime for the device type.
  if udid=$(xcrun simctl create "$DEVICE_NAME" "$device_type" 2>/dev/null); then
    echo "created '$device_type' simulator $udid" >&2
    break
  fi
  udid=""
done

if [ -z "$udid" ]; then
  echo "error: none of the candidate device types are available on this runner" >&2
  xcrun simctl list devicetypes >&2
  exit 1
fi

xcrun simctl boot "$udid"
xcrun simctl bootstatus "$udid" -b

xcrun simctl spawn "$udid" defaults write "Apple Global Domain" AppleLocale -string en_US
xcrun simctl spawn "$udid" defaults write "Apple Global Domain" AppleLanguages -array en-US
xcrun simctl ui "$udid" appearance light
xcrun simctl status_bar "$udid" override \
  --time "9:41" \
  --dataNetwork wifi --wifiMode active --wifiBars 3 \
  --cellularMode notSupported \
  --batteryState charged --batteryLevel 100

echo "SIMULATOR_UDID=$udid" >>"${GITHUB_ENV:?GITHUB_ENV is not set}"
