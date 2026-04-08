export const thinkingIndicatorVariants = {
  hidden: { height: 0, opacity: 0 },
  visible: {
    height: "auto",
    opacity: 1,
    transition: {
      height: {
        type: "spring" as const,
        stiffness: 420,
        damping: 28,
        mass: 0.65,
      },
      opacity: {
        duration: 0.18,
        ease: [0.2, 0.8, 0.2, 1] as const,
      },
    },
  },
  exit: {
    height: 0,
    opacity: 0,
    transition: {
      height: {
        duration: 0.22,
        ease: [0.32, 0.72, 0, 1] as const,
      },
      opacity: { duration: 0.14, ease: "easeIn" as const },
    },
  },
};
