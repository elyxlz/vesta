import { Button } from "@/components/ui/button";

interface VersionMismatchDialogProps {
  gatewayVersion: string;
}

export function VersionMismatchDialog({
  gatewayVersion,
}: VersionMismatchDialogProps) {
  return (
    <div className="fixed inset-0 z-[100000] flex items-center justify-center bg-black/30 supports-backdrop-filter:backdrop-blur-sm">
      <div className="grid w-full max-w-xs gap-6 rounded-4xl bg-popover p-6 text-popover-foreground shadow-xl ring-1 ring-foreground/5 sm:max-w-md dark:ring-foreground/10">
        <div className="grid place-items-center gap-1.5 text-center">
          <h2 className="font-heading text-lg font-medium">
            Version Mismatch
          </h2>
          <p className="text-sm text-balance text-muted-foreground">
            This app is v{__APP_VERSION__} but the gateway is v{gatewayVersion}.
            Please update to continue.
          </p>
        </div>
        <div className="flex justify-end">
          <Button>Update</Button>
        </div>
      </div>
    </div>
  );
}
