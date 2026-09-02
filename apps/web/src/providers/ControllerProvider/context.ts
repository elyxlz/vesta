import { createContext, useContext } from "react";
import type { Controller } from "@vesta/core";

export const ControllerContext = createContext<Controller | null>(null);

// A no-op default so a consumer outside an ActiveController (before a controller exists)
// can call it harmlessly; the update path only fires once a controller exists.
export const ControllerReconnectContext = createContext<() => void>(
  () => undefined,
);

export function useController(): Controller {
  const controller = useContext(ControllerContext);
  if (!controller) {
    throw new Error("useController must be used within ControllerProvider");
  }
  return controller;
}

// For a consumer that can mount before a controller exists (the gateway, notification, and
// presence providers): the core hooks accept the null and answer with the disconnected value.
export function useOptionalController(): Controller | null {
  return useContext(ControllerContext);
}

export function useControllerReconnect(): () => void {
  return useContext(ControllerReconnectContext);
}
