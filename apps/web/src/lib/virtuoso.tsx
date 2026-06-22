import { forwardRef, type CSSProperties } from "react";
import type { Components } from "react-virtuoso";
import { cn } from "@/lib/utils";

interface ScrollerExtras {
  className?: string;
  style?: CSSProperties;
}

/**
 * react-virtuoso's vertical Scroller has two sharp edges we kept hitting in every
 * virtualized list:
 *
 *  1. The `className` set on <Virtuoso> is forwarded to a custom Scroller via props.
 *     A Scroller that sets its own `className` silently *overwrites* it, dropping the
 *     list's font/size/color styling.
 *  2. It only sets `overflow-y: auto` inline, leaving `overflow-x` to compute to `auto`
 *     too — so any content a hair too wide gets a phantom horizontal scrollbar.
 *
 * createScroller bakes in both fixes (merge the forwarded className, clip overflow-x)
 * so a list is correct by construction. `extras` contributes per-list class and style
 * derived from the list's context (e.g. a fade mask). Horizontal padding belongs on the
 * item content, not here — virtuoso doesn't bound the inner item width to the scroller's
 * padding box, so a padded scroller leaves long lines flush to the edge.
 */
export function createScroller<Data, Context>(
  extras?: (context: Context | undefined) => ScrollerExtras | undefined,
): Components<Data, Context>["Scroller"] {
  const Scroller: Components<Data, Context>["Scroller"] = forwardRef(
    function Scroller({ context, style, className, ...props }, ref) {
      const extra = extras?.(context);
      return (
        <div
          {...props}
          ref={ref}
          className={cn(className, "overflow-x-hidden", extra?.className)}
          style={{ ...style, ...extra?.style }}
        />
      );
    },
  );
  return Scroller;
}
