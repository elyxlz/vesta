import { getConnection } from "@/lib/connection";
import { useGateway } from "@/providers/GatewayProvider";
import { UpdatePill } from "@/components/UpdatePill";

interface StatusPillProps {
  showHostname?: boolean;
}

export function StatusPill({ showHostname = true }: StatusPillProps) {
  const { reachable } = useGateway();

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
        title={reachable ? "connected" : "can't reach gateway"}
        className="inline-flex h-8 items-center gap-2 rounded-4xl px-3"
      >
        <div
          role="img"
          aria-label={reachable ? "connected" : "can't reach gateway"}
          className={`size-2 rounded-full shrink-0 ${reachable ? "bg-green-500" : "bg-red-500"}`}
        />
        {showHostname && hostname && (
          <span className="hidden truncate text-sm text-secondary-foreground sm:block">
            {hostname}
          </span>
        )}
      </div>
      <UpdatePill />
    </div>
  );
}
