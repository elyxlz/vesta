import { createContext, useContext } from "react";
import type { ConnectionConfig } from "@/lib/connection";

export interface AuthContextValue {
  loading: boolean;
  initialized: boolean;
  connected: boolean;
  /** True when the stored session was rejected by vestad (refresh token
   * expired/revoked) and the user was bounced back to the connect screen. */
  sessionExpired: boolean;
  setLoading: (loading: boolean) => void;
  connect: (url: string, apiKey: string) => Promise<void>;
  connectSavedGateway: (connection: ConnectionConfig) => void;
  disconnect: () => void;
  expireSession: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
