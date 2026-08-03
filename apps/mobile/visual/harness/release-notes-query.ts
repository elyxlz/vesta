import * as Linking from "expo-linking";
import { queryOptions } from "@tanstack/react-query";
import type { ReleaseNote } from "@vesta/core";

const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;
const mode = query?.visualReleaseNotes;
const notes: ReleaseNote[] = [
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
      if (mode === "error") throw new Error("Visual release notes failure");
      return mode === "empty" ? [] : notes;
    },
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
