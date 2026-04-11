import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { connectToServer } from "@/api";
import {
  clearConnection,
  getConnection,
  initConnection,
} from "@/lib/connection";
import { useTauri } from "@/providers/TauriProvider";

interface AuthContextValue {
  loading: boolean;
  initialized: boolean;
  connected: boolean;
  setLoading: (loading: boolean) => void;
  connect: (url: string, apiKey: string) => Promise<void>;
  disconnect: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function hasStoredConnection(): boolean {
  return getConnection() !== null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { isTauri, isDesktop } = useTauri();
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const init = async () => {
      await initConnection();

      if (isTauri && isDesktop) {
        try {
          const { getCurrentWindow } = await import("@tauri-apps/api/window");
          const win = getCurrentWindow();
          const monitor = await import("@tauri-apps/api/window").then(
            (module) => module.currentMonitor(),
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
        } catch {}
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
    setConnected(true);
  };

  const disconnect = () => {
    clearConnection();
    setConnected(false);
  };

  const value = {
    loading,
    initialized,
    connected,
    setLoading,
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
