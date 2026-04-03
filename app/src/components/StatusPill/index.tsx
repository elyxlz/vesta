import { getConnection } from "@/lib/connection";

interface StatusPillProps {
  showHostname?: boolean;
}

export function StatusPill({ showHostname = true }: StatusPillProps) {
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
    <div className="flex items-center gap-1.5">
      <div className="size-2 rounded-full bg-green-500 shrink-0" />
      {showHostname && hostname && (
        <span className="text-sm text-foreground truncate hidden sm:block">{hostname}</span>
      )}
    </div>
  );
}
