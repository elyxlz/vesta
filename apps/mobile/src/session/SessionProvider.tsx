import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { AppState } from "react-native";
import { useQueryClient } from "@tanstack/react-query";
import Constants from "expo-constants";
import {
  connectWithKey,
  resumeGatewaySession,
  signInWithVestaAccount,
} from "@/api/auth";
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
import type { RecentGateway } from "@/storage/recent-gateway-model";
import {
  clearRecentGateways as clearStoredRecentGateways,
  forgetRecentGateway as forgetStoredRecentGateway,
  readRecentGatewayCredential,
  readRecentGateways,
  saveRecentGateway,
} from "@/storage/recent-gateways";
import { changesGateway } from "@/session/session-model";

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
  recentGateways: RecentGateway[] | null;
  refreshAccessToken: () => Promise<boolean>;
  connectLink: (link: string) => Promise<void>;
  connectRecentGateway: (id: string) => Promise<void>;
  forgetRecentGateway: (id: string) => Promise<void>;
  clearRecentGateways: () => Promise<void>;
  signIn: () => Promise<boolean>;
  disconnect: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

interface CommitConnectionOptions {
  connectKey?: string;
  touchRecent?: boolean;
}

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
  const queryClient = useQueryClient();
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
  const [recentGateways, setRecentGateways] = useState<RecentGateway[] | null>(
    null,
  );
  const [connectionStore] = useState(() => new ConnectionStore());

  const commitConnection = useCallback(
    async (
      next: ConnectionConfig,
      options: CommitConnectionOptions = {},
    ): Promise<void> => {
      const current = connectionStore.read();
      if (changesGateway(current, next)) {
        queryClient.clear();
        setAgents([]);
        setAgentsReady(false);
      }
      await writeConnection(next);
      connectionStore.write(next);
      setConnection(next);
      setStatus("connected");
      void saveRecentGateway(next, {
        connectKey: options.connectKey,
        touch: options.touchRecent ?? false,
      })
        .then(setRecentGateways)
        .catch((cause: unknown) =>
          console.warn("Could not save recent gateway:", cause),
        );
    },
    [connectionStore, queryClient],
  );

  const disconnect = useCallback(async (): Promise<void> => {
    queryClient.clear();
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
  }, [connectionStore, queryClient]);

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

    const restoreSession = async () => {
      let stored: ConnectionConfig | null = null;
      try {
        stored = await readConnection();
      } catch (cause) {
        console.warn("Could not load the active gateway:", cause);
      }
      if (!active) return;

      connectionStore.write(stored);
      setConnection(stored);
      setStatus(stored ? "connected" : "disconnected");

      try {
        const recent = stored
          ? await saveRecentGateway(stored, { touch: false })
          : await readRecentGateways();
        if (active) setRecentGateways(recent);
      } catch (cause) {
        console.warn("Could not load recent gateways:", cause);
        if (active) setRecentGateways([]);
      }
    };

    void restoreSession();
    return () => {
      active = false;
    };
  }, [connectionStore]);

  const connectLink = useCallback(
    async (link: string): Promise<void> => {
      const parsed = parseConnectLink(link);
      if (!parsed.ok) throw new Error(parsed.message);
      await commitConnection(await connectWithKey(parsed.url, parsed.key), {
        connectKey: parsed.key,
        touchRecent: true,
      });
    },
    [commitConnection],
  );

  const connectRecentGateway = useCallback(
    async (id: string): Promise<void> => {
      const credential = await readRecentGatewayCredential(id);
      if (!credential) {
        setRecentGateways(await forgetStoredRecentGateway(id));
        throw new Error("This saved gateway is no longer available.");
      }
      let next = credential.connection;
      if (credential.connectKey && !credential.connection.hosted) {
        next = await connectWithKey(
          credential.connection.url,
          credential.connectKey,
        );
      } else {
        next = await resumeGatewaySession(credential.connection);
      }
      await commitConnection(next, {
        connectKey: credential.connectKey,
        touchRecent: true,
      });
    },
    [commitConnection],
  );

  const forgetRecentGateway = useCallback(async (id: string): Promise<void> => {
    setRecentGateways(await forgetStoredRecentGateway(id));
  }, []);

  const clearRecentGateways = useCallback(async (): Promise<void> => {
    await clearStoredRecentGateways();
    setRecentGateways([]);
  }, []);

  const signIn = useCallback(async (): Promise<boolean> => {
    const connection = await signInWithVestaAccount();
    if (!connection) return false;
    await commitConnection(connection, {
      touchRecent: true,
    });
    return true;
  }, [commitConnection]);

  useEffect(() => {
    if (!connection) return;

    let active = true;
    let socket: WebSocket | null = null;
    let gatewayLoad: AbortController | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = INITIAL_RECONNECT_MS;
    let appActive = AppState.currentState === "active";

    const closeSocket = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      gatewayLoad?.abort();
      gatewayLoad = null;
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

    const loadGateway = async (signal: AbortSignal): Promise<boolean> => {
      try {
        const [versionInfo, info] = await Promise.all([
          api.json<GatewayVersionInfo>("/version", { signal }),
          api.json<{ managed?: boolean }>("/info", { signal }).catch(() => ({
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
      if (!active || !appActive || socket || gatewayLoad) return;
      const controller = new AbortController();
      gatewayLoad = controller;
      void loadGateway(controller.signal)
        .then((compatible) => {
          if (!active || !appActive || socket || controller.signal.aborted) {
            return;
          }
          if (!compatible) {
            return;
          }
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
                    ? {
                        ...current,
                        version: message.version ?? current.version,
                      }
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
        })
        .finally(() => {
          if (gatewayLoad === controller) gatewayLoad = null;
        });
    };

    const appStateSubscription = AppState.addEventListener(
      "change",
      (nextState) => {
        const nextAppActive = nextState === "active";
        appActive = nextAppActive;
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
      recentGateways,
      refreshAccessToken: api.forceRefresh,
      connectLink,
      connectRecentGateway,
      forgetRecentGateway,
      clearRecentGateways,
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
      recentGateways,
      connectLink,
      connectRecentGateway,
      forgetRecentGateway,
      clearRecentGateways,
      signIn,
      disconnect,
    ],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = use(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}
