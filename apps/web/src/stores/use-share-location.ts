import { create } from "zustand";

// This device's opt-in to share its precise location (browser geolocation), separate from the
// gateway-wide "share device context" switch: off by default, remembered per device. Turning it on
// makes the presence reporter ask the browser for a fix, which raises the OS permission prompt.
const STORAGE_KEY = "vesta:share-location";

interface ShareLocationState {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
}

function loadInitial(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(STORAGE_KEY) === "on";
}

export const useShareLocation = create<ShareLocationState>((set) => ({
  enabled: loadInitial(),
  setEnabled: (enabled) => {
    localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off");
    set({ enabled });
  },
}));
