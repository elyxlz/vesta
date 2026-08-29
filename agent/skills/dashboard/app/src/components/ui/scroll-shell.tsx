import * as React from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";
import { BOTTOM_FADE_PX, useScrollFade } from "@/hooks/use-scroll-fade";

// A floated header/footer dissolves content over this multiple of its own height; an edge with no
// chrome (no header, or no footer) softens by the flat BOTTOM_FADE_PX instead.
const CHROME_FADE_MULT = 1.5;

interface ScrollChrome {
  slot: HTMLElement | null;
  reportHeight: (height: number) => void;
}
// null default = no ScrollShell around it, so the header/footer renders in place rather than floating.
const HeaderChromeContext = React.createContext<ScrollChrome | null>(null);
const FooterChromeContext = React.createContext<ScrollChrome | null>(null);

// A floated header/footer measures itself, so the scroll reserves its height as padding and sizes
// its fade to it. Measures synchronously before paint (the observer's own first callback is async,
// which would let one frame paint with the padding still 0, content under the header). On unmount it
// reports 0, so a shell that drops its footer does not keep the gone height as dead bottom padding.
function useReportHeight(
  chrome: ScrollChrome | null,
  node: HTMLElement | null,
): void {
  React.useLayoutEffect(() => {
    const report = chrome?.reportHeight;
    if (!report || !node) return;
    report(node.offsetHeight);
    const observer = new ResizeObserver(() => report(node.offsetHeight));
    observer.observe(node);
    return () => {
      observer.disconnect();
      report(0);
    };
  }, [chrome, node]);
}

// Inside a ScrollShell, portal the header/footer into its slot once mounted; standalone, render in place.
function portalChrome(
  chrome: ScrollChrome | null,
  content: React.ReactNode,
): React.ReactNode {
  if (!chrome) return content;
  return chrome.slot ? createPortal(content, chrome.slot) : null;
}

// A header (edge "top") or footer (edge "bottom") for a ScrollShell: a plain div that measures itself
// and floats into the shell's matching slot, or renders in place with no shell around it. Every
// dialog/drawer header, footer, and handle is this plus its own styling and a11y primitive.
export function ShellChrome({
  edge,
  children,
  ...props
}: React.ComponentProps<"div"> & { edge: "top" | "bottom" }) {
  const header = React.useContext(HeaderChromeContext);
  const footer = React.useContext(FooterChromeContext);
  const chrome = edge === "top" ? header : footer;
  const [node, setNode] = React.useState<HTMLDivElement | null>(null);
  useReportHeight(chrome, node);
  return portalChrome(
    chrome,
    <div ref={setNode} {...props}>
      {children}
    </div>,
  );
}

// One scroll region that fills the shell; a header floats over its top and a footer over its bottom
// (both measured), so the scroll reserves each one's height as padding and dissolves content into
// both edges, and the scrollbar dissolves with the content, like PageScroll. Shared by the dialog
// sheet and every drawer. `closeButton` is the shell's own pinned affordance, if any.
export function ScrollShell({
  children,
  closeButton,
}: {
  children: React.ReactNode;
  closeButton?: React.ReactNode;
}) {
  const [headerSlot, setHeaderSlot] = React.useState<HTMLDivElement | null>(
    null,
  );
  const [footerSlot, setFooterSlot] = React.useState<HTMLDivElement | null>(
    null,
  );
  const [headerHeight, setHeaderHeight] = React.useState(0);
  const [footerHeight, setFooterHeight] = React.useState(0);
  const headerChrome = React.useMemo(
    () => ({ slot: headerSlot, reportHeight: setHeaderHeight }),
    [headerSlot],
  );
  const footerChrome = React.useMemo(
    () => ({ slot: footerSlot, reportHeight: setFooterHeight }),
    [footerSlot],
  );
  // The fade dissolves content into each floated edge over CHROME_FADE_MULT × its height, but only on
  // an edge that can still scroll, so a short shell and the very top and bottom stay crisp. An edge
  // with no chrome softens by the flat BOTTOM_FADE_PX instead.
  const topFade =
    headerHeight > 0 ? headerHeight * CHROME_FADE_MULT : BOTTOM_FADE_PX;
  const bottomFade =
    footerHeight > 0 ? footerHeight * CHROME_FADE_MULT : BOTTOM_FADE_PX;
  const {
    ref: scrollRef,
    style: fadeStyle,
    edges,
  } = useScrollFade<HTMLDivElement>({
    top: `${String(topFade)}px`,
    bottom: `${String(bottomFade)}px`,
    topChrome: headerHeight > 0,
    bottomChrome: footerHeight > 0,
  });

  return (
    <HeaderChromeContext.Provider value={headerChrome}>
      <FooterChromeContext.Provider value={footerChrome}>
        <div
          ref={scrollRef}
          data-slot="scroll-shell"
          className={cn(
            "flex min-h-0 w-full flex-1 flex-col overflow-y-auto overscroll-contain px-6 pb-6",
            // The scrollbar gutter, like the fades, is reserved only while the body scrolls, so a
            // short shell's chrome stays flush with the edge.
            (edges.top || edges.bottom) && "[scrollbar-gutter:stable]",
          )}
          style={{
            ...fadeStyle,
            paddingTop: headerHeight,
            paddingBottom: footerHeight || undefined,
          }}
        >
          {children}
        </div>
        <div ref={setHeaderSlot} className="absolute inset-x-0 top-0 z-10" />
        <div ref={setFooterSlot} className="absolute inset-x-0 bottom-0 z-10" />
        {closeButton}
      </FooterChromeContext.Provider>
    </HeaderChromeContext.Provider>
  );
}
