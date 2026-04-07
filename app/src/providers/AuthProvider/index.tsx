import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { connectToServer, isNewer } from "@/api";
import { clearConnection, getConnection, initConnection, authHeaders } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";

const POLL_INTERVAL_MS = 15_000;

interface AuthContextValue {
  loading: boolean;
  initialized: boolean;
  connected: boolean;
  reachable: boolean;
  version: string;
  setLoading: (loading: boolean) => void;
  setReachable: (reachable: boolean) => void;
  connect: (url: string, apiKey: string) => Promise<void>;
  disconnect: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchVersion(): Promise<string> {
  const conn = getConnection();
  if (!conn) return "";

  try {
    const resp = await fetch(`${conn.url}/version`, {
      headers: authHeaders(),
    });
    if (!resp.ok) return "";
    const data = await resp.json();
    return typeof data.version === "string" ? data.version : "";
  } catch {
    return "";
  }
}

async function triggerVestadUpdateIfNeeded(vestadVersion: string) {
  if (!vestadVersion || !isNewer(__APP_VERSION__, vestadVersion)) return;
  const conn = getConnection();
  if (!conn) return;
  try {
    await fetch(`${conn.url}/self-update`, {
      method: "POST",
      headers: authHeaders(),
    });
  } catch {
    // vestad will restart — connection loss is expected
  }
}

async function checkStoredConnection(): Promise<boolean> {
  const conn = getConnection();
  if (!conn) return false;

  const ok = await ensureFreshToken();
  if (!ok) return false;

  try {
    const resp = await fetch(`${conn.url}/version`, {
      headers: authHeaders(),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [connected, setConnected] = useState(false);
  const [reachable, setReachable] = useState(true);
  const [version, setVersion] = useState("");

  useEffect(() => {
    const init = async () => {
      await initConnection();

      const platform = detectPlatform();
      if (isTauri && platform !== "ios" && platform !== "android") {
        try {
          const { getCurrentWindow } = await import("@tauri-apps/api/window");
          const win = getCurrentWindow();
          const monitor = await import("@tauri-apps/api/window").then((module) =>
            module.currentMonitor(),
          );
          if (monitor) {
            const shortest = Math.min(
              monitor.size.width / monitor.scaleFactor,
              monitor.size.height / monitor.scaleFactor,
            );
            const size = Math.round(
              Math.max(400, Math.min(800, shortest * 0.6)),
            );
            await win.setSize(
              new (await import("@tauri-apps/api/dpi")).LogicalSize(size, size),
            );
            await win.center();
          }
        } catch { }
      }

      const ok = await checkStoredConnection();
      if (ok) {
        setConnected(true);
      }

      setInitialized(true);
    };

    void init();
  }, []);

  useEffect(() => {
    if (!connected) {
      setVersion("");
      return;
    }

    const loadVersion = async () => {
      const nextVersion = await fetchVersion();
      setVersion(nextVersion);
      void triggerVestadUpdateIfNeeded(nextVersion);
    };

    void loadVersion();
  }, [connected]);

  useEffect(() => {
    if (!connected) {
      setReachable(true);
      return;
    }

    let cancelled = false;

    const poll = async () => {
      const ok = await checkStoredConnection();
      if (!cancelled) setReachable(ok);
    };

    const id = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [connected]);

  const connect = async (url: string, apiKey: string) => {
    await connectToServer(url, apiKey);
    setConnected(true);
    const nextVersion = await fetchVersion();
    setVersion(nextVersion);
    void triggerVestadUpdateIfNeeded(nextVersion);
  };

  const disconnect = () => {
    clearConnection();
    setConnected(false);
    setReachable(true);
    setVersion("");
  };

  const value = {
    loading,
    initialized,
    connected,
    reachable,
    version,
    setLoading,
    setReachable,
    connect,
    disconnect,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
