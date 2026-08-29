"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Drawer as DrawerPrimitive } from "vaul";

import { cn } from "@/lib/utils";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { ScrollShell, ShellChrome } from "@/components/ui/scroll-shell";
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
          "fixed inset-0 z-50 bg-black/50 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
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
        "fixed inset-0 isolate z-50 bg-black/50 duration-100 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
        className,
      )}
      {...props}
    />
  );
}

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

// The dialog sheet's floating scroll shell; it passes its own close button. The drawer path uses
// DrawerContent's own shell instead of this.
function DialogBody({
  children,
  showCloseButton,
}: {
  children: React.ReactNode;
  showCloseButton: boolean;
}) {
  return (
    <ScrollShell
      closeButton={showCloseButton ? <DialogCloseButton /> : undefined}
    >
      {children}
    </ScrollShell>
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
  // DrawerContent brings its own floating shell, so the children (with DialogHeader/DialogFooter)
  // go straight in, and the header carries the grab handle instead of DrawerContent.
  if (isDrawer) {
    return <DrawerContent showHandle={false}>{children}</DrawerContent>;
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
  // Floats over the shell's top (measured so the scroll's mask and top padding size to it). In the
  // drawer it also carries the grab handle.
  const isDrawer = React.useContext(DrawerModeContext);
  return (
    <ShellChrome
      edge="top"
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
    </ShellChrome>
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
  // The mirror of DialogHeader: floats crisp and full-width over the shell's bottom edge. Shared by
  // the desktop sheet and the mobile drawer; the close acts through the mode-aware DialogClose.
  return (
    <ShellChrome
      edge="bottom"
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 px-6 pt-4 pb-6 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    >
      {children}
      {showCloseButton && (
        <DialogClose asChild>
          <Button variant="outline">Close</Button>
        </DialogClose>
      )}
    </ShellChrome>
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
