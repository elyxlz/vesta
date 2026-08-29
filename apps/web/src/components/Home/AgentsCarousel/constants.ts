export const AGENT_CAROUSEL_GAP = 16;
export const AGENT_CAROUSEL_CARD_WIDTH = 220;
export const AGENT_CAROUSEL_ITEM_STRIDE =
  AGENT_CAROUSEL_CARD_WIDTH + AGENT_CAROUSEL_GAP;
// Scale of a card one stride or more from the scrollport's center.
export const AGENT_CAROUSEL_EDGE_SCALE = 0.85;

export function scaleForCarouselItemOffset(offsetPx: number) {
  const distance = Math.abs(offsetPx);
  return (
    1 -
    (1 - AGENT_CAROUSEL_EDGE_SCALE) *
      Math.min(distance / AGENT_CAROUSEL_ITEM_STRIDE, 1)
  );
}
