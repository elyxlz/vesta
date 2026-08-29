import type { Transition } from "motion/react";

const spring: Transition = {
  type: "spring",
  stiffness: 400,
  damping: 30,
};

export const stepTransition = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: spring,
};

export const fade = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.15 },
};

export const floatSpring: Transition = {
  type: "spring",
  stiffness: 300,
  damping: 28,
};

// Reduced motion means no animation at all: elements appear and leave
// instantly rather than fading, per prefers-reduced-motion.
export const instant = {
  initial: { opacity: 1 },
  animate: { opacity: 1 },
  exit: { opacity: 1 },
  transition: { duration: 0 },
};

// Step-body enter/exit: floaty slide + fade.
export function floatTransition(reduced: boolean) {
  if (reduced) return instant;
  return {
    initial: { opacity: 0, y: 12, scale: 0.98 },
    animate: { opacity: 1, y: 0, scale: 1 },
    exit: { opacity: 0, y: -12, scale: 0.98 },
    transition: floatSpring,
  };
}

export const textSwap = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.18 },
};
