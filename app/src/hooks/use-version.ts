import { useEffect } from "react";
import { getConnection } from "@/lib/connection";
import { useAppStore } from "@/stores/use-app-store";

export function useVersion() {
  const connected = useAppStore((s) => s.connected);
  const setVersion = useAppStore((s) => s.setVersion);

  useEffect(() => {
    if (!connected) return;

    const fetchVersion = async () => {
      try {
        const conn = getConnection();
        if (!conn) return;
        const resp = await fetch(`${conn.url}/version`, {
          headers: { Authorization: `Bearer ${conn.apiKey}` },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.version) setVersion(data.version);
      } catch {
        // ignore
      }
    };
    fetchVersion();
  }, [connected, setVersion]);
}
