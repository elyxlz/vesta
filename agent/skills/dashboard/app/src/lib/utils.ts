import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

// A resource's load failure as display text, or null while it has none.
export function loadFailure(error: unknown, fallback: string): string | null {
  return error === null ? null : errorMessage(error, fallback);
}
