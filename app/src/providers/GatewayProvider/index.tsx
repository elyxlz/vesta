import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getConnection, authHeaders } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";
import { useAuth } from "@/providers/AuthProvider";
import { VersionMismatchDialog } from "@/components/VersionMismatchDialog";
import type { AgentInfo } from "@/lib/types";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

interface GatewayContextValue {
  reachable: boolean;
  gatewayVersion: string;
  gatewayPort: number;
  versionChecked: boolean;
  agents: AgentInfo[];
  agentsFetched: boolean;
  send: (event: object) => boolean;
}

const GatewayContext = createContext<GatewayContextValue | null>(null);

const disconnectedValue: GatewayContextValue = {
  reachable: false,
  gatewayVersion: "",
  gatewayPort: 0,
  versionChecked: true,
  agents: [],
  agentsFetched: false,
  send: () => false,
};

function controlWsUrl(): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vesta gateway");
  const base = conn.url.replace(/^http/, "ws");
  return `${base}/ws?token=${encodeURIComponent(conn.accessToken)}`;
}

function ConnectedGateway({ children }: { children: ReactNode }) {
  const { loading } = useAuth();
  const [reachable, setReachable] = useState(false);
  const [gatewayVersion, setGatewayVersion] = useState("");
  const [gatewayPort, setGatewayPort] = useState(0);
  const [versionChecked, setVersionChecked] = useState(false);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agentsFetched, setAgentsFetched] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = RECONNECT_BASE_MS;

    const doConnect = async () => {
      if (cancelled) return;

      await ensureFreshToken();

      let url: string;
      try {
        url = controlWsUrl();
      } catch {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
        return;
      }

      // Fetch version early via HTTP before WS connects
      try {
        const conn = getConnection();
        if (conn) {
          const resp = await fetch(`${conn.url}/version`, { headers: authHeaders(), signal: AbortSignal.timeout(5000) });
          if (!cancelled && resp.ok) {
            const data = await resp.json();
            if (data.version) {
              setGatewayVersion(data.version);
              setVersionChecked(true);
              // Skip WS if version mismatch — the dialog will render instead
              if (data.version !== __APP_VERSION__) return;
            }
          }
        }
      } catch {}
      if (!cancelled) setVersionChecked(true);

      if (cancelled) return;

      socket = new WebSocket(url);
      wsRef.current = socket;

      socket.onopen = () => {
        if (cancelled) return;
        reconnectDelay = RECONNECT_BASE_MS;
        setReachable(true);
      };

      socket.onmessage = (e) => {
        if (cancelled) return;
        if (typeof e.data !== "string") return;
        try {
          const msg = JSON.parse(e.data);
          switch (msg.type) {
            case "hello": {
              setGatewayVersion(msg.version ?? "");
              setGatewayPort(msg.port ?? 0);
              break;
            }
            case "agents": {
              setAgents(msg.agents ?? []);
              setAgentsFetched(true);
              break;
            }
          }
        } catch {
          console.warn("ws: bad message", e.data);
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        socket = null;
        wsRef.current = null;
        setReachable(false);
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
      };

      socket.onerror = () => { };
    };

    void doConnect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
      wsRef.current = null;
    };
  }, []);

  const send = (event: object): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(event));
    return true;
  };

  const versionMismatch = !loading && gatewayVersion && gatewayVersion !== __APP_VERSION__;

  return (
    <GatewayContext.Provider
      value={{
        reachable,
        gatewayVersion,
        gatewayPort,
        versionChecked,
        agents,
        agentsFetched,
        send,
      }}
    >
      {versionMismatch
        ? <VersionMismatchDialog gatewayVersion={gatewayVersion} />
        : children}
    </GatewayContext.Provider>
  );
}

export function GatewayProvider({ children }: { children: ReactNode }) {
  const { connected, initialized } = useAuth();

  if (initialized && connected) {
    return <ConnectedGateway>{children}</ConnectedGateway>;
  }

  return (
    <GatewayContext.Provider value={disconnectedValue}>
      {children}
    </GatewayContext.Provider>
  );
}

export function useGateway() {
  const context = useContext(GatewayContext);
  if (!context) {
    throw new Error("useGateway must be used within GatewayProvider");
  }
  return context;
}
