import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Drawer as DrawerPrimitive } from "vaul";

import { cn } from "@/lib/utils";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { useIsMobile } from "@/hooks/use-mobile";
import { Button } from "@/components/ui/button";
import { DrawerContent } from "@/components/ui/drawer";
import {
  Dialog as UiDialog,
  DialogClose as UiDialogClose,
  DialogContent as UiDialogContent,
  DialogDescription as UiDialogDescription,
  DialogFooter as UiDialogFooter,
  DialogHeader as UiDialogHeader,
  DialogTitle as UiDialogTitle,
} from "@/components/ui/dialog";

// The app's dialog: the stock sheet holding the app scrim (components/Scrim) while open, and with
// `drawerOnMobile` a vaul bottom drawer on phone widths. Every part reads the mode from context, so
// a consumer composes the same DialogHeader/DialogFooter in both.
const DrawerModeContext = React.createContext(false);

function Dialog({
  drawerOnMobile,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root> & {
  drawerOnMobile?: boolean;
}) {
  const isMobile = useIsMobile();
  const isDrawer = !!drawerOnMobile && isMobile;
  // The drawer path keeps vaul's own drag-tracking overlay instead of the scrim.
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
      <UiDialog {...rootProps} />
    </DrawerModeContext.Provider>
  );
}

function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return <DrawerPrimitive.Close data-slot="dialog-close" {...props} />;
  }
  return <UiDialogClose {...props} />;
}

function DialogContent({
  children,
  ...props
}: React.ComponentProps<typeof UiDialogContent>) {
  const isDrawer = React.useContext(DrawerModeContext);
  // className is the desktop sheet's (widths like sm:max-w-md); the drawer spans the viewport.
  // DrawerContent brings its own floating shell, so the children (with DialogHeader/DialogFooter)
  // go straight in, and the header carries the grab handle instead of DrawerContent.
  if (isDrawer) {
    return <DrawerContent showHandle={false}>{children}</DrawerContent>;
  }
  return <UiDialogContent {...props}>{children}</UiDialogContent>;
}

function DialogHeader({
  className,
  children,
  ...props
}: React.ComponentProps<"div">) {
  const isDrawer = React.useContext(DrawerModeContext);
  if (isDrawer) {
    return (
      <UiDialogHeader className={cn("pt-3", className)} {...props}>
        <div className="mx-auto mb-1.5 h-1.5 w-[100px] shrink-0 rounded-full bg-muted-foreground/40" />
        {children}
      </UiDialogHeader>
    );
  }
  return (
    <UiDialogHeader className={className} {...props}>
      {children}
    </UiDialogHeader>
  );
}

function DialogFooter({
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<typeof UiDialogFooter>) {
  // The close acts through the mode-aware DialogClose, so the stock footer's own button stays off.
  return (
    <UiDialogFooter {...props}>
      {children}
      {showCloseButton && (
        <DialogClose asChild>
          <Button variant="outline">Close</Button>
        </DialogClose>
      )}
    </UiDialogFooter>
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
  return <UiDialogTitle className={className} {...props} />;
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
  return <UiDialogDescription className={className} {...props} />;
}

export {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
};
