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

const floatSpring: Transition = {
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

// The sheet-behind choreography curve the conversation morph's companions share (scrim, top
// fade, panel slide, header and list recede): the motion/react form, and the tailwind
// recede classes carrying the same curve (the scanner reads class-shaped strings anywhere in
// source, so the one string below is the one owner of the CSS side).
export const sheetEase: [number, number, number, number] = [0.32, 0.72, 0, 1];
export const recedeTransition =
  "[will-change:transform] transition-transform ease-[cubic-bezier(0.32,0.72,0,1)]";

export const textSwap = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.18 },
};
