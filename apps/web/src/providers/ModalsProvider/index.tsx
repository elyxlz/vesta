import {
  createContext,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { authenticate, type AuthStartResult } from "@/api";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

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

  const [showAuth, setShowAuth] = useState(false);
  const [authStarting, setAuthStarting] = useState(false);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authError, setAuthError] = useState("");
  const authAttemptRef = useRef(0);

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const clearAuthState = () => {
    authAttemptRef.current += 1;
    setShowAuth(false);
    setAuthStarting(false);
    setAuthStart(null);
    setAuthError("");
  };

  const handleOpenAuth = async () => {
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
    } catch (e: unknown) {
      if (authAttemptRef.current !== attemptId) return;
      setAuthError(
        (e as { message?: string })?.message || "authentication failed",
      );
    } finally {
      if (authAttemptRef.current === attemptId) {
        setAuthStarting(false);
      }
    }
  };

  const handleDelete = async () => {
    navigate("/");
    await remove();
  };

  const value: ModalsContextValue = {
    showAuth,
    authStarting,
    authStart,
    authError,
    handleOpenAuth,
    clearAuthState,
    deleteDialogOpen,
    setDeleteDialogOpen,
    handleDelete,
  };

  return (
    <ModalsContext.Provider value={value}>{children}</ModalsContext.Provider>
  );
}

export function useModals() {
  const context = useContext(ModalsContext);
  if (!context) {
    throw new Error("useModals must be used within ModalsProvider");
  }
  return context;
}
