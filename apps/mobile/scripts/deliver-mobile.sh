#!/usr/bin/env bash
# Build a Vesta mobile app on the machine this runs on, with no EAS cloud build,
# and optionally submit the iOS build to TestFlight. The developer Mac and the
# GitHub-hosted runner run this exact script with the same flags: signing comes
# from EAS remote credentials via EXPO_TOKEN, so only the host machine differs.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: deliver-mobile.sh --platform ios|android --profile <name> [--changelog <text>] [--submit]

Requires EXPO_TOKEN in the environment (EAS remote credentials, and submit).
Prints the built artifact's absolute path on stdout on success.
iOS builds need macOS + Xcode; Android builds need a JDK + the Android SDK.
EOF
  exit 1
}

PLATFORM=""
PROFILE=""
CHANGELOG=""
SUBMIT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --platform) PLATFORM="${2:-}"; shift 2 ;;
    --profile) PROFILE="${2:-}"; shift 2 ;;
    --changelog) CHANGELOG="${2:-}"; shift 2 ;;
    --submit) SUBMIT=1; shift ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done

[ -n "$PLATFORM" ] && [ -n "$PROFILE" ] || usage
[ -n "${EXPO_TOKEN:-}" ] || { echo "EXPO_TOKEN is required" >&2; exit 1; }
case "$PLATFORM" in
  ios | android) ;;
  *) echo "platform must be ios or android" >&2; exit 1 ;;
esac

script_dir=$(cd "$(dirname "$0")" && pwd)
app_dir=$(cd "$script_dir/.." && pwd)
cd "$app_dir"

extension=$([ "$PLATFORM" = ios ] && echo ipa || echo apk)
output="$app_dir/build/vesta-$PLATFORM.$extension"
mkdir -p "$app_dir/build"

# Build/submit chatter goes to stderr so stdout carries only the artifact path,
# which lets a caller capture it with `path=$(deliver-mobile.sh ...)`.
echo "Building $PLATFORM ($PROFILE) on this machine..." >&2
npx --yes eas-cli@latest build \
  --local \
  --platform "$PLATFORM" \
  --profile "$PROFILE" \
  --non-interactive \
  --output "$output" >&2

if [ "$PLATFORM" = ios ] && [ "$SUBMIT" = 1 ]; then
  echo "Submitting the iOS build to TestFlight..." >&2
  submit_args=(--platform ios --path "$output" --profile "$PROFILE" --non-interactive)
  [ -n "$CHANGELOG" ] && submit_args+=(--what-to-test "$CHANGELOG")
  npx --yes eas-cli@latest submit "${submit_args[@]}" >&2
fi

echo "$output"
