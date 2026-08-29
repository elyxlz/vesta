import {
  animate,
  AnimatePresence,
  motion,
  useMotionValue,
  type MotionValue,
} from "motion/react";
import {
  CircleCheckIcon,
  InfoIcon,
  OctagonXIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useToastStore, type Toast, type ToastKind } from "@/stores/use-toast";
import { PILL_EXPANDED_HEIGHT } from "@/providers/NotificationsPillProvider/context";

// Mirrors NotificationsPill's shell on the other side of the navbar: one pill
// that springs its width open to the measured content and collapses back out,
// so a toast reads as the twin of a notification. A replacement toast rotates
// through the held-open shell (content slides, width springs, tint crossfades)
// instead of collapsing and reopening. The behavior source is the toast store;
// this is only the rendering. The absolute cap is generous: on desktop the
// navbar's responsive budget (up to the agent island) is the real limit.
const PILL_MAX_WIDTH = 480;

interface ResizeConfig {
  readonly type: "spring";
  readonly duration: number;
  readonly bounce: number;
}

const KIND_ICON: Record<ToastKind, LucideIcon> = {
  error: OctagonXIcon,
  success: CircleCheckIcon,
  info: InfoIcon,
};

// The kind's look, split so a replacement can crossfade: the tint layer
// (border + fill) sits behind the content, the text color rides the content.
// The colored fills are fully opaque: the mobile toast floats over page
// content, and a translucent tint would let it bleed through.
const KIND_TINT: Record<ToastKind, string> = {
  error:
    "border border-destructive/25 bg-red-100 shadow-sm dark:border-red-400/25 dark:bg-red-950",
  success:
    "border border-emerald-600/25 bg-emerald-100 shadow-sm dark:border-emerald-400/25 dark:bg-emerald-950",
  info: "chrome-outline",
};
const KIND_TEXT: Record<ToastKind, string> = {
  error: "text-destructive",
  success: "text-emerald-700 dark:text-emerald-400",
  info: "text-foreground",
};

export function ToastPill({
  maxWidth = PILL_MAX_WIDTH,
  centered = false,
}: {
  /** Responsive width budget from the navbar (space up to the agent island). */
  maxWidth?: number;
  /** Floating placement (centered shell): pin lines to the center, not the right edge. */
  centered?: boolean;
}) {
  const current = useToastStore((state) => state.current);
  const dismiss = useToastStore((state) => state.dismiss);
  const cap = Math.min(PILL_MAX_WIDTH, maxWidth);

  return (
    // The shell's key is constant: replacements rotate inside the open shell,
    // and only an emptied store collapses it. initial={false} keeps a navbar
    // remount (page navigation) from replaying the shown toast's entrance;
    // the morph width persists in the toast store.
    <AnimatePresence mode="wait" initial={false}>
      {current && (
        <ToastShell
          key="toast"
          toast={current}
          cap={cap}
          centered={centered}
          onDismiss={dismiss}
        />
      )}
    </AnimatePresence>
  );
}

function ToastShell({
  toast,
  cap,
  centered,
  onDismiss,
}: {
  toast: Toast;
  cap: number;
  centered: boolean;
  onDismiss: () => void;
}) {
  // Store-owned (module scope, beside the queue) so a navbar remount resumes
  // mid-morph.
  const width = useToastStore((state) => state.morphWidth);

  // The kind tint crossfades in exact sync with the width: the front layer
  // fades in on the same spring as the resize, over a back layer (the
  // previous kind) that stays fully opaque until the front covers it, so the
  // page never shows through mid-crossfade.
  const [backKind, setBackKind] = useState(toast.kind);
  const frontTint = useMotionValue(1);

  // The line's measuring effect (ToastLine) reports each resize here so the
  // tint crossfade runs on the width's exact spring and delay.
  const onResize = (resize: ResizeConfig) => {
    if (backKind === toast.kind) return;
    frontTint.jump(0);
    const tintControls = animate(frontTint, 1, resize);
    void tintControls.then(() => {
      setBackKind(toast.kind);
    });
  };

  return (
    <motion.button
      type="button"
      aria-label="dismiss notification"
      // justify-end: the shell is right-aligned in the navbar, so its right
      // edge is the static one; anchoring content there keeps it horizontally
      // still while the width springs, and the rotary slide stays vertical.
      className="relative flex items-center justify-end overflow-hidden rounded-full"
      // maxWidth clamps the shell live: a window resized mid-toast squeezes it
      // off the center content immediately, without re-running the springs.
      style={{ width, maxWidth: cap, height: PILL_EXPANDED_HEIGHT }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{
        width: 0,
        opacity: 0,
        transition: {
          type: "spring",
          duration: 0.5,
          bounce: 0,
          opacity: { duration: 0.3, ease: "easeOut" },
        },
      }}
      transition={{
        type: "spring",
        duration: 0.5,
        bounce: 0.2,
        opacity: { duration: 0.3, ease: "easeOut" },
      }}
      onClick={onDismiss}
    >
      {/* The kind's tint: the previous kind behind, the current in front,
          crossfading on the width's own spring (see the measuring effect). */}
      <span
        aria-hidden
        className={`absolute inset-0 rounded-full ${KIND_TINT[backKind]}`}
      />
      <motion.span
        aria-hidden
        className={`absolute inset-0 rounded-full ${KIND_TINT[toast.kind]}`}
        style={{ opacity: frontTint }}
      />
      {/* The rotary: a replacement slides the old line up and out while the
          new one slides in from below. Every line is absolutely pinned to the
          right edge, the static one, so entering and exiting lines alike move
          only vertically while the width springs. */}
      <AnimatePresence initial={false}>
        <ToastLine
          key={toast.id}
          toast={toast}
          width={width}
          cap={cap}
          centered={centered}
          onResize={onResize}
        />
      </AnimatePresence>
    </motion.button>
  );
}

// One toast's line, absolutely pinned to the shell's static right edge. It
// owns the measuring effect: springs the shell to its width (direction-aware
// sequencing, like the notifications pill), and slides itself in through its
// own motion values, so a parent re-render can never reapply a stale
// transform and knock the line off center.
function ToastLine({
  toast,
  width,
  cap,
  centered,
  onResize,
}: {
  toast: Toast;
  width: MotionValue<number>;
  cap: number;
  centered: boolean;
  onResize: (resize: ResizeConfig) => void;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  // Arrival-time snapshot for the measuring effect: a resize mid-toast is
  // handled by the shell's CSS clamp, never by re-running the springs.
  const capRef = useRef(cap);
  useEffect(() => {
    capRef.current = cap;
  }, [cap]);
  const y = useMotionValue(0);
  const opacity = useMotionValue(1);
  const Icon = KIND_ICON[toast.kind];

  // Mirrored so the measuring effect depends only on the toast identity: a
  // parent re-render (the tint settling) must never cycle the effect, whose
  // cleanup would stop the in-flight springs mid-motion.
  const onResizeRef = useRef(onResize);
  useEffect(() => {
    onResizeRef.current = onResize;
  }, [onResize]);

  useLayoutEffect(() => {
    const content = ref.current;
    if (!content) return;
    const target = Math.min(content.offsetWidth, capRef.current);
    const from = width.get();
    // Everything moves together: lines are pinned to the static right edge,
    // so the slide has no horizontal component to sequence around, and the
    // tint rides the same config as the width (see onResize).
    const resize: ResizeConfig = { type: "spring", duration: 0.5, bounce: 0.2 };
    const widthControls = animate(width, target, resize);
    onResizeRef.current(resize);
    // A replacement slides in from below; the first open just fades with the
    // widening shell.
    y.jump(from > 0 ? 24 : 0);
    opacity.jump(0);
    const slide = { type: "spring", duration: 0.35, bounce: 0 } as const;
    const yControls = animate(y, 0, slide);
    const opacityControls = animate(opacity, 1, slide);
    return () => {
      widthControls.stop();
      yControls.stop();
      opacityControls.stop();
    };
  }, [toast.id, width, y, opacity]);

  return (
    <motion.span
      ref={ref}
      className={`absolute top-0 flex h-full w-max items-center gap-1.5 px-3 ${
        centered ? "left-1/2" : "right-0"
      } ${KIND_TEXT[toast.kind]}`}
      style={{ maxWidth: cap, x: centered ? "-50%" : 0, y, opacity }}
      exit={{ y: -24, opacity: 0 }}
      transition={{ type: "spring", duration: 0.35, bounce: 0 }}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      <span
        className={`min-w-0 truncate ${centered ? "text-xs" : "text-[13px]"}`}
      >
        {toast.title}
      </span>
    </motion.span>
  );
}
