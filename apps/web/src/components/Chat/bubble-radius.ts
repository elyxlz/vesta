import type { CSSProperties } from "react";

// Bubble corner radii (px). The body radius is large but FINITE, not 9999: a pill-corner
// shares each edge with the tail, and CSS clamps a whole edge's radii proportionally, which
// crushes the tail to ~0. A finite body keeps the pill look while letting the tail show.
const BUBBLE_BODY_RADIUS = 20;
// The one tail corner kept tighter than the body so the bubble reads as a chat bubble.
const BUBBLE_TAIL_RADIUS = 6;

// All four corners as longhands (no `borderRadius` shorthand) so React never
// drops the per-corner override; inline so it beats the ui base radius. Shared
// with the skeleton rows so the loading shapes match the real bubbles.
export function bubbleRadiusStyle(
  isUser: boolean,
  hasTail: boolean,
): CSSProperties {
  return {
    borderTopLeftRadius: BUBBLE_BODY_RADIUS,
    borderTopRightRadius: BUBBLE_BODY_RADIUS,
    borderBottomLeftRadius: BUBBLE_BODY_RADIUS,
    borderBottomRightRadius: BUBBLE_BODY_RADIUS,
    ...(hasTail && isUser && { borderBottomRightRadius: BUBBLE_TAIL_RADIUS }),
    ...(hasTail && !isUser && { borderBottomLeftRadius: BUBBLE_TAIL_RADIUS }),
  };
}
