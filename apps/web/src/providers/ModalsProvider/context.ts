import { createContext, useContext } from "react";

// Context + hook live here, separate from the ModalsProvider component, so the
// ModalsContext identity is stable across Fast Refresh. Co-locating them with the
// component made every edit re-create the context, detaching mounted consumers
// ("useModals must be used within ModalsProvider" on hot reload).
export interface ModalsContextValue {
  showAuth: boolean;
  handleOpenAuth: () => void;
  clearAuthState: () => void;

  deleteDialogOpen: boolean;
  setDeleteDialogOpen: (open: boolean) => void;
  handleDelete: () => Promise<void>;
}

export const ModalsContext = createContext<ModalsContextValue | null>(null);

export function useModals() {
  const context = useContext(ModalsContext);
  if (!context) {
    throw new Error("useModals must be used within ModalsProvider");
  }
  return context;
}
