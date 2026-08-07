import { queryOptions } from "@tanstack/react-query";
import { fetchReleaseNotes } from "@vesta/core";

export function releaseNotesQueryOptions(version?: string) {
  return queryOptions({
    queryKey: ["release-notes", version ?? "unknown"],
    queryFn: async () => {
      const notes = await fetchReleaseNotes();
      if (notes === null) throw new Error("Could not load release notes.");
      return notes;
    },
    staleTime: 60 * 60 * 1000,
  });
}
