import { AnimatePresence, motion } from "motion/react";
import { createPortal } from "react-dom";
import { useScrim } from "@/stores/use-scrim";

// The app's one scrim, mounted once: a fixed dim+blur layer under every
// floating surface (z-40, contents sit at z-50), shown while any overlay root
// holds it (stores/use-scrim). Because it is a singleton, a handoff between
// two surfaces (popover to dialog) keeps it mounted and the blur continuous;
// a click on it lands outside whatever is open, so it dismisses.
export function Scrim() {
  const held = useScrim((s) => s.holders > 0);
  return createPortal(
    <AnimatePresence initial={false}>
      {held && (
        <motion.div
          aria-hidden
          className="fixed inset-0 z-40 bg-black/20 will-change-[opacity,backdrop-filter] supports-backdrop-filter:backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        />
      )}
    </AnimatePresence>,
    document.body,
  );
}
