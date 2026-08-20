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
