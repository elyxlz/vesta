export const CHAT_LATEST_THRESHOLD = 32;

export function getLatestMessageOffset(
  platform: string | undefined,
  contentInsetTop: number,
): number {
  return platform === "ios" ? -contentInsetTop : 0;
}

export type AnchorTrigger = "inset" | "content";

// iOS rests an inverted list at offset 0, the screen's bottom edge, until it is told where the
// latest message lies. The first anchor waits for the inset and the content, whichever lands
// second. Content that arrives afterwards (history pages, a cold start swapping its placeholder
// for rows) can leave the list at the edge again, so content changes re-anchor while the reader
// is at the latest message. An inset change re-anchors only once: during the keyboard animation
// the library owns the offset.
export function shouldAnchorToLatest(input: {
  platform: string | undefined;
  hasContent: boolean;
  latestOffset: number;
  atLatest: boolean;
  anchored: boolean;
  trigger: AnchorTrigger;
}): boolean {
  return (
    input.platform === "ios" &&
    input.hasContent &&
    input.latestOffset < 0 &&
    input.atLatest &&
    (input.trigger === "content" || !input.anchored)
  );
}

export function isNearLatestMessage(
  scrollOffset: number,
  latestMessageOffset: number,
): boolean {
  return scrollOffset <= latestMessageOffset + CHAT_LATEST_THRESHOLD;
}
