import { create } from "zustand";

// This device's location sharing switch (browser geolocation): on by default, remembered per
// device. On makes the presence reporter ask the browser for a fix, so the OS permission prompt is
// the real consent; off retracts the position the gateway stored for this device.
const STORAGE_KEY = "vesta:share-location";

interface ShareLocationState {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
}

function loadInitial(): boolean {
  if (typeof localStorage === "undefined") return true;
  return localStorage.getItem(STORAGE_KEY) !== "off";
}

export const useShareLocation = create<ShareLocationState>((set) => ({
  enabled: loadInitial(),
  setEnabled: (enabled) => {
    localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off");
    set({ enabled });
  },
}));
