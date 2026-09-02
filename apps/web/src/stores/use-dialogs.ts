import { create } from "zustand";

// Open state for every dialog that mounts once at a shell (the app root or the agent layout)
// while its triggers live elsewhere, keyed by name so a trigger and its dialog share one flag.
type DialogName =
  "switchGateway" | "whatsNew" | "providerAuth" | "deleteAgent" | "backups";

interface DialogsState {
  open: Record<DialogName, boolean>;
  setOpen: (name: DialogName, open: boolean) => void;
}

export const useDialogs = create<DialogsState>((set) => ({
  open: {
    switchGateway: false,
    whatsNew: false,
    providerAuth: false,
    deleteAgent: false,
    backups: false,
  },
  setOpen: (name, open) =>
    set((state) => ({ open: { ...state.open, [name]: open } })),
}));
