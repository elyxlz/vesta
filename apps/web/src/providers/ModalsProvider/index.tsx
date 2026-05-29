import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

interface ModalsContextValue {
  showAuth: boolean;
  handleOpenAuth: () => void;
  clearAuthState: () => void;

  deleteDialogOpen: boolean;
  setDeleteDialogOpen: (open: boolean) => void;
  handleDelete: () => Promise<void>;
}

const ModalsContext = createContext<ModalsContextValue | null>(null);

export function ModalsProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { remove } = useSelectedAgent();

  // ProviderPicker (rendered inside AgentIslandModals) owns the auth lifecycle now.
  // This provider only controls whether the dialog is open.
  const [showAuth, setShowAuth] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const handleOpenAuth = () => setShowAuth(true);
  const clearAuthState = () => setShowAuth(false);

  const handleDelete = async () => {
    navigate("/");
    await remove();
  };

  const value: ModalsContextValue = {
    showAuth,
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
