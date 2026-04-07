import type { AuthStartResult } from "@/api";

export type Step = "platform" | "name" | "creating" | "auth" | "done";

export const CREATING_MESSAGES = [
  "setting things up...",
  "preparing email & calendar access...",
  "loading browser & research tools...",
  "setting up reminders & tasks...",
  "almost there...",
];

export function normalizeName(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}
