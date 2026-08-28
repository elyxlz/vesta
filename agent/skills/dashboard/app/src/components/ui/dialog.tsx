"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Drawer as DrawerPrimitive } from "vaul";

import { cn } from "@/lib/utils";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { useScrollFade } from "@/hooks/use-scroll-fade";
import { Button } from "@/components/ui/button";
import { DrawerContent } from "@/components/ui/drawer";
import { XIcon } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";

const DrawerModeContext = React.createContext(false);

function Dialog({
  drawerOnMobile,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root> & {
  drawerOnMobile?: boolean;
}) {
  const isMobile = useIsMobile();
  const isDrawer = !!drawerOnMobile && isMobile;
  // Holds the app scrim (components/Scrim) while open, like every overlay
  // root; the drawer path keeps vaul's own drag-tracking overlay instead.
  const handleOpenChange = useOverlayScrim(props, { enabled: !isDrawer });
  const rootProps = { ...props, onOpenChange: handleOpenChange };

  if (isDrawer) {
    return (
      <DrawerModeContext.Provider value={true}>
        <DrawerPrimitive.Root data-slot="dialog" {...rootProps} />
      </DrawerModeContext.Provider>
    );
  }

  return (
    <DrawerModeContext.Provider value={false}>
      <DialogPrimitive.Root data-slot="dialog" {...rootProps} />
    </DrawerModeContext.Provider>
  );
}

function DialogTrigger({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return <DrawerPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
  }
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return <DrawerPrimitive.Portal data-slot="dialog-portal" {...props} />;
  }
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return <DrawerPrimitive.Close data-slot="dialog-close" {...props} />;
  }
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return (
      <DrawerPrimitive.Overlay
        data-slot="dialog-overlay"
        className={cn(
          "fixed inset-0 z-50 bg-black/30 will-change-[opacity,backdrop-filter] supports-backdrop-filter:backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
          className,
        )}
        {...props}
      />
    );
  }
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 isolate z-50 bg-black/30 duration-100 supports-backdrop-filter:backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
        className,
      )}
      {...props}
    />
  );
}

const BOTTOM_FADE_PX = 15;

// The floating close affordance shared by the padded body and the bare full-bleed
// content: a ghost button pinned to the shell's top-right corner.
function DialogCloseButton() {
  return (
    <DialogClose asChild>
      <Button
        variant="ghost"
        className="absolute top-4 right-4 z-20 bg-secondary"
        size="icon-sm"
      >
        <XIcon />
        <span className="sr-only">Close</span>
      </Button>
    </DialogClose>
  );
}

interface DialogHeaderChrome {
  slot: HTMLElement | null;
  reportHeight: (height: number) => void;
}
// null default = no DialogBody above (standalone DialogHeader renders in place).
const DialogHeaderChromeContext =
  React.createContext<DialogHeaderChrome | null>(null);

// The scroll fills the whole shell; the header is floated over it (measured), so the scroll's fade
// mask sizes to the header and the scrollbar dissolves with the content, like PageScroll.
function DialogBody({
  children,
  showCloseButton,
}: {
  children: React.ReactNode;
  showCloseButton: boolean;
}) {
  const [slot, setSlot] = React.useState<HTMLDivElement | null>(null);
  const [headerHeight, setHeaderHeight] = React.useState(0);
  const chrome = React.useMemo(
    () => ({ slot, reportHeight: setHeaderHeight }),
    [slot],
  );
  // The fade dissolves content into the floated header over twice its height and softens at the
  // bottom, but only on the edge that can still scroll, so a short dialog and the very top and
  // bottom stay crisp.
  const { ref: scrollRef, style: fadeStyle } = useScrollFade<HTMLDivElement>({
    top: `${String(headerHeight * 2)}px`,
    bottom: `${String(BOTTOM_FADE_PX)}px`,
  });

  return (
    <DialogHeaderChromeContext.Provider value={chrome}>
      <div
        ref={scrollRef}
        data-slot="dialog-scroll"
        className="flex min-h-0 w-full flex-1 flex-col overflow-y-auto overscroll-contain px-6 pb-6 [scrollbar-gutter:stable]"
        style={{ ...fadeStyle, paddingTop: headerHeight }}
      >
        {children}
      </div>
      <div ref={setSlot} className="absolute inset-x-0 top-0 z-10" />
      {showCloseButton && <DialogCloseButton />}
    </DialogHeaderChromeContext.Provider>
  );
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  bare = false,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showCloseButton?: boolean;
  // Skip DialogBody's padded scroll and floated-header machinery: the child owns the
  // full-bleed layout (e.g. a self-scrolling log terminal with its own floating header).
  bare?: boolean;
}) {
  const isDrawer = React.useContext(DrawerModeContext);

  // className is the desktop sheet's (widths like sm:max-w-md); the drawer spans the viewport.
  if (isDrawer) {
    return (
      <DrawerContent showHandle={false}>
        <DialogBody showCloseButton={false}>{children}</DialogBody>
      </DrawerContent>
    );
  }

  return (
    <DialogPortal>
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          // iOS-26 sheet: a clipped, rounded shell with a capped height. DialogBody floats the header
          // over the one scroll region, which dissolves content and scrollbar into it.
          "fixed top-1/2 left-1/2 z-50 flex max-h-[75vh] w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-4xl bg-popover text-sm text-popover-foreground shadow-xl ring-1 ring-foreground/5 duration-100 outline-none sm:max-w-md dark:ring-foreground/10 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className,
        )}
        {...props}
      >
        {bare ? (
          <>
            {children}
            {showCloseButton && <DialogCloseButton />}
          </>
        ) : (
          <DialogBody showCloseButton={showCloseButton}>{children}</DialogBody>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({
  className,
  children,
  ...props
}: React.ComponentProps<"div">) {
  // Floated over the scroll by DialogBody. Measures itself and reports its height so the scroll's
  // mask and top padding size to it. In the drawer it also carries the grab handle.
  const chrome = React.useContext(DialogHeaderChromeContext);
  const isDrawer = React.useContext(DrawerModeContext);
  const [node, setNode] = React.useState<HTMLDivElement | null>(null);
  React.useLayoutEffect(() => {
    const report = chrome?.reportHeight;
    if (!report || !node) return;
    const observer = new ResizeObserver(() => report(node.offsetHeight));
    observer.observe(node);
    return () => observer.disconnect();
  }, [chrome, node]);
  const content = (
    <div
      ref={setNode}
      data-slot="dialog-header"
      className={cn(
        "flex flex-col gap-1.5 px-6 pb-4 text-left",
        isDrawer ? "pt-3" : "pt-6",
        className,
      )}
      {...props}
    >
      {isDrawer && (
        <div className="mx-auto mb-1.5 h-1.5 w-[100px] shrink-0 rounded-full bg-muted-foreground/40" />
      )}
      {children}
    </div>
  );
  // Standalone (no DialogBody): render in place. Inside one: portal into its header slot once mounted.
  if (!chrome) return content;
  return chrome.slot ? createPortal(content, chrome.slot) : null;
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean;
}) {
  // Pinned to the bottom with no background of its own: the fade sits behind the buttons
  // (a gradient covering the footer and tailing off above it), so the content dissolves as
  // it scrolls down behind the buttons while they stay crisp on top. Shared by the desktop
  // sheet and the mobile drawer; the close acts through the mode-aware DialogClose.
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "sticky bottom-0 z-10 -mx-6 -mb-6 flex flex-col-reverse gap-2 px-6 pt-4 pb-6 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-5 bottom-0 -z-10 bg-popover/90 backdrop-blur-sm [mask-image:linear-gradient(to_top,black_58%,rgba(0,0,0,0.85)_70%,rgba(0,0,0,0.5)_82%,rgba(0,0,0,0.2)_92%,transparent)]"
      />
      {children}
      {showCloseButton && (
        <DialogClose asChild>
          <Button variant="outline">Close</Button>
        </DialogClose>
      )}
    </div>
  );
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return (
      <DrawerPrimitive.Title
        data-slot="dialog-title"
        className={cn(
          "font-heading text-base font-medium text-foreground",
          className,
        )}
        {...props}
      />
    );
  }
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("font-heading text-lg leading-none font-medium", className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return (
      <DrawerPrimitive.Description
        data-slot="dialog-description"
        className={cn("text-xs text-muted-foreground", className)}
        {...props}
      />
    );
  }
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn(
        "text-xs text-muted-foreground *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
};
