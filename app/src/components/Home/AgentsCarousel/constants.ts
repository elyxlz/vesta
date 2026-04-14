export const AGENT_CAROUSEL_GAP = 16;
export const AGENT_CAROUSEL_CARD_WIDTH = 220;
export const AGENT_CAROUSEL_ITEM_STRIDE =
  AGENT_CAROUSEL_CARD_WIDTH + AGENT_CAROUSEL_GAP;

export function scaleForCarouselItemOffset(offsetPx: number) {
  const distance = Math.abs(offsetPx);
  return 1 - 0.15 * Math.min(distance / AGENT_CAROUSEL_ITEM_STRIDE, 1);
}
