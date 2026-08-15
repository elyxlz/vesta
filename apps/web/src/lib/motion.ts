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

// Step-body enter/exit: floaty slide + blur. Reduced motion keeps plain fades.
export function floatTransition(reduced: boolean) {
  if (reduced) {
    return {
      initial: { opacity: 0 },
      animate: { opacity: 1 },
      exit: { opacity: 0 },
      transition: { duration: 0.2 },
    };
  }
  return {
    initial: { opacity: 0, y: 12, scale: 0.98, filter: "blur(4px)" },
    animate: { opacity: 1, y: 0, scale: 1, filter: "blur(0px)" },
    exit: { opacity: 0, y: -12, scale: 0.98, filter: "blur(4px)" },
    transition: floatSpring,
  };
}

export const textSwap = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.18 },
};
