export const FEED_BOTTOM_THRESHOLD = 32;

// How far the viewport's bottom edge sits above the end of the content the reader last saw.
// A growth's own position-hold adjustment reports a scroll carrying the grown content height
// before the follow decision runs, so the distance is measured against the settled height: a
// burst of new lines then reads as still at the bottom, while a reader who scrolled up reads far.
export function distanceFromSettledBottom(input: {
  settledContentHeight: number;
  contentHeight: number;
  viewportHeight: number;
  offset: number;
}): number {
  return (
    Math.min(input.contentHeight, input.settledContentHeight) -
    input.viewportHeight -
    input.offset
  );
}
