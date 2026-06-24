import { useCallback, useEffect, useState, type ReactNode } from "react";
import { connectToServer } from "@/api";
import {
  clearConnection,
  getConnection,
  initConnection,
  parseConnectKey,
} from "@/lib/connection";
import { AuthContext } from "./context";

export { useAuth } from "./context";

function hasStoredConnection(): boolean {
  return getConnection() !== null;
}

/** Read the one-click connect key that `vestad status` embeds in the URL
 * fragment (`#k=...`), then strip it so the key never lingers in the address
 * bar, history, or a shared screenshot. Fragments are never sent to the
 * server, so the key stays out of request logs. Returns null when absent. */
function consumeConnectKey(): string | null {
  const key = parseConnectKey(window.location.hash);
  if (!key) return null;
  history.replaceState(
    null,
    "",
    window.location.pathname + window.location.search,
  );
  return key;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [connected, setConnected] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    const init = async () => {
      await initConnection();

      // One-click connect: a key in the URL fragment (from `vestad status`)
      // takes priority so a freshly opened link always re-pairs. Origin is the
      // vestad that served this bundle, which is exactly where the link points.
      const keyFromLink = consumeConnectKey();
      if (keyFromLink) {
        try {
          await connectToServer(window.location.origin, keyFromLink);
          setConnected(true);
          setInitialized(true);
          return;
        } catch {
          // Stale or wrong key: fall back to any stored session / manual entry.
        }
      }

      if (hasStoredConnection()) {
        setConnected(true);
      }

      setInitialized(true);
    };

    void init();
  }, []);

  const connect = async (url: string, apiKey: string) => {
    await connectToServer(url, apiKey);
    setSessionExpired(false);
    setConnected(true);
  };

  const disconnect = () => {
    clearConnection();
    setSessionExpired(false);
    setConnected(false);
  };

  // Stable (useCallback) so the gateway connect effect can list it as a dep.
  const expireSession = useCallback(() => {
    clearConnection();
    setSessionExpired(true);
    setConnected(false);
  }, []);

  const value = {
    loading,
    initialized,
    connected,
    sessionExpired,
    setLoading,
    connect,
    disconnect,
    expireSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
