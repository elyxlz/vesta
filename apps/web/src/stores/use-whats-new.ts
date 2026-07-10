import { create } from "zustand";

// Open state for the What's new dialog. A store (not lifted state) because the
// dialog mounts once at the app root (so the post-update auto-open works on any
// page) while the trigger button lives in the settings navbar.
interface WhatsNewState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const useWhatsNew = create<WhatsNewState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));
