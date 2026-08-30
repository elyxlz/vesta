import { Asset } from "expo-asset";
import photoModule from "./assets/attachment-photo.png";
import videoModule from "./assets/attachment-video.mp4";
import audioModule from "./assets/attachment-audio.wav";

// Visual stand-in for the authed media uri hook: attachment paths resolve to bundled fixture
// bytes instead of a token-stamped gateway URL, keyed by the attachment id the transcript
// fixture uses. Degraded ids resolve to a dead file uri, so the production error/removed phases
// (image onError, then the HEAD probe against the session fixture) run exactly as shipped.

const ASSET_BY_ID = new Map<string, number>([
  ["att-photo", photoModule],
  ["att-video", videoModule],
  ["att-audio", audioModule],
]);

const DEAD_URI = "file:///visual-missing-attachment";

export function useAuthedMediaUri(
  _api: unknown,
  path: string | null,
): string | null {
  if (path === null) return null;
  const id = path.split("/attachments/")[1]?.split("?")[0] ?? "";
  const moduleId = ASSET_BY_ID.get(id);
  if (moduleId === undefined) return DEAD_URI;
  return Asset.fromModule(moduleId).uri;
}
