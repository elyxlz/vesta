// Splits plain message text (user bubbles render raw text, not markdown) into segments so URLs
// become tappable spans. Rendering stays plain <Text> nodes built from these segments, never
// parsed HTML, so message content cannot inject markup.
export interface MessageSegment {
  text: string;
  url: string | null;
}

const URL_RE = /https?:\/\/[^\s]+/gi;
// Punctuation that reads as sentence trailing rather than part of the URL when it ends one.
const TRAILING_PUNCTUATION_RE = /[.,;:!?)\]}'"]+$/;

export function messageSegments(text: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(URL_RE)) {
    const url = match[0].replace(TRAILING_PUNCTUATION_RE, "");
    if (!url) continue;
    const start = match.index ?? 0;
    if (start > cursor) {
      segments.push({ text: text.slice(cursor, start), url: null });
    }
    segments.push({ text: url, url });
    cursor = start + url.length;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), url: null });
  }
  return segments;
}
