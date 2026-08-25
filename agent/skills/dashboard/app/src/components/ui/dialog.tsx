"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Drawer as DrawerPrimitive } from "vaul";

import { cn } from "@/lib/utils";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { Button } from "@/components/ui/button";
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

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showCloseButton?: boolean;
}) {
  const isDrawer = React.useContext(DrawerModeContext);

  if (isDrawer) {
    return (
      <DrawerPrimitive.Portal data-slot="dialog-portal">
        <DrawerPrimitive.Overlay
          data-slot="dialog-overlay"
          className="fixed inset-0 z-50 bg-black/30 will-change-[opacity,backdrop-filter] supports-backdrop-filter:backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0"
        />
        <DrawerPrimitive.Content
          data-slot="dialog-content"
          className={cn(
            "group/drawer-content fixed inset-x-0 bottom-0 z-50 mt-24 flex h-auto max-h-[80vh] flex-col bg-transparent p-4 text-sm before:absolute before:inset-x-2 before:top-0 before:-bottom-10 before:-z-10 before:rounded-4xl before:rounded-b-none before:border before:border-b-0 before:border-border before:bg-popover before:shadow-xl",
            className,
          )}
        >
          <div className="mx-auto mt-4 h-1.5 w-[100px] shrink-0 rounded-full bg-muted" />
          <div className="flex flex-col gap-6 p-4 pb-8 overflow-y-auto">
            {children}
          </div>
        </DrawerPrimitive.Content>
      </DrawerPrimitive.Portal>
    );
  }

  return (
    <DialogPortal>
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          // iOS-26 sheet: a clipped, rounded shell with a capped height. The header and footer
          // float (they sit sticky inside the one scroll region below), so the content scrolls
          // edge-to-edge, dissolving under the header's fade and past the bottom mask.
          "fixed top-1/2 left-1/2 z-50 flex max-h-[75vh] w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-4xl bg-popover text-sm text-popover-foreground shadow-xl ring-1 ring-foreground/5 duration-100 outline-none sm:max-w-md dark:ring-foreground/10 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className,
        )}
        {...props}
      >
        <div
          data-slot="dialog-scroll"
          className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-6 pb-6 [mask-image:linear-gradient(to_bottom,black_calc(100%-20px),transparent_calc(100%-1px))]"
        >
          {children}
        </div>
        {showCloseButton && (
          <DialogPrimitive.Close data-slot="dialog-close" asChild>
            <Button
              variant="ghost"
              className="absolute top-4 right-4 z-20 bg-secondary"
              size="icon-sm"
            >
              <XIcon />
              <span className="sr-only">Close</span>
            </Button>
          </DialogPrimitive.Close>
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
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return (
      <div
        data-slot="dialog-header"
        className={cn("flex flex-col gap-1.5 text-left", className)}
        {...props}
      >
        {children}
      </div>
    );
  }
  // Floats over the scrolling content with no background of its own: the fade sits behind the title
  // (a gradient layer covering the header and tailing off below it), so the content dissolves as it
  // scrolls up behind the header while the title stays crisp on top.
  return (
    <div
      data-slot="dialog-header"
      className={cn(
        "sticky top-0 z-10 -mx-6 flex flex-col gap-1.5 px-6 pt-6 pb-4 text-left",
        className,
      )}
      {...props}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -bottom-5 -z-10 bg-popover/90 backdrop-blur-sm [mask-image:linear-gradient(to_bottom,black_58%,rgba(0,0,0,0.85)_70%,rgba(0,0,0,0.5)_82%,rgba(0,0,0,0.2)_92%,transparent)]"
      />
      {children}
    </div>
  );
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean;
}) {
  const isDrawer = React.useContext(DrawerModeContext);

  if (isDrawer) {
    return (
      <div
        data-slot="dialog-footer"
        className={cn("mt-auto flex flex-col gap-2", className)}
        {...props}
      >
        {children}
        {showCloseButton && (
          <DrawerPrimitive.Close asChild>
            <Button variant="outline">Close</Button>
          </DrawerPrimitive.Close>
        )}
      </div>
    );
  }

  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        // Pinned to the bottom with no background of its own: the fade sits behind the buttons
        // (a gradient covering the footer and tailing off above it), so the content dissolves as
        // it scrolls down behind the buttons while they stay crisp on top.
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
        <DialogPrimitive.Close asChild>
          <Button variant="outline">Close</Button>
        </DialogPrimitive.Close>
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
