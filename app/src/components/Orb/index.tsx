import { useEffect, useRef } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { orbColors, type OrbVisualState } from "./styles";

interface OrbProps {
  state: OrbVisualState;
  size?: number;
  enableTracking?: boolean;
}

const LIVE_STATES = new Set<OrbVisualState>([
  "alive",
  "thinking",
  "booting",
  "authenticating",
  "starting",
  "loading",
]);

export function Orb({ state, size = 140, enableTracking = false }: OrbProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const colors = orbColors[state];
  const isLive = LIVE_STATES.has(state);
  const shouldTrack = enableTracking && isLive;

  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  const springX = useSpring(mouseX, { stiffness: 120, damping: 20 });
  const springY = useSpring(mouseY, { stiffness: 120, damping: 20 });

  const maxOffset = size * 0.06;
  const trackX = useTransform(springX, [-1, 1], [-maxOffset, maxOffset]);
  const trackY = useTransform(springY, [-1, 1], [-maxOffset, maxOffset]);

  const hlBaseLeft = size * 0.18;
  const hlBaseTop = size * 0.12;
  const hlShift = size * 0.06;
  const highlightX = useTransform(
    springX,
    [-1, 1],
    [hlBaseLeft - hlShift, hlBaseLeft + hlShift],
  );
  const highlightY = useTransform(
    springY,
    [-1, 1],
    [hlBaseTop - hlShift, hlBaseTop + hlShift],
  );

  useEffect(() => {
    if (!shouldTrack) {
      mouseX.set(0);
      mouseY.set(0);
      return;
    }

    const onMove = (e: MouseEvent) => {
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      mouseX.set(
        Math.max(
          -1,
          Math.min(1, (e.clientX - cx) / (window.innerWidth * 0.4)),
        ),
      );
      mouseY.set(
        Math.max(
          -1,
          Math.min(1, (e.clientY - cy) / (window.innerHeight * 0.4)),
        ),
      );
    };

    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [shouldTrack, mouseX, mouseY]);

  const floatY = isLive
    ? state === "thinking"
      ? [0, -8, 0]
      : [0, -6, 0]
    : 0;
  const floatDuration = state === "thinking" ? 3 : 4;

  const glowOpacity =
    state === "thinking" ? [0.3, 0.55, 0.3] : isLive ? 0.4 : 0.08;
  const glowScale =
    state === "thinking" ? [1, 1.08, 1] : isLive ? 1 : 0.8;
  const orbScale = state === "thinking" ? [1, 1.03, 1] : 1;

  const insetD = Math.round(size * 0.15);
  const blurD = Math.round(size * 0.3);
  const insetL = Math.round(size * 0.08);
  const blurL = Math.round(size * 0.25);
  const glowPad = Math.round(size * 0.25);
  const glowBlur = Math.round(size * 0.2);
  const hlW = Math.round(size * 0.35);
  const hlH = Math.round(size * 0.28);
  const hlBlur = Math.max(1, Math.round(size * 0.02));

  const colorTransition = { duration: 1.5, ease: "easeInOut" as const };
  const pulseTransition = {
    duration: 2.5,
    repeat: Infinity,
    ease: "easeInOut" as const,
  };

  return (
    <div
      ref={containerRef}
      style={{ width: size, height: size, position: "relative" }}
    >
      <motion.div
        style={{ x: trackX, y: trackY, position: "absolute", inset: 0 }}
      >
        <motion.div
          initial={false}
          animate={{ y: floatY }}
          transition={{
            y: isLive
              ? {
                duration: floatDuration,
                repeat: Infinity,
                ease: "easeInOut",
              }
              : { duration: 1.2, ease: "easeOut" },
          }}
          style={{ position: "relative", width: "100%", height: "100%" }}
        >
          <motion.div
            initial={false}
            animate={{
              opacity: glowOpacity,
              scale: glowScale,
              backgroundColor: colors[1],
            }}
            transition={{
              opacity:
                state === "thinking" ? pulseTransition : colorTransition,
              scale:
                state === "thinking" ? pulseTransition : colorTransition,
              backgroundColor: colorTransition,
            }}
            style={{
              position: "absolute",
              top: -glowPad,
              left: -glowPad,
              right: -glowPad,
              bottom: -glowPad,
              borderRadius: "50%",
              filter: `blur(${glowBlur}px)`,
              pointerEvents: "none",
            }}
          />

          <motion.div
            initial={false}
            animate={{
              backgroundColor: colors[1],
              boxShadow: `inset ${-insetD}px ${-insetD}px ${blurD}px ${colors[2]}, inset ${insetL}px ${insetL}px ${blurL}px ${colors[0]}`,
              scale: orbScale,
            }}
            transition={{
              backgroundColor: colorTransition,
              boxShadow: colorTransition,
              scale:
                state === "thinking"
                  ? pulseTransition
                  : { duration: 0.8, ease: "easeOut" },
            }}
            style={{
              width: size,
              height: size,
              borderRadius: "50%",
              position: "relative",
              overflow: "hidden",
            }}
          >
            <motion.div
              style={{
                position: "absolute",
                left: highlightX,
                top: highlightY,
                width: hlW,
                height: hlH,
                borderRadius: "50%",
                background:
                  "radial-gradient(ellipse at center, rgba(255,255,255,0.3), transparent 70%)",
                filter: `blur(${hlBlur}px)`,
                pointerEvents: "none",
              }}
            />
          </motion.div>
        </motion.div>
      </motion.div>
    </div>
  );
}
