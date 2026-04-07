import * as React from "react"
import { XIcon } from "lucide-react"
import { Dialog as DialogPrimitive } from "radix-ui"
import { Drawer as DrawerPrimitive } from "vaul"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { useIsMobile } from "@/hooks/use-mobile"

interface DialogModeValue {
  mode: "dialog" | "drawer"
  responsive: boolean
}

const DialogModeContext = React.createContext<DialogModeValue>({ mode: "dialog", responsive: false })

function Dialog({
  drawerOnMobile,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root> & {
  drawerOnMobile?: boolean
}) {
  const isMobile = useIsMobile()
  const isDrawer = drawerOnMobile && isMobile
  const ctx = React.useMemo<DialogModeValue>(
    () => ({ mode: isDrawer ? "drawer" : "dialog", responsive: !!drawerOnMobile }),
    [isDrawer, drawerOnMobile],
  )

  return (
    <DialogModeContext.Provider value={ctx}>
      {isDrawer ? (
        <DrawerPrimitive.Root data-slot="dialog" {...props} />
      ) : (
        <DialogPrimitive.Root data-slot="dialog" {...props} />
      )}
    </DialogModeContext.Provider>
  )
}

function DialogTrigger({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  const { mode } = React.useContext(DialogModeContext)
  if (mode === "drawer") {
    return <DrawerPrimitive.Trigger data-slot="dialog-trigger" {...(props as React.ComponentProps<typeof DrawerPrimitive.Trigger>)} />
  }
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  const { mode } = React.useContext(DialogModeContext)
  if (mode === "drawer") {
    return <DrawerPrimitive.Portal data-slot="dialog-portal" {...(props as React.ComponentProps<typeof DrawerPrimitive.Portal>)} />
  }
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  const { mode } = React.useContext(DialogModeContext)
  if (mode === "drawer") {
    return <DrawerPrimitive.Close data-slot="dialog-close" {...(props as React.ComponentProps<typeof DrawerPrimitive.Close>)} />
  }
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  const { mode } = React.useContext(DialogModeContext)
  if (mode === "drawer") {
    return (
      <DrawerPrimitive.Overlay
        data-slot="dialog-overlay"
        className={cn("fixed inset-0 z-50 bg-black/50", className)}
        {...(props as React.ComponentProps<typeof DrawerPrimitive.Overlay>)}
      />
    )
  }
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/50 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0",
        className
      )}
      {...props}
    />
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showCloseButton?: boolean
}) {
  const { mode, responsive } = React.useContext(DialogModeContext)

  if (mode === "drawer") {
    return (
      <DrawerPrimitive.Portal data-slot="dialog-portal">
        <DrawerPrimitive.Overlay
          data-slot="dialog-overlay"
          className="fixed inset-0 z-50 bg-black/50"
        />
        <DrawerPrimitive.Content
          data-slot="dialog-content"
          className="group/drawer-content fixed inset-x-0 bottom-0 z-50 mt-24 flex h-auto max-h-[80vh] flex-col rounded-t-lg border-t bg-background"
        >
          <div className="mx-auto mt-4 h-2 w-[100px] shrink-0 rounded-full bg-muted" />
          <div className="flex flex-col gap-4 overflow-y-auto p-6">
            {children}
          </div>
        </DrawerPrimitive.Content>
      </DrawerPrimitive.Portal>
    )
  }

  return (
    <DialogPortal data-slot="dialog-portal">
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "fixed top-[50%] left-[50%] z-50 grid w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-lg border bg-background p-6 shadow-lg duration-200 outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
          responsive ? "lg:max-w-lg" : "sm:max-w-lg",
          className
        )}
        {...props}
      >
        {children}
        {showCloseButton && (
          <DialogPrimitive.Close
            data-slot="dialog-close"
            className="absolute top-4 right-4 rounded-xs opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
          >
            <XIcon />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    />
  )
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean
}) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className
      )}
      {...props}
    >
      {children}
      {showCloseButton && (
        <DialogClose asChild>
          <Button variant="outline">Close</Button>
        </DialogClose>
      )}
    </div>
  )
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  const { mode } = React.useContext(DialogModeContext)
  if (mode === "drawer") {
    return (
      <DrawerPrimitive.Title
        data-slot="dialog-title"
        className={cn("text-lg leading-none font-semibold", className)}
        {...(props as React.ComponentProps<typeof DrawerPrimitive.Title>)}
      />
    )
  }
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-lg leading-none font-semibold", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  const { mode } = React.useContext(DialogModeContext)
  if (mode === "drawer") {
    return (
      <DrawerPrimitive.Description
        data-slot="dialog-description"
        className={cn("text-sm text-muted-foreground", className)}
        {...(props as React.ComponentProps<typeof DrawerPrimitive.Description>)}
      />
    )
  }
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
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
}
