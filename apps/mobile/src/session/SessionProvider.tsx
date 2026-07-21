import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  connectWithKey,
  resumeGatewaySession,
  signInWithVestaAccount,
} from "@/api/auth";
import { createApiClient, type ApiClient } from "@/api/client";
import { parseConnectLink } from "@/api/connection-link";
import type { ConnectionConfig } from "@/api/types";
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

type SessionStatus = "booting" | "disconnected" | "connected";

interface SessionValue {
  status: SessionStatus;
  connection: ConnectionConfig | null;
  api: ApiClient;
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

  const value = useMemo<SessionValue>(
    () => ({
      status,
      connection,
      api,
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
