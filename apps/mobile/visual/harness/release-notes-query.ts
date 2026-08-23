import { queryOptions } from "@tanstack/react-query";
import type { ReleaseNote } from "@vesta/core";
import { visualDelay, visualSwitch } from "./launch-query";

const mode = visualSwitch("visualReleaseNotes");
const notes: ReleaseNote[] = [
  {
    version: "0.2.0-beta.3",
    date: "2026-07-27T12:00:00.000Z",
    prerelease: true,
    message:
      "Beta: the redesigned home carousel and a first pass at agent state badges.",
    url: "https://github.com/elyxlz/vesta/releases/tag/v0.2.0-beta.3",
  },
  {
    version: "0.2.0",
    date: "2026-07-29T12:00:00.000Z",
    prerelease: false,
    message:
      "A faster mobile experience with native sheets, clearer connection states, and more reliable agent updates.",
    url: "https://github.com/elyxlz/vesta/releases/tag/v0.2.0",
  },
  {
    version: "0.1.183",
    date: "2026-07-22T12:00:00.000Z",
    prerelease: false,
    message:
      "Improved gateway recovery, notification controls, and the first version of the mobile visual QA catalog.",
    url: "https://github.com/elyxlz/vesta/releases/tag/v0.1.183",
  },
];

export function releaseNotesQueryOptions(version?: string) {
  return queryOptions({
    queryKey: ["visual-release-notes", version ?? "unknown", mode ?? "loaded"],
    queryFn: async () => {
      await visualDelay();
      if (mode === "error") throw new Error("Visual release notes failure");
      return mode === "empty" ? [] : notes;
    },
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
