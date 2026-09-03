import { useEffect, useRef } from "react";
import { orbVisual, type OrbMotion, type OrbVisualState } from "@vesta/core";
import { usePrefersReducedMotion } from "@/hooks/use-reduced-motion";
import { orbColors } from "@/design-tokens";
import { orbGradientCss, orbHighlightStyle, orbShadowCss } from "./orb-css";

interface OrbProps {
  state: OrbVisualState;
  // Live-voice motion overlay: same colors, different breathing.
  motion?: OrbMotion;
  size?: number;
  suppressMotion?: boolean;
  label?: string;
  /** Halo strength multiplier (0..1): dense surfaces damp the glow. */
  glow?: number;
}

// The solid orb fills this fraction of its box; the rest is breathing room for
// the glow halo (the old WebGL sphere occupied a similar fraction of `size`).
const ORB_FILL = 0.68;

// Glow halo shape: how far the halo spreads past the orb, and the radius (as a
// percentage of the halo box) where its radial fade ends.
const GLOW_SPREAD_SCALE = 2;
const GLOW_FADE_PCT = 60;

export function Orb({
  state,
  motion,
  size = 140,
  suppressMotion = false,
  label,
  glow = 1,
}: OrbProps) {
  const gradientRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const motionSuppressed = suppressMotion || prefersReducedMotion;
  const visual = orbVisual(state, motion);
  const orbSize = size * ORB_FILL;
  const orbInset = (size - orbSize) / 2;

  const glowColor = orbColors[state][1];
  const glowOpacity =
    (state === "thinking" ? 0.62 : visual.live ? 0.46 : 0.18) * glow;
  const glowSize = state === "thinking" ? 1.25 : 1.12;
  const glowInset = Math.round(size * 0.18 * GLOW_SPREAD_SCALE);
  const fadePct = GLOW_FADE_PCT;
  const coreGlowPct = Math.max(0, fadePct - 48);
  const innerGlowPct = Math.max(0, fadePct - 32);
  const midGlowPct = Math.max(0, fadePct - 18);
  const outerGlowPct = Math.max(0, fadePct - 8);
  const edgeGlowPct = Math.max(0, fadePct - 2);
  const glowGradient = `radial-gradient(circle, ${glowColor}b8 0%, ${glowColor}84 ${String(coreGlowPct)}%, ${glowColor}52 ${String(innerGlowPct)}%, ${glowColor}2c ${String(midGlowPct)}%, ${glowColor}14 ${String(outerGlowPct)}%, ${glowColor}08 ${String(edgeGlowPct)}%, transparent ${String(fadePct)}%)`;

  // Slow spin of the gradient layer, only while the orb is live.
  useEffect(() => {
    const layer = gradientRef.current;
    if (
      !layer ||
      typeof layer.animate !== "function" ||
      motionSuppressed ||
      !visual.live
    ) {
      return;
    }
    const animation = layer.animate(
      [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
      { duration: visual.rotationMs, iterations: Infinity, easing: "linear" },
    );
    return () => animation.cancel();
  }, [motionSuppressed, visual.live, visual.rotationMs]);

  // Breathing, only for the states that "the agent itself is up" (alive/thinking).
  useEffect(() => {
    const shell = shellRef.current;
    if (
      !shell ||
      typeof shell.animate !== "function" ||
      motionSuppressed ||
      !visual.breathes
    ) {
      return;
    }
    const animation = shell.animate(
      [
        { transform: "scale(1)" },
        { transform: `scale(${String(visual.pulseScale)})` },
      ],
      {
        duration: visual.pulseHalfMs,
        iterations: Infinity,
        direction: "alternate",
        easing: "ease-in-out",
      },
    );
    return () => animation.cancel();
  }, [
    motionSuppressed,
    visual.breathes,
    visual.pulseScale,
    visual.pulseHalfMs,
  ]);

  return (
    <div
      role="img"
      aria-label={label ?? `agent ${state}`}
      style={{ width: size, height: size, position: "relative" }}
    >
      <div
        style={{
          position: "absolute",
          inset: -glowInset,
          borderRadius: "50%",
          background: glowGradient,
          opacity: glowOpacity,
          transform: `scale(${String(glowSize)})`,
          pointerEvents: "none",
          transition:
            "background 1.5s ease-in-out, opacity 1.5s ease-in-out, transform 1.5s ease-in-out",
        }}
      />
      <div
        ref={shellRef}
        style={{
          position: "absolute",
          width: orbSize,
          height: orbSize,
          left: orbInset,
          top: orbInset,
          borderRadius: "50%",
          overflow: "hidden",
          boxShadow: orbShadowCss(orbSize, state),
        }}
      >
        <div
          ref={gradientRef}
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            background: orbGradientCss(state),
            transition: "background 1.5s ease-in-out",
          }}
        />
        <div style={orbHighlightStyle(orbSize, state)} />
      </div>
    </div>
  );
}
