import type { CSSProperties } from "react";
import {
  ORB_GRADIENT_ANGLE_DEG,
  orbVisual,
  type OrbVisualState,
} from "@vesta/core";
import { orbColors } from "@/design-tokens";

// The diagonal 3-stop gradient that fills the orb circle.
export function orbGradientCss(state: OrbVisualState): string {
  const [light, mid, dark] = orbColors[state];
  const deg = ORB_GRADIENT_ANGLE_DEG.toFixed(2);
  return `linear-gradient(${deg}deg, ${light} 0%, ${mid} 50%, ${dark} 100%)`;
}

// The glossy white highlight oval, positioned and rotated over the orb.
export function orbHighlightStyle(
  size: number,
  state: OrbVisualState,
): CSSProperties {
  const { highlight } = orbVisual(state);
  const width = highlight.wRatio * size;
  const height = highlight.hRatio * size;
  return {
    position: "absolute",
    width,
    height,
    left: highlight.cx * size - width / 2,
    top: highlight.cy * size - height / 2,
    borderRadius: size,
    background: `rgba(255,255,255,${String(highlight.alpha)})`,
    transform: `rotate(${String(highlight.angleDeg)}deg)`,
    pointerEvents: "none",
  };
}

// Soft contact shadow under the orb, tinted by its mid tone (~0.42 alpha).
export function orbShadowCss(size: number, state: OrbVisualState): string {
  const mid = orbColors[state][1];
  return `0px ${String(Math.round(size * 0.09))}px ${String(Math.round(size * 0.2))}px ${mid}6b`;
}
