import { useState } from "react";
import { useGateway } from "@/providers/GatewayProvider/context";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

// Renders nothing unless the gateway reports an available update, so call sites
// can drop it wherever the pill should surface without re-checking the flag.
export function UpdatePill({ className }: { className?: string }) {
  const { updateAvailable, latestVersion, triggerGatewayUpdate } = useGateway();
  const [updating, setUpdating] = useState(false);

  if (!updateAvailable) return null;

  const handleUpdate = async () => {
    setUpdating(true);
    const ok = await triggerGatewayUpdate();
    if (!ok) setUpdating(false);
  };

  return (
    <Button
      size="xs"
      onClick={() => {
        void handleUpdate();
      }}
      disabled={updating}
      className={className}
      title={latestVersion ? `Update to v${latestVersion}` : "Update available"}
    >
      {updating && <Spinner className="size-3" />}
      update
    </Button>
  );
}
