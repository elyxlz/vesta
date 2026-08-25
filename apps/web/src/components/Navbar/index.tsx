import { useState } from "react";
import { useMeasuredHeight } from "@/hooks/use-measured-height";
import { useMeasuredWidth } from "@/hooks/use-measured-width";
import { useIsMobile } from "@/hooks/use-mobile";
import { useLayout } from "@/stores/use-layout";
import { WindowControls } from "@/components/WindowControls";
import { NotificationsPill } from "./NotificationsPill";
import { ToastPill } from "./ToastPill";

interface NavbarProps {
  leading?: React.ReactNode;
  center?: React.ReactNode;
  trailing?: React.ReactNode;
}

// Breathing room between the center content (the agent island) and the
// widest a toast may grow toward it.
const TOAST_CENTER_GAP = 12;
// The floating toast has no measured budget; keep it phone-safe.
const FLOATING_TOAST_MAX_WIDTH = 340;
// An inline budget tighter than this reads as a sliver: the toast drops to
// the floating under-island placement instead, where the full width fits.
const MIN_INLINE_TOAST_WIDTH = 260;

export function Navbar({ leading, center, trailing }: NavbarProps) {
  const setNavbarHeight = useLayout((s) => s.setNavbarHeight);
  const measureRef = useMeasuredHeight(setNavbarHeight);
  const isMobile = useIsMobile();

  // The toast's responsive width budget: its slot spans from the navbar's
  // center to the trailing buttons, and the center content is centered on
  // that same point, so half the center's width intrudes into the slot.
  const [centerWidth, setCenterWidth] = useState(0);
  const [toastSlotWidth, setToastSlotWidth] = useState(0);
  const centerRef = useMeasuredWidth(setCenterWidth);
  const toastSlotRef = useMeasuredWidth(setToastSlotWidth);
  const toastMaxWidth = Math.max(
    0,
    toastSlotWidth - centerWidth / 2 - TOAST_CENTER_GAP,
  );
  const floatingToast = isMobile || toastMaxWidth < MIN_INLINE_TOAST_WIDTH;

  return (
    <div
      ref={measureRef}
      data-drag-region
      className="absolute top-0 left-0 right-0 z-[99999] flex flex-col shrink-0 min-h-0 select-none overflow-visible px-2.5"
      style={{
        paddingTop: "var(--safe-area-pt)",
        paddingBottom: "var(--navbar-pb)",
      }}
    >
      {/* Two equal halves with the center content absolutely centered (out of
          flow), so the center's width never shifts the halves and the left-gap
          pill stays centered on the true navbar center. */}
      <div data-drag-region className="relative flex items-center">
        <div
          data-drag-region
          className="flex flex-1 items-center gap-2 min-w-0"
          style={{ paddingLeft: "var(--titlebar-inset-left, 0px)" }}
        >
          {leading}
          <NotificationsPill />
        </div>

        <div
          data-drag-region
          className="flex flex-1 items-center gap-2 justify-end min-w-0"
        >
          <div
            ref={toastSlotRef}
            className="flex min-w-0 flex-1 items-center justify-end"
          >
            {!floatingToast && <ToastPill maxWidth={toastMaxWidth} />}
          </div>
          {trailing}
          <WindowControls />
        </div>

        <div
          data-drag-region
          className="absolute left-1/2 flex -translate-x-1/2 items-center"
        >
          <div ref={centerRef} className="flex items-center">
            {center}
          </div>
        </div>
      </div>

      {/* On mobile, and on any window whose inline budget is too tight, the
          toast floats centered under the navbar's center (the agent island),
          out of flow so it never changes the measured navbar height. One
          instance either way: two would fight over the shared morph width. */}
      {floatingToast && (
        <div className="pointer-events-none absolute inset-x-0 top-full flex justify-center">
          <div className="pointer-events-auto">
            <ToastPill maxWidth={FLOATING_TOAST_MAX_WIDTH} centered />
          </div>
        </div>
      )}
    </div>
  );
}
