import * as Location from "expo-location";

// The OS side of location sharing, run when the phone's Privacy toggle turns it on. Asks for the
// when-in-use grant, then the always-on one that lets the closed-app poll read a fix; the OS asks
// in its own way (iOS a second prompt, Android a settings screen). Resolves to whether sharing can
// turn on: the when-in-use grant is enough for the foreground, so a declined always-on still
// turns it on.
export async function requestLocationSharing(): Promise<boolean> {
  const foreground = await Location.requestForegroundPermissionsAsync();
  if (!foreground.granted) return false;
  await Location.requestBackgroundPermissionsAsync();
  return true;
}

// A phone that has never been asked is asked on its first shared foreground read, so the
// default-on preference shares location out of the box; a phone that already answered (granted or
// refused) keeps its answer, with the OS Settings as the place to change it. Never called from the
// background poll, which cannot raise a prompt.
export async function requestLocationIfUndecided(): Promise<void> {
  const permission = await Location.getForegroundPermissionsAsync().catch(
    () => null,
  );
  if (permission?.status !== Location.PermissionStatus.UNDETERMINED) return;
  await requestLocationSharing();
}
