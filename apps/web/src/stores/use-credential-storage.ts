import { create } from "zustand";
import { persist } from "zustand/middleware";

// Health of the place the app keeps its gateway tokens. `writeError` is the last failure to
// persist the connection (set by lib/connection, cleared by the next successful write), shown
// until it clears. `insecureDismissed` remembers that the user has read the desktop warning about
// an OS with no secret service, so it shows once per install.
interface CredentialStorageState {
  writeError: string | null;
  insecureDismissed: boolean;
  setWriteError: (message: string | null) => void;
  dismissInsecure: () => void;
}

export const useCredentialStorage = create<CredentialStorageState>()(
  persist(
    (set) => ({
      writeError: null,
      insecureDismissed: false,
      setWriteError: (writeError) => set({ writeError }),
      dismissInsecure: () => set({ insecureDismissed: true }),
    }),
    {
      name: "vesta-credential-storage",
      partialize: (state) => ({ insecureDismissed: state.insecureDismissed }),
    },
  ),
);
