"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Drawer as DrawerPrimitive } from "vaul";

import { cn } from "@/lib/utils";
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

  if (isDrawer) {
    return (
      <DrawerModeContext.Provider value={true}>
        <DrawerPrimitive.Root data-slot="dialog" {...props} />
      </DrawerModeContext.Provider>
    );
  }

  return (
    <DrawerModeContext.Provider value={false}>
      <DialogPrimitive.Root data-slot="dialog" {...props} />
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
          "fixed inset-0 z-50 bg-black/30 supports-backdrop-filter:backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
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
          className="fixed inset-0 z-50 bg-black/30 supports-backdrop-filter:backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0"
        />
        <DrawerPrimitive.Content
          data-slot="dialog-content"
          className={cn(
            "group/drawer-content fixed inset-x-0 bottom-0 z-50 mt-24 flex h-auto max-h-[80vh] flex-col bg-transparent p-4 text-sm before:absolute before:inset-2 before:-z-10 before:rounded-4xl before:border before:border-border before:bg-popover before:shadow-xl",
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
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-6 rounded-4xl bg-popover p-6 text-sm text-popover-foreground shadow-xl ring-1 ring-foreground/5 duration-100 outline-none sm:max-w-md dark:ring-foreground/10 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className,
        )}
        {...props}
      >
        {children}
        {showCloseButton && (
          <DialogPrimitive.Close data-slot="dialog-close" asChild>
            <Button
              variant="ghost"
              className="absolute top-4 right-4 bg-secondary"
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

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-1.5 text-left", className)}
      {...props}
    />
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
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    >
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
      className={cn(
        "font-heading text-base leading-none font-medium",
        className,
      )}
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
        className={cn("text-sm text-muted-foreground", className)}
        {...props}
      />
    );
  }
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn(
        "text-sm text-muted-foreground *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground",
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
