import { createContext, use, useMemo, type ReactNode } from "react";
import * as Linking from "expo-linking";
import { createApiClient } from "../../src/api/client";
import type { ConnectionConfig } from "../../src/api/types";
import {
  SessionProvider as ProductionSessionProvider,
  useSession as useProductionSession,
} from "../../src/session/SessionProvider";

type SessionValue = ReturnType<typeof useProductionSession>;

const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;
const startsConnected = query?.visualSession === "connected";
const visualConnection: ConnectionConfig = {
  url: "https://home.vesta.run",
  accessToken: "visual-access-token",
  refreshToken: "visual-refresh-token",
  expiresAt: Date.UTC(2030, 0, 1),
  hosted: true,
};
const FixtureContext = createContext<SessionValue | null>(null);

function FixtureProvider({ children }: { children: ReactNode }) {
  const value = useMemo<SessionValue | null>(() => {
    if (!startsConnected) return null;
    const api = createApiClient({
      getConnection: () => visualConnection,
      onConnectionChange: async () => undefined,
      onSessionExpired: async () => undefined,
    });
    return {
      status: "connected",
      connection: visualConnection,
      api,
      recentGateways: [],
      refreshAccessToken: async () => true,
      connectLink: async () => undefined,
      connectRecentGateway: async () => undefined,
      forgetRecentGateway: async () => undefined,
      clearRecentGateways: async () => undefined,
      signIn: async () => true,
      disconnect: async () => undefined,
    };
  }, []);

  return (
    <FixtureContext.Provider value={value}>{children}</FixtureContext.Provider>
  );
}

export function SessionProvider({ children }: { children: ReactNode }) {
  return (
    <ProductionSessionProvider>
      <FixtureProvider>{children}</FixtureProvider>
    </ProductionSessionProvider>
  );
}

export function useSession(): SessionValue {
  const fixture = use(FixtureContext);
  const production = useProductionSession();
  return fixture ?? production;
}
