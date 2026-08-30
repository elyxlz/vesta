// Pure sizing and throttling math for attachment bubble media, kept out of the component so it
// tests in plain node.

import type { ChatAttachment } from "@vesta/core";

// Bubble media is capped to a phone-photo footprint; pre-sizing from the metadata dimensions
// keeps the inverted chat list stable while bytes load.
export const MEDIA_MAX_WIDTH = 260;
export const MEDIA_MAX_HEIGHT = 340;
const MEDIA_FALLBACK = { width: 220, height: 150 };

export function mediaSize(attachment: ChatAttachment): {
  width: number;
  height: number;
} {
  if (!attachment.width || !attachment.height) return MEDIA_FALLBACK;
  const scale = Math.min(
    MEDIA_MAX_WIDTH / attachment.width,
    MEDIA_MAX_HEIGHT / attachment.height,
    1,
  );
  return {
    width: Math.round(attachment.width * scale),
    height: Math.round(attachment.height * scale),
  };
}

// Progress arrives per network chunk; only meaningful movement should commit a render.
export function progressStep(totalBytes: number): number {
  return Math.max(totalBytes / 100, 256 * 1024);
}

export function throttledProgress(
  previous: number,
  bytes: number,
  totalBytes: number,
): number {
  return bytes - previous >= progressStep(totalBytes) || bytes >= totalBytes
    ? bytes
    : previous;
}
