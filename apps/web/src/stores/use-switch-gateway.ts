import { create } from "zustand";

// Open state for the switch-gateway dialog, shared so its two triggers (the
// agent menu and the gateway settings card) open one dialog mounted at the app
// shell instead of each carrying its own copy.
interface SwitchGatewayState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const useSwitchGateway = create<SwitchGatewayState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));
