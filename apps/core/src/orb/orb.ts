import { orbIsLive, type OrbVisualState } from "../agent-status/agent-status"

export interface OrbPoint {
  x: number
  y: number
}

export interface OrbHighlight {
  cx: number
  cy: number
  wRatio: number
  hRatio: number
  angleDeg: number
  alpha: number
}

export interface OrbVisual {
  gradient: { start: OrbPoint; end: OrbPoint }
  highlight: OrbHighlight
  live: boolean
  breathes: boolean
  thinking: boolean
  pulseScale: number
  pulseHalfMs: number
  rotationMs: number
}

// Geometry shared by every state: the diagonal gradient axis and the glossy
// highlight oval, in orb-normalized coordinates (0..1 across the orb).
const GRADIENT = { start: { x: 0.15, y: 0 }, end: { x: 0.9, y: 1 } } as const
const HIGHLIGHT: OrbHighlight = {
  cx: 0.39,
  cy: 0.28,
  wRatio: 0.42,
  hRatio: 0.24,
  angleDeg: -24,
  alpha: 0.34,
}

// One owner for how the orb looks and moves; each platform renders from this.
export function orbVisual(state: OrbVisualState): OrbVisual {
  const thinking = state === "thinking"
  return {
    gradient: GRADIENT,
    highlight: HIGHLIGHT,
    live: orbIsLive(state),
    breathes: state === "alive" || thinking,
    thinking,
    pulseScale: thinking ? 1.1 : 1.04,
    pulseHalfMs: thinking ? 1200 : 1800,
    rotationMs: thinking ? 2600 : 9000,
  }
}

// CSS `linear-gradient` angle (deg) that matches the start -> end axis, with the
// screen's y-axis pointing down.
export function orbGradientAngleDeg(visual: OrbVisual): number {
  const dx = visual.gradient.end.x - visual.gradient.start.x
  const dy = visual.gradient.end.y - visual.gradient.start.y
  return (Math.atan2(dx, -dy) * 180) / Math.PI
}
