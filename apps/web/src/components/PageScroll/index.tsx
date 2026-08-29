import { type ReactNode } from "react";
import { useLayout } from "@/stores/use-layout";
import { BOTTOM_FADE_PX, useScrollFade } from "@/hooks/use-scroll-fade";
import { cn } from "@/lib/utils";

// A full-page scroll surface: content scrolls under the fixed navbar, dissolving into it
// over twice its height at the top and softening at the bottom, and inset by the page
// padding. The fade shows only on the edge that can still scroll, so a short page and the
// very top and bottom never fade.

export function PageScroll({
  children,
  className,
  contentClassName,
}: {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const { ref: scrollRef, style: fadeStyle } = useScrollFade<HTMLDivElement>({
    top: `${String(navbarHeight * 2)}px`,
    bottom: `${String(BOTTOM_FADE_PX)}px`,
  });

  return (
    <div
      ref={scrollRef}
      className={cn(
        "min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]",
        className,
      )}
      style={fadeStyle}
    >
      <div
        className={cn("px-1 md:px-page", contentClassName)}
        style={{
          paddingTop: `calc(${String(navbarHeight)}px + var(--page-padding-x))`,
          paddingBottom: "calc(var(--page-padding-x) * 2)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
