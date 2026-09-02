import { orbIsLive, type OrbVisualState } from "../agent-status/agent-status";

export interface OrbPoint {
  x: number;
  y: number;
}

export interface OrbHighlight {
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
// "listening" barely breathes; "talking" pulses hard and fast, unmistakably speech.
export type OrbMotion = "listening" | "talking";

const MOTION_CONFIG: Record<
  OrbMotion,
  Pick<OrbVisual, "pulseScale" | "pulseHalfMs">
> = {
  listening: { pulseScale: 1.03, pulseHalfMs: 2400 },
  talking: { pulseScale: 1.16, pulseHalfMs: 430 },
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
