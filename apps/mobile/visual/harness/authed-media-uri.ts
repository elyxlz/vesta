import { useAssets } from "expo-asset";
import photoModule from "./assets/attachment-photo.png";
import videoModule from "./assets/attachment-video.mp4";
import audioModule from "./assets/attachment-audio.wav";

// Visual stand-in for the authed media uri hook: attachment paths resolve to bundled fixture
// bytes instead of a token-stamped gateway URL, keyed by the attachment id the transcript
// fixture uses. Degraded ids resolve to a dead file uri, so the production error/removed phases
// (image onError, then the HEAD probe against the session fixture) run exactly as shipped.

const MODULES = [photoModule, videoModule, audioModule];
const ASSET_INDEX = new Map([
  ["att-photo", 0],
  ["att-video", 1],
  ["att-audio", 2],
]);

const DEAD_URI = "file:///visual-missing-attachment";

export function useAuthedMediaUri(
  _api: unknown,
  path: string | null,
): string | null {
  // Android release assets start as file:///android_res/... pseudo-paths.
  // Expo extracts them to real local files; native image/video readers cannot
  // consume the pseudo-path as a regular file. iOS uses the same asset lifecycle.
  const [assets, error] = useAssets(MODULES);
  if (path === null) return null;
  const id = path.split("/attachments/")[1]?.split("?")[0] ?? "";
  const index = ASSET_INDEX.get(id);
  if (index === undefined || error) return DEAD_URI;
  const asset = assets?.[index];
  return asset ? (asset.localUri ?? asset.uri) : null;
}
