import { createContext, useContext } from "react";

export interface ModalsContextValue {
  showAuth: boolean;
  handleOpenAuth: () => void;
  clearAuthState: () => void;

  deleteDialogOpen: boolean;
  setDeleteDialogOpen: (open: boolean) => void;
  handleDelete: () => Promise<void>;

  backupDialogOpen: boolean;
  setBackupDialogOpen: (open: boolean) => void;
}

export const ModalsContext = createContext<ModalsContextValue | null>(null);

export function useModals() {
  const context = useContext(ModalsContext);
  if (!context) {
    throw new Error("useModals must be used within ModalsProvider");
  }
  return context;
}
