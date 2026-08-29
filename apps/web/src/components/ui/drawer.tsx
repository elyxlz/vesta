import * as React from "react";
import { Drawer as DrawerPrimitive } from "vaul";

import { cn } from "@/lib/utils";
import { ScrollShell, ShellChrome } from "@/components/ui/scroll-shell";

function Drawer({
  shouldScaleBackground = false,
  noBodyStyles = true,
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Root>) {
  return (
    <DrawerPrimitive.Root
      data-slot="drawer"
      shouldScaleBackground={shouldScaleBackground}
      noBodyStyles={noBodyStyles}
      {...props}
    />
  );
}

function DrawerTrigger({
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Trigger>) {
  return <DrawerPrimitive.Trigger data-slot="drawer-trigger" {...props} />;
}

function DrawerPortal({
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Portal>) {
  return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />;
}

function DrawerClose({
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Close>) {
  return <DrawerPrimitive.Close data-slot="drawer-close" {...props} />;
}

function DrawerOverlay({
  className,
  onPointerDown,
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Overlay>) {
  return (
    <DrawerPrimitive.Overlay
      data-slot="drawer-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-background/70 dark:bg-background/55 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
        className,
      )}
      onPointerDown={(e) => {
        onPointerDown?.(e);
        // Close on pointer down instead of waiting for click
        const close = (e.target as HTMLElement).closest(
          "[data-slot=drawer-overlay]",
        );
        if (close instanceof HTMLElement) close.click();
      }}
      {...props}
    />
  );
}

function DrawerContent({
  className,
  children,
  container,
  showHandle = true,
  bare = false,
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Content> & {
  container?: Element | null;
  // Off when a consumer floats the handle inside its own sticky header instead
  // (the Dialog drawer path), so content scrolls flush under handle and title.
  showHandle?: boolean;
  // Skip the floating scroll shell: the child owns its own scroll and layout (the sidebar, a menu
  // that caps its own height). Every other drawer gets the floating header/footer + edge fades.
  bare?: boolean;
}) {
  return (
    <DrawerPortal data-slot="drawer-portal" container={container}>
      <DrawerOverlay />
      <DrawerPrimitive.Content
        data-slot="drawer-content"
        className={cn(
          // The content element IS the sheet surface, so overflow-hidden clips children to the
          // squircle instead of the old inset before-layer they could spill past.
          "group/drawer-content fixed z-50 flex h-auto flex-col overflow-hidden rounded-squircle-md [corner-shape:squircle] bg-popover text-sm ring-1 ring-(color:--card-ring) data-[vaul-drawer-direction=bottom]:inset-x-2 data-[vaul-drawer-direction=bottom]:bottom-2 data-[vaul-drawer-direction=bottom]:mt-24 data-[vaul-drawer-direction=bottom]:max-h-[80vh] data-[vaul-drawer-direction=left]:inset-y-2 data-[vaul-drawer-direction=left]:left-2 data-[vaul-drawer-direction=left]:w-3/4 data-[vaul-drawer-direction=right]:inset-y-2 data-[vaul-drawer-direction=right]:right-2 data-[vaul-drawer-direction=right]:w-3/4 data-[vaul-drawer-direction=top]:inset-x-2 data-[vaul-drawer-direction=top]:top-2 data-[vaul-drawer-direction=top]:mb-24 data-[vaul-drawer-direction=top]:max-h-[80vh] data-[vaul-drawer-direction=left]:sm:max-w-sm data-[vaul-drawer-direction=right]:sm:max-w-sm",
          className,
        )}
        {...props}
      >
        {bare ? (
          <>
            {showHandle && <DrawerHandle />}
            {children}
          </>
        ) : (
          <ScrollShell>
            {showHandle && <DrawerHandle />}
            {children}
          </ScrollShell>
        )}
      </DrawerPrimitive.Content>
    </DrawerPortal>
  );
}

// The grab handle floats over the shell's top (bottom drawers only), measured so the scroll reserves
// its height and content dissolves beneath it while scrolling flush to the edge. In a bare drawer it
// renders in normal flow above the content.
function DrawerHandle() {
  return (
    <ShellChrome
      edge="top"
      className="hidden w-full py-5 shrink-0 cursor-grab items-center justify-center active:cursor-grabbing group-data-[vaul-drawer-direction=bottom]/drawer-content:flex"
    >
      <div className="h-1.5 w-[100px] rounded-full bg-muted-foreground/40" />
    </ShellChrome>
  );
}

function DrawerHeader({ className, ...props }: React.ComponentProps<"div">) {
  // Floats over the shell's top when inside a floating DrawerContent, and renders in place inside a
  // bare drawer.
  return (
    <ShellChrome
      edge="top"
      data-slot="drawer-header"
      className={cn(
        "flex flex-col gap-0.5 p-4 group-data-[vaul-drawer-direction=bottom]/drawer-content:text-center group-data-[vaul-drawer-direction=top]/drawer-content:text-center md:gap-1.5 md:text-left",
        className,
      )}
      {...props}
    />
  );
}

function DrawerFooter({ className, ...props }: React.ComponentProps<"div">) {
  // The mirror of DrawerHeader: floats over the shell's bottom, or pins to the bottom in normal flow
  // (mt-auto) inside a bare drawer.
  return (
    <ShellChrome
      edge="bottom"
      data-slot="drawer-footer"
      className={cn("mt-auto flex flex-col gap-2 p-4", className)}
      {...props}
    />
  );
}

function DrawerTitle({
  className,
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Title>) {
  return (
    <DrawerPrimitive.Title
      data-slot="drawer-title"
      className={cn(
        "font-heading text-base font-medium text-foreground",
        className,
      )}
      {...props}
    />
  );
}

function DrawerDescription({
  className,
  ...props
}: React.ComponentProps<typeof DrawerPrimitive.Description>) {
  return (
    <DrawerPrimitive.Description
      data-slot="drawer-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Drawer,
  DrawerPortal,
  DrawerOverlay,
  DrawerTrigger,
  DrawerClose,
  DrawerContent,
  DrawerHeader,
  DrawerFooter,
  DrawerTitle,
  DrawerDescription,
};
