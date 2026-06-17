import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { apiFetch, apiJson } from "@/api/client";
import { getConnection } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";
import { useAuth } from "@/providers/AuthProvider";
import { VersionMismatchDialog } from "@/components/VersionMismatchDialog";
import { DisconnectedOverlay } from "@/components/DisconnectedOverlay";
import type {
  AgentInfo,
  GatewayVersionInfo,
  ReleaseChannel,
} from "@/lib/types";

const VERSION_FETCH_TIMEOUT_MS = 5000;
// A manual check fetches from GitHub server-side, so allow longer than the
// cached /version read (vestad's own fetch timeout is 10s).
const VERSION_CHECK_TIMEOUT_MS = 15000;

async function fetchVersionInfo(): Promise<GatewayVersionInfo | null> {
  try {
    return await apiJson<GatewayVersionInfo>("/version", {
      signal: AbortSignal.timeout(VERSION_FETCH_TIMEOUT_MS),
    });
  } catch {
    return null;
  }
}

/**
 * Whether this box is a hosted (vesta.run-managed) instance — the unauthenticated
 * `/info` flag the control plane sets via cloud-init. The app uses it to surface
 * the hosted account/billing page; a self-hosted box reports `false`.
 */
async function fetchManaged(): Promise<boolean> {
  try {
    const data = await apiJson<{ managed?: boolean }>("/info", {
      signal: AbortSignal.timeout(VERSION_FETCH_TIMEOUT_MS),
    });
    return data.managed === true;
  } catch {
    return false;
  }
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

const VERSION_POLL_MS = 60000;

// Brief grace before the disconnect overlay appears, so quick WS blips and the
// gap between the initial version fetch and the first socket open don't flash it.
const DISCONNECT_GRACE_MS = 750;

interface GatewayContextValue {
  reachable: boolean;
  /** True iff this is a hosted (vesta.run-managed) box — gates the account link. */
  managed: boolean;
  gatewayVersion: string;
  gatewayBranch: string | null;
  gatewayChannel: ReleaseChannel;
  gatewayAutoUpdate: boolean;
  gatewayPort: number;
  versionChecked: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
  agents: AgentInfo[];
  agentsFetched: boolean;
  send: (event: object) => boolean;
  triggerGatewayUpdate: () => Promise<boolean>;
  checkForUpdate: () => Promise<void>;
}

const GatewayContext = createContext<GatewayContextValue | null>(null);

const disconnectedValue: GatewayContextValue = {
  reachable: false,
  managed: false,
  gatewayVersion: "",
  gatewayBranch: null,
  gatewayChannel: "stable",
  gatewayAutoUpdate: true,
  gatewayPort: 0,
  versionChecked: true,
  updateAvailable: false,
  latestVersion: null,
  agents: [],
  agentsFetched: false,
  send: () => false,
  triggerGatewayUpdate: async () => false,
  checkForUpdate: async () => {},
};

function controlWsUrl(): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vesta gateway");
  const base = conn.url.replace(/^http/, "ws");
  return `${base}/ws?token=${encodeURIComponent(conn.accessToken)}`;
}

function ConnectedGateway({ children }: { children: ReactNode }) {
  const { loading, expireSession } = useAuth();
  const [reachable, setReachable] = useState(false);
  const [managed, setManaged] = useState(false);
  const [gatewayVersion, setGatewayVersion] = useState("");
  const [gatewayBranch, setGatewayBranch] = useState<string | null>(null);
  const [gatewayChannel, setGatewayChannel] =
    useState<ReleaseChannel>("stable");
  const [gatewayAutoUpdate, setGatewayAutoUpdate] = useState(true);
  const [gatewayPort, setGatewayPort] = useState(0);

  const [versionChecked, setVersionChecked] = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agentsFetched, setAgentsFetched] = useState(false);
  const [lastConnectAttempt, setLastConnectAttempt] = useState<number | null>(
    null,
  );
  const [showDisconnected, setShowDisconnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const [connectEpoch, setConnectEpoch] = useState(0);
  const skipVersionGateRef = useRef(false);

  const triggerGatewayUpdate = async (): Promise<boolean> => {
    try {
      await apiFetch("/gateway/update", { method: "POST" });
    } catch (err) {
      console.warn("[gateway] update request failed:", err);
      return false;
    }
    skipVersionGateRef.current = true;
    setConnectEpoch((e) => e + 1);
    return true;
  };

  const checkForUpdate = async () => {
    try {
      const data = await apiJson<GatewayVersionInfo>("/version/check", {
        method: "POST",
        signal: AbortSignal.timeout(VERSION_CHECK_TIMEOUT_MS),
      });
      setUpdateAvailable(!!data.update_available);
      setLatestVersion(data.latest_version ?? null);
      setGatewayChannel(data.channel ?? "stable");
      setGatewayAutoUpdate(data.auto_update ?? true);
    } catch (err) {
      console.warn("[gateway] update check request failed:", err);
    }
  };

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = RECONNECT_BASE_MS;

    const doConnect = async () => {
      if (cancelled) return;
      setLastConnectAttempt(Date.now());

      // A dead session (refresh token expired/revoked) can never reconnect:
      // bail out to the connect screen instead of retrying forever with a
      // token vestad will keep rejecting. Transient failures keep the loop.
      if ((await ensureFreshToken()) === "expired") {
        if (!cancelled) expireSession();
        return;
      }

      let url: string;
      try {
        url = controlWsUrl();
      } catch {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
        return;
      }

      // Fetch version early via HTTP before WS connects
      const data = await fetchVersionInfo();
      if (!cancelled && data?.version) {
        setGatewayVersion(data.version);
        setGatewayBranch(data.branch ?? null);
        setGatewayChannel(data.channel ?? "stable");
        setGatewayAutoUpdate(data.auto_update ?? true);
        setUpdateAvailable(!!data.update_available);
        setLatestVersion(data.latest_version ?? null);
        setVersionChecked(true);
        if (data.version !== __APP_VERSION__ && !skipVersionGateRef.current)
          return;
      }
      if (!cancelled) setVersionChecked(true);

      // Hosted vs self-hosted — non-blocking, never gates the connection.
      void fetchManaged().then((m) => {
        if (!cancelled) setManaged(m);
      });

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
              skipVersionGateRef.current = false;
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

      socket.onerror = () => {};
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
  }, [connectEpoch, expireSession]);

  useEffect(() => {
    if (!reachable) return;
    let cancelled = false;

    const pollVersion = async () => {
      const data = await fetchVersionInfo();
      if (cancelled || !data) return;
      setUpdateAvailable(!!data.update_available);
      setLatestVersion(data.latest_version ?? null);
      setGatewayChannel(data.channel ?? "stable");
      setGatewayAutoUpdate(data.auto_update ?? true);
    };

    const timer = setInterval(pollVersion, VERSION_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [reachable]);

  // Surface a blocking overlay once the gateway has been unreachable past a
  // brief grace period, and dismiss it the moment it reconnects. The grace
  // avoids flashing on quick reconnects and during initial connect, where
  // `reachable` is false until the first socket opens.
  useEffect(() => {
    if (loading || reachable) {
      setShowDisconnected(false);
      return;
    }
    const timer = setTimeout(
      () => setShowDisconnected(true),
      DISCONNECT_GRACE_MS,
    );
    return () => clearTimeout(timer);
  }, [loading, reachable]);

  const send = (event: object): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(event));
    return true;
  };

  const versionMismatch =
    !loading && gatewayVersion && gatewayVersion !== __APP_VERSION__;

  return (
    <GatewayContext.Provider
      value={{
        reachable,
        managed,
        gatewayVersion,
        gatewayBranch,
        gatewayChannel,
        gatewayAutoUpdate,
        gatewayPort,
        versionChecked,
        updateAvailable,
        latestVersion,
        agents,
        agentsFetched,
        send,
        triggerGatewayUpdate,
        checkForUpdate,
      }}
    >
      {versionMismatch ? (
        <VersionMismatchDialog
          gatewayVersion={gatewayVersion}
          onUpdateGateway={triggerGatewayUpdate}
        />
      ) : (
        children
      )}
      {showDisconnected && (
        <DisconnectedOverlay lastAttempt={lastConnectAttempt} />
      )}
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
