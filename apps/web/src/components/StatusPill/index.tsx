import { useState } from "react";
import { getConnection } from "@/lib/connection";
import { useGateway } from "@/providers/GatewayProvider";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

interface StatusPillProps {
  showHostname?: boolean;
}

export function StatusPill({ showHostname = true }: StatusPillProps) {
  const { reachable, updateAvailable, latestVersion, triggerGatewayUpdate } =
    useGateway();
  const [updating, setUpdating] = useState(false);

  const handleUpdate = () => {
    setUpdating(true);
    triggerGatewayUpdate();
  };

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

  return (
    <div className="flex items-center gap-2">
      <div
        className={`size-2 rounded-full shrink-0 ${reachable ? "bg-green-500" : "bg-red-500"}`}
      />
      {showHostname && hostname && (
        <span className="text-sm text-secondary-foreground truncate hidden sm:block">
          {hostname}
        </span>
      )}
      {updateAvailable && (
        <Button
          size="xs"
          onClick={handleUpdate}
          disabled={updating}
          title={
            latestVersion ? `Update to v${latestVersion}` : "Update available"
          }
        >
          {updating && <Spinner className="size-3" />}
          update
        </Button>
      )}
    </div>
  );
}
