export const CHAT_LATEST_THRESHOLD = 32;

export function getLatestMessageOffset(
  platform: string | undefined,
  contentInsetTop: number,
): number {
  return platform === "ios" ? -contentInsetTop : 0;
}

export function isNearLatestMessage(
  scrollOffset: number,
  latestMessageOffset: number,
): boolean {
  return scrollOffset <= latestMessageOffset + CHAT_LATEST_THRESHOLD;
}
