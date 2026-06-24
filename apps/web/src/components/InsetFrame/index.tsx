import type { ReactNode } from "react";
import { createPortal } from "react-dom";

// Above every portaled overlay (dialogs/popovers/sheets at z-50, navbar z-99999,
// agent island z-999999) so the frame masks them too. Max 32-bit z-index.
const FRAME_Z = 2147483647;

/**
 * The web-desktop "framed window" look, done without clipping the layout.
 *
 *  - The content surface is in-flow (fills the fixed-viewport flex shell minus the
 *    gutter; bg-muted distinguishes it from the --background gutter). No overflow
 *    clip — the rounded corners are faked by the overlay instead.
 *  - The overlay is PORTALED TO document.body (so it's a sibling of every dialog
 *    portal, not trapped inside #root) and pinned --frame-inset from each edge. Its
 *    `0 0 0 100vmax` box-shadow in --background paints everything OUTSIDE its rounded
 *    rect — the gutter plus anything sliding past the squircle corners, including
 *    portaled dialog/popover overlays — so the whole app reads as a clipped window.
 *    A hairline border draws the frame line. pointer-events-none so it never eats
 *    clicks.
 *
 * The surface margin equals the gutter so the surface rect lines up exactly with
 * the overlay rect (and the frame line), keeping content inset the same as the
 * gutter rather than tucked under the frame.
 */
export function InsetFrame({ children }: { children: ReactNode }) {
  return (
    <>
      <div
        className="relative flex min-h-0 flex-1 flex-col rounded-squircle-md bg-muted [corner-shape:squircle]"
        style={{ margin: "var(--frame-inset)" }}
      >
        {children}
      </div>

      {createPortal(
        <div
          aria-hidden
          className="pointer-events-none fixed rounded-squircle-md [corner-shape:squircle]"
          style={{
            inset: "var(--frame-inset)",
            zIndex: FRAME_Z,
            boxShadow: "0 0 0 100vmax var(--background)",
          }}
        >
          <div className="absolute inset-0 rounded-[inherit] border border-border [corner-shape:inherit]" />
        </div>,
        document.body,
      )}
    </>
  );
}
