import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { orbColors, getOrbClasses, type OrbVisualState } from "./styles";

interface OrbProps {
  state: OrbVisualState;
  size?: number;
  enableTracking?: boolean;
}

export function Orb({ state, size = 140, enableTracking = false }: OrbProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const targetRef = useRef({ x: 0, y: 0 });
  const rafRef = useRef<number>(0);

  const colors = orbColors[state];
  const classes = getOrbClasses(state);

  const lerp = useCallback(() => {
    setOffset((prev) => {
      const nx = prev.x + (targetRef.current.x - prev.x) * 0.015;
      const ny = prev.y + (targetRef.current.y - prev.y) * 0.015;
      if (Math.abs(nx - prev.x) < 0.01 && Math.abs(ny - prev.y) < 0.01) {
        return prev;
      }
      return { x: nx, y: ny };
    });
    rafRef.current = requestAnimationFrame(lerp);
  }, []);

  useEffect(() => {
    if (!enableTracking) return;
    rafRef.current = requestAnimationFrame(lerp);
    return () => cancelAnimationFrame(rafRef.current);
  }, [enableTracking, lerp]);

  useEffect(() => {
    if (!enableTracking) return;

    const handleMove = (e: MouseEvent) => {
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const range = 14;
      targetRef.current = {
        x: ((e.clientX - cx) / (window.innerWidth / 2)) * range,
        y: ((e.clientY - cy) / (window.innerHeight / 2)) * range,
      };
    };

    window.addEventListener("mousemove", handleMove);
    return () => window.removeEventListener("mousemove", handleMove);
  }, [enableTracking]);

  const gradient = `radial-gradient(circle at 35% 30%, ${colors[0]}, ${colors[1]} 50%, ${colors[2]})`;
  const glowColor = `${colors[1]}80`;

  return (
    <div
      ref={containerRef}
      className={cn("relative", classes.float)}
      style={{ width: size, height: size }}
    >
      {/* Glow */}
      <div
        className={cn(
          "absolute inset-[-15%] rounded-full blur-xl opacity-50",
          classes.glow,
        )}
        style={{ background: glowColor }}
      />
      {/* Body */}
      <div
        className={cn(
          "absolute inset-0 rounded-full shadow-lg",
          classes.breathe,
          classes.body,
        )}
        style={{
          background: gradient,
          transform: enableTracking
            ? `translate(${offset.x}px, ${offset.y}px)`
            : undefined,
        }}
      />
    </div>
  );
}
