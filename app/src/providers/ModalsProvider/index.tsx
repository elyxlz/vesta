import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { authenticate, type AuthStartResult } from "@/api";
import { openExternalUrl } from "@/lib/open-external-url";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";

interface ModalsContextValue {
  showAuth: boolean;
  authStarting: boolean;
  authStart: AuthStartResult | null;
  authError: string;
  handleOpenAuth: () => Promise<void>;
  clearAuthState: () => void;

  deleteDialogOpen: boolean;
  setDeleteDialogOpen: (open: boolean) => void;
  handleDelete: () => Promise<void>;
}

const ModalsContext = createContext<ModalsContextValue | null>(null);

export function ModalsProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { name, remove } = useSelectedAgent();
  const { refreshAgents } = useAgents();

  const [showAuth, setShowAuth] = useState(false);
  const [authStarting, setAuthStarting] = useState(false);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authError, setAuthError] = useState("");
  const authAttemptRef = useRef(0);

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const clearAuthState = useCallback(() => {
    authAttemptRef.current += 1;
    setShowAuth(false);
    setAuthStarting(false);
    setAuthStart(null);
    setAuthError("");
  }, []);

  const handleOpenAuth = useCallback(async () => {
    if (!name || authStarting) return;

    const attemptId = authAttemptRef.current + 1;
    authAttemptRef.current = attemptId;
    setShowAuth(true);
    setAuthStarting(true);
    setAuthStart(null);
    setAuthError("");

    try {
      const result = await authenticate(name);
      if (authAttemptRef.current !== attemptId) return;
      setAuthStart(result);
      void openExternalUrl(result.auth_url);
    } catch (e: unknown) {
      if (authAttemptRef.current !== attemptId) return;
      setAuthError((e as { message?: string })?.message || "authentication failed");
    } finally {
      if (authAttemptRef.current === attemptId) {
        setAuthStarting(false);
      }
    }
  }, [name, authStarting]);

  const handleDelete = useCallback(async () => {
    navigate("/home");
    await remove();
    await refreshAgents();
  }, [navigate, remove, refreshAgents]);

  const value = useMemo<ModalsContextValue>(() => ({
    showAuth,
    authStarting,
    authStart,
    authError,
    handleOpenAuth,
    clearAuthState,
    deleteDialogOpen,
    setDeleteDialogOpen,
    handleDelete,
  }), [
    showAuth, authStarting, authStart, authError,
    handleOpenAuth, clearAuthState,
    deleteDialogOpen, handleDelete,
  ]);

  return (
    <ModalsContext.Provider value={value}>
      {children}
    </ModalsContext.Provider>
  );
}

export function useModals() {
  const context = useContext(ModalsContext);
  if (!context) {
    throw new Error("useModals must be used within ModalsProvider");
  }
  return context;
}
