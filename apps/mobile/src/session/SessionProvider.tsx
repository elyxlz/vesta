import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { AppState } from "react-native";
import Constants from "expo-constants";
import { connectWithKey, signInWithVestaAccount } from "@/api/auth";
import { createApiClient, type ApiClient } from "@/api/client";
import { parseConnectLink } from "@/api/connection-link";
import type {
  AgentInfo,
  ConnectionConfig,
  ControlWsMessage,
  GatewayVersionInfo,
} from "@/api/types";
import {
  clearConnection as clearStoredConnection,
  readConnection,
  writeConnection,
} from "@/storage/connection";

const RECONNECT_MAX_MS = 30_000;
const INITIAL_RECONNECT_MS = 750;

type SessionStatus = "booting" | "disconnected" | "connected";

interface CompatibilityState {
  compatible: boolean;
  gateway: string;
  supported: string;
}

interface SessionValue {
  status: SessionStatus;
  connection: ConnectionConfig | null;
  api: ApiClient;
  agents: AgentInfo[];
  agentsReady: boolean;
  reachable: boolean;
  managed: boolean;
  version: GatewayVersionInfo | null;
  compatibility: CompatibilityState | null;
  connectLink: (link: string) => Promise<void>;
  signIn: () => Promise<void>;
  disconnect: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

class ConnectionStore {
  private connection: ConnectionConfig | null = null;

  read(): ConnectionConfig | null {
    return this.connection;
  }

  write(connection: ConnectionConfig | null): void {
    this.connection = connection;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("booting");
  const [connection, setConnection] = useState<ConnectionConfig | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agentsReady, setAgentsReady] = useState(false);
  const [reachable, setReachable] = useState(false);
  const [managed, setManaged] = useState(false);
  const [version, setVersion] = useState<GatewayVersionInfo | null>(null);
  const [compatibility, setCompatibility] = useState<CompatibilityState | null>(
    null,
  );
  const [connectionStore] = useState(() => new ConnectionStore());

  const commitConnection = useCallback(
    async (next: ConnectionConfig): Promise<void> => {
      const current = connectionStore.read();
      if (
        !current ||
        current.url !== next.url ||
        current.hosted !== next.hosted
      ) {
        setAgents([]);
        setAgentsReady(false);
      }
      connectionStore.write(next);
      setConnection(next);
      setStatus("connected");
      await writeConnection(next);
    },
    [connectionStore],
  );

  const disconnect = useCallback(async (): Promise<void> => {
    connectionStore.write(null);
    setConnection(null);
    setAgents([]);
    setAgentsReady(false);
    setReachable(false);
    setManaged(false);
    setVersion(null);
    setCompatibility(null);
    setStatus("disconnected");
    await clearStoredConnection();
  }, [connectionStore]);

  const api = useMemo(
    () =>
      createApiClient({
        getConnection: () => connectionStore.read(),
        onConnectionChange: commitConnection,
        onSessionExpired: disconnect,
      }),
    [commitConnection, connectionStore, disconnect],
  );

  useEffect(() => {
    let active = true;
    void readConnection().then((stored) => {
      if (!active) return;
      connectionStore.write(stored);
      setConnection(stored);
      setStatus(stored ? "connected" : "disconnected");
    });
    return () => {
      active = false;
    };
  }, [connectionStore]);

  const connectLink = useCallback(
    async (link: string): Promise<void> => {
      const parsed = parseConnectLink(link);
      if (!parsed.ok) throw new Error(parsed.message);
      await commitConnection(await connectWithKey(parsed.url, parsed.key));
    },
    [commitConnection],
  );

  const signIn = useCallback(async (): Promise<void> => {
    await commitConnection(await signInWithVestaAccount());
  }, [commitConnection]);

  useEffect(() => {
    if (!connection) return;

    let active = true;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = INITIAL_RECONNECT_MS;
    let appActive = AppState.currentState === "active";

    const closeSocket = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      socket?.close();
      socket = null;
      setReachable(false);
    };

    const scheduleReconnect = () => {
      if (!active || !appActive || reconnectTimer) return;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectControlSocket();
      }, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    };

    const loadGateway = async (): Promise<boolean> => {
      try {
        const [versionInfo, info] = await Promise.all([
          api.json<GatewayVersionInfo>("/version"),
          api.json<{ managed?: boolean }>("/info").catch(() => ({
            managed: false,
          })),
        ]);
        if (!active) return false;
        setVersion(versionInfo);
        setManaged(info.managed === true);
        const supported = String(
          Constants.expoConfig?.extra?.apiCompat ?? "0.2",
        );
        const nextCompatibility: CompatibilityState = {
          compatible: versionInfo.api_compat === supported,
          gateway: versionInfo.api_compat,
          supported,
        };
        setCompatibility(nextCompatibility);
        return nextCompatibility.compatible;
      } catch {
        return true;
      }
    };

    const connectControlSocket = () => {
      if (!active || !appActive || socket) return;
      void loadGateway().then((compatible) => {
        if (!active || !appActive || !compatible || socket) return;
        const next = new WebSocket(api.websocketUrl("/ws"));
        socket = next;
        next.onopen = () => {
          reconnectDelay = INITIAL_RECONNECT_MS;
          setReachable(true);
        };
        next.onmessage = (event) => {
          if (typeof event.data !== "string") return;
          try {
            const message: ControlWsMessage = JSON.parse(event.data);
            if (message.type === "hello") {
              setVersion((current) =>
                current
                  ? { ...current, version: message.version ?? current.version }
                  : current,
              );
            } else if (message.type === "agents") {
              setAgents(message.agents ?? []);
              setAgentsReady(true);
            }
          } catch {
            // Ignore an invalid gateway frame and keep the healthy socket open.
          }
        };
        next.onerror = () => next.close();
        next.onclose = () => {
          if (socket === next) socket = null;
          setReachable(false);
          scheduleReconnect();
        };
      });
    };

    const appStateSubscription = AppState.addEventListener(
      "change",
      (nextState) => {
        appActive = nextState === "active";
        if (appActive) connectControlSocket();
        else closeSocket();
      },
    );

    connectControlSocket();
    return () => {
      active = false;
      appStateSubscription.remove();
      closeSocket();
    };
  }, [api, connection]);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      connection,
      api,
      agents,
      agentsReady,
      reachable,
      managed,
      version,
      compatibility,
      connectLink,
      signIn,
      disconnect,
    }),
    [
      status,
      connection,
      api,
      agents,
      agentsReady,
      reachable,
      managed,
      version,
      compatibility,
      connectLink,
      signIn,
      disconnect,
    ],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}
