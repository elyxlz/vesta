import { orbIsLive, type OrbVisualState } from "../agent-status/agent-status";

interface OrbPoint {
  x: number;
  y: number;
}

interface OrbHighlight {
  cx: number;
  cy: number;
  wRatio: number;
  hRatio: number;
  angleDeg: number;
  alpha: number;
}

export interface OrbVisual {
  gradient: { start: OrbPoint; end: OrbPoint };
  highlight: OrbHighlight;
  live: boolean;
  breathes: boolean;
  thinking: boolean;
  pulseScale: number;
  pulseHalfMs: number;
  rotationMs: number;
  // The whole orb, glow included: 1, except while a conversation waits for the wake phrase.
  opacity: number;
}

// Geometry shared by every state: the diagonal gradient axis and the glossy
// highlight oval, in orb-normalized coordinates (0..1 across the orb).
const GRADIENT = { start: { x: 0.15, y: 0 }, end: { x: 0.9, y: 1 } } as const;
const HIGHLIGHT: OrbHighlight = {
  cx: 0.39,
  cy: 0.28,
  wRatio: 0.42,
  hRatio: 0.24,
  angleDeg: -24,
  alpha: 0.34,
};

// A live-voice overlay on top of the status: same colors and glow, different motion.
// "waiting" (for the wake phrase) is dim and all but still, so the hit that wakes it reads as
// the orb coming up; "listening" barely breathes; "talking" pulses hard and fast.
export type OrbMotion = "waiting" | "listening" | "talking";

const MOTION_CONFIG: Record<
  OrbMotion,
  Pick<OrbVisual, "pulseScale" | "pulseHalfMs" | "opacity">
> = {
  waiting: { pulseScale: 1.015, pulseHalfMs: 3600, opacity: 0.4 },
  listening: { pulseScale: 1.03, pulseHalfMs: 2400, opacity: 1 },
  talking: { pulseScale: 1.16, pulseHalfMs: 430, opacity: 1 },
};

// One owner for how the orb looks and moves; each platform renders from this.
export function orbVisual(
  state: OrbVisualState,
  motion?: OrbMotion,
): OrbVisual {
  const thinking = state === "thinking";
  const base: OrbVisual = {
    gradient: GRADIENT,
    highlight: HIGHLIGHT,
    live: orbIsLive(state),
    breathes: state === "alive" || thinking,
    thinking,
    pulseScale: thinking ? 1.1 : 1.04,
    pulseHalfMs: thinking ? 1200 : 1800,
    rotationMs: thinking ? 2600 : 9000,
    opacity: 1,
  };
  if (!motion) return base;
  return { ...base, breathes: true, ...MOTION_CONFIG[motion] };
}

// CSS `linear-gradient` angle (deg) that matches the start -> end axis, with the
// screen's y-axis pointing down. Precomputed once: the axis is a constant.
export const ORB_GRADIENT_ANGLE_DEG =
  (Math.atan2(
    GRADIENT.end.x - GRADIENT.start.x,
    -(GRADIENT.end.y - GRADIENT.start.y),
  ) *
    180) /
  Math.PI;
